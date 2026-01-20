"""API utilities for error handling and retry logic."""

import logging
import time
from functools import wraps
from typing import Callable, TypeVar, Any, Optional

# Configure logging for API failures
logger = logging.getLogger(__name__)

T = TypeVar('T')


class APIError(Exception):
    """Base class for API errors."""
    pass


class RetryableAPIError(APIError):
    """Error that can be retried (rate limits, network errors, server errors)."""
    pass


class NonRetryableAPIError(APIError):
    """Error that should not be retried (auth errors, invalid requests)."""
    pass


def is_retryable_error(error: Exception) -> bool:
    """Determine if an error should trigger a retry.

    Retryable errors include:
    - Rate limits (429)
    - Server errors (500, 502, 503, 504)
    - Connection/timeout errors
    - Overloaded errors

    Non-retryable errors include:
    - Authentication errors (401, 403)
    - Invalid request (400)
    - Not found (404)
    """
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()

    # Check for rate limit errors
    if '429' in error_str or 'rate' in error_str or 'limit' in error_str:
        return True

    # Check for server errors
    if any(code in error_str for code in ['500', '502', '503', '504']):
        return True

    # Check for overloaded errors (Anthropic specific)
    if 'overloaded' in error_str:
        return True

    # Check for connection/network errors
    network_errors = ['connection', 'timeout', 'network', 'socket', 'eof']
    if any(err in error_str or err in error_type for err in network_errors):
        return True

    # Check for common retryable exception types
    retryable_types = ['timeout', 'connection', 'ratelimit', 'overloaded', 'service']
    if any(t in error_type for t in retryable_types):
        return True

    return False


def retry_with_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    on_retry: Optional[Callable[[Exception, int, float], None]] = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator for retrying API calls with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        backoff_factor: Multiplier for delay after each retry
        on_retry: Optional callback called on each retry with (error, attempt, delay)

    Returns:
        Decorated function that will retry on retryable errors

    Example:
        @retry_with_backoff(max_retries=3)
        def call_api():
            return client.messages.create(...)
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_error: Optional[Exception] = None
            delay = initial_delay

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e

                    # Don't retry on non-retryable errors
                    if not is_retryable_error(e):
                        logger.warning(
                            f"Non-retryable API error in {func.__name__}: {type(e).__name__}: {e}"
                        )
                        raise

                    # Don't retry if we've exhausted attempts
                    if attempt >= max_retries:
                        logger.error(
                            f"API call {func.__name__} failed after {max_retries + 1} attempts: "
                            f"{type(e).__name__}: {e}"
                        )
                        raise

                    # Log retry attempt
                    logger.warning(
                        f"Retryable error in {func.__name__} (attempt {attempt + 1}/{max_retries + 1}): "
                        f"{type(e).__name__}: {e}. Retrying in {delay:.1f}s..."
                    )

                    # Call optional retry callback
                    if on_retry:
                        on_retry(e, attempt + 1, delay)

                    # Wait before retrying
                    time.sleep(delay)

                    # Increase delay for next retry (exponential backoff)
                    delay = min(delay * backoff_factor, max_delay)

            # Should not reach here, but just in case
            if last_error:
                raise last_error
            raise RuntimeError(f"Unexpected state in retry_with_backoff for {func.__name__}")

        return wrapper
    return decorator


def log_vote_parsing_failure(
    raw_response: str,
    parsed_vote: str,
    valid_candidates: list[str],
    fallback_used: str,
    player_name: str = "",
    action_type: str = "vote",
) -> None:
    """Log a vote parsing failure for debugging and monitoring.

    This replaces silent fallback behavior with proper logging so that
    LLM output quality issues can be tracked and addressed.

    Args:
        raw_response: The raw LLM response
        parsed_vote: What was extracted from the response
        valid_candidates: List of valid vote targets
        fallback_used: The fallback value that was used
        player_name: Name of the player who voted
        action_type: Type of action (vote, murder_vote, etc.)
    """
    logger.warning(
        f"Vote parsing fallback triggered: "
        f"player={player_name}, action={action_type}, "
        f"parsed='{parsed_vote}', valid={valid_candidates}, "
        f"fallback='{fallback_used}', raw_response='{raw_response[:200]}...'"
    )
