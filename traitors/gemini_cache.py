"""Cache manager for Gemini context caching."""

import hashlib
from typing import Optional

from google import genai
from google.genai import types


# Minimum token thresholds for caching (below this, skip caching)
MIN_CACHE_TOKENS = {
    "gemini-2.0-flash-lite": 1024,
    "gemini-2.0-flash": 1024,
    "gemini-1.5-flash": 1024,
    "gemini-1.5-pro": 4096,
}
DEFAULT_MIN_TOKENS = 1024

# Cache TTL in seconds (matches Anthropic ephemeral ~5 min)
CACHE_TTL_SECONDS = 300


class GeminiCacheManager:
    """Manages Gemini context caches with TTL and content tracking.

    Caches system instructions + conversation history for reuse across
    multiple players, similar to Anthropic's prompt caching strategy.
    """

    def __init__(self, client: genai.Client, model: str):
        """Initialize the cache manager.

        Args:
            client: The google-genai client
            model: Model name (e.g., "gemini-2.0-flash-lite")
        """
        self.client = client
        self.model = model
        self._active_cache: Optional[types.CachedContent] = None
        self._cache_content_hash: Optional[str] = None

    def _get_min_tokens(self) -> int:
        """Get minimum token threshold for this model."""
        return MIN_CACHE_TOKENS.get(self.model, DEFAULT_MIN_TOKENS)

    def _hash_content(self, system_instruction: str, history_content: str) -> str:
        """Create a hash of the content to detect changes."""
        combined = f"{system_instruction}\n---\n{history_content}"
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation (4 chars per token average)."""
        return len(text) // 4

    def get_or_create_cache(
        self,
        system_instruction: str,
        history_content: str
    ) -> Optional[str]:
        """Get existing cache or create new one if content meets threshold.

        Args:
            system_instruction: The system prompt
            history_content: Conversation history to cache

        Returns:
            Cache name if caching is used, None otherwise
        """
        # Check token threshold
        combined_content = f"{system_instruction}\n{history_content}"
        estimated_tokens = self._estimate_tokens(combined_content)

        if estimated_tokens < self._get_min_tokens():
            return None

        # Check if we can reuse existing cache
        content_hash = self._hash_content(system_instruction, history_content)

        if self._active_cache and self._cache_content_hash == content_hash:
            # Content unchanged, reuse existing cache
            return self._active_cache.name

        # Delete old cache if exists
        self._delete_active_cache()

        # Create new cache
        try:
            cache = self.client.caches.create(
                model=self.model,
                config=types.CreateCachedContentConfig(
                    system_instruction=system_instruction,
                    contents=[
                        types.Content(
                            role="user",
                            parts=[types.Part(text=history_content)]
                        )
                    ],
                    ttl=f"{CACHE_TTL_SECONDS}s",
                )
            )
            self._active_cache = cache
            self._cache_content_hash = content_hash
            return cache.name
        except Exception:
            # If caching fails, continue without it
            return None

    def _delete_active_cache(self) -> None:
        """Delete the active cache if it exists."""
        if self._active_cache:
            try:
                self.client.caches.delete(name=self._active_cache.name)
            except Exception:
                pass  # Ignore deletion errors (cache may have expired)
            self._active_cache = None
            self._cache_content_hash = None

    def cleanup(self) -> None:
        """Clean up any active caches. Call at end of game."""
        self._delete_active_cache()
