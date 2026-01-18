"""Cost tracking and budget monitoring for LLM API calls."""

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx


# Pricing per 1M tokens (as of 2024)
MODEL_PRICING = {
    "claude-3-5-haiku-20241022": {
        "input": 0.80,
        "output": 4.00,
        "cache_write": 1.00,
        "cache_read": 0.08,
    },
    "claude-3-5-sonnet-20241022": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
    "claude-sonnet-4-20250514": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
    "claude-opus-4-20250514": {
        "input": 15.00,
        "output": 75.00,
        "cache_write": 18.75,
        "cache_read": 1.50,
    },
}

# Default pricing for unknown models (conservative estimate)
DEFAULT_PRICING = {
    "input": 3.00,
    "output": 15.00,
    "cache_write": 3.75,
    "cache_read": 0.30,
}


@dataclass
class TokenUsage:
    """Token counts from a single API call."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    def cost(self, model: str) -> float:
        """Calculate cost in dollars for these tokens."""
        pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)

        # Cost calculation (prices are per 1M tokens)
        input_cost = (self.input_tokens / 1_000_000) * pricing["input"]
        output_cost = (self.output_tokens / 1_000_000) * pricing["output"]
        cache_write_cost = (self.cache_creation_tokens / 1_000_000) * pricing["cache_write"]
        cache_read_cost = (self.cache_read_tokens / 1_000_000) * pricing["cache_read"]

        return input_cost + output_cost + cache_write_cost + cache_read_cost

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        """Add two TokenUsage instances together."""
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_creation_tokens=self.cache_creation_tokens + other.cache_creation_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
        )

    @property
    def total_tokens(self) -> int:
        """Total tokens used (input + output)."""
        return self.input_tokens + self.output_tokens


@dataclass
class CostTracker:
    """Accumulates token usage and cost across multiple API calls."""
    total_usage: TokenUsage = field(default_factory=TokenUsage)
    api_calls: int = 0
    model: str = "claude-3-5-haiku-20241022"
    call_durations_ms: list[float] = field(default_factory=list)

    def add_usage(self, usage: TokenUsage, duration_ms: float = 0) -> None:
        """Record token usage from an API call."""
        self.total_usage = self.total_usage + usage
        self.api_calls += 1
        if duration_ms > 0:
            self.call_durations_ms.append(duration_ms)

    @property
    def total_cost(self) -> float:
        """Total cost in dollars."""
        return self.total_usage.cost(self.model)

    @property
    def avg_call_duration_ms(self) -> float:
        """Average API call duration in milliseconds."""
        if not self.call_durations_ms:
            return 0
        return sum(self.call_durations_ms) / len(self.call_durations_ms)

    def estimate_remaining_cost(self, remaining_calls: int) -> float:
        """Estimate cost for remaining API calls based on average usage."""
        if self.api_calls == 0:
            return 0
        avg_cost_per_call = self.total_cost / self.api_calls
        return avg_cost_per_call * remaining_calls

    def estimate_game_cost(self, num_players: int = 12, num_rounds: int = 8) -> float:
        """Estimate total cost for a full game.

        Rough estimate based on typical game patterns:
        - ~3 discussion turns per round per player
        - ~1 vote per round per player
        - ~3 traitor discussions per round (fewer traitors)
        - ~1 murder vote per round
        """
        # Rough calls per round: 3*n (discussion) + n (vote) + 3 (traitor talk) + 3 (murder)
        calls_per_round = 4 * num_players + 6
        total_calls = calls_per_round * num_rounds

        if self.api_calls > 0:
            # Use actual average from this game
            avg_cost = self.total_cost / self.api_calls
            return avg_cost * total_calls
        else:
            # Default estimate: ~$0.001 per call with Haiku
            return total_calls * 0.001


def get_admin_key() -> Optional[str]:
    """Get ANTHROPIC_ADMIN_KEY from environment."""
    return os.environ.get("ANTHROPIC_ADMIN_KEY")


def fetch_admin_spending(admin_key: str, days: int = 7) -> dict:
    """Fetch recent spending from Anthropic Admin API.

    Uses the usage endpoint (which has near real-time data) and calculates
    costs from token counts, since the cost endpoint has significant delays.

    Returns:
        dict with keys:
        - total_cost_usd: Total cost over the period
        - today_cost_usd: Cost for today only
        - by_day: List of {date, cost_usd} dicts
        - error: Error message if request failed (None on success)
    """
    result = {
        "total_cost_usd": 0.0,
        "today_cost_usd": 0.0,
        "by_day": [],
        "error": None,
    }

    # Calculate date range (RFC 3339 format)
    now = datetime.now(timezone.utc)
    today = now.date()
    start_date = today - timedelta(days=days - 1)

    # Use hourly usage endpoint for better granularity and faster updates
    url = "https://api.anthropic.com/v1/organizations/usage_report/messages"
    params = {
        "starting_at": f"{start_date.isoformat()}T00:00:00Z",
        "bucket_width": "1h",
        "limit": days * 24,  # hours
        "group_by[]": "model",  # Need model to calculate accurate costs
    }
    headers = {
        "x-api-key": admin_key,
        "anthropic-version": "2023-06-01",
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, params=params, headers=headers)

        if response.status_code == 401:
            result["error"] = "Invalid admin key"
            return result
        elif response.status_code == 403:
            result["error"] = "Admin key lacks permission for usage API"
            return result
        elif response.status_code != 200:
            result["error"] = f"API error: {response.status_code}"
            return result

        data = response.json()

        # Aggregate costs by day, calculating from token usage
        daily_costs: dict[str, float] = {}

        for bucket in data.get("data", []):
            # Extract date from starting_at (RFC 3339 format)
            starting_at = bucket.get("starting_at", "")
            date_str = starting_at[:10] if starting_at else ""

            for item in bucket.get("results", []):
                model = item.get("model") or "claude-3-5-haiku-20241022"
                pricing = MODEL_PRICING.get(model, DEFAULT_PRICING)

                # Calculate cost from tokens
                input_tokens = item.get("uncached_input_tokens", 0)
                output_tokens = item.get("output_tokens", 0)
                cache_read = item.get("cache_read_input_tokens", 0)

                # Cache creation tokens
                cache_creation = item.get("cache_creation", {})
                cache_write = (
                    cache_creation.get("ephemeral_5m_input_tokens", 0) +
                    cache_creation.get("ephemeral_1h_input_tokens", 0)
                )

                cost = (
                    (input_tokens / 1_000_000) * pricing["input"] +
                    (output_tokens / 1_000_000) * pricing["output"] +
                    (cache_read / 1_000_000) * pricing["cache_read"] +
                    (cache_write / 1_000_000) * pricing["cache_write"]
                )

                if date_str:
                    daily_costs[date_str] = daily_costs.get(date_str, 0.0) + cost

        # Build results
        total = sum(daily_costs.values())
        today_str = today.isoformat()
        today_cost = daily_costs.get(today_str, 0.0)

        by_day = [{"date": d, "cost_usd": c} for d, c in sorted(daily_costs.items())]

        result["total_cost_usd"] = total
        result["today_cost_usd"] = today_cost
        result["by_day"] = by_day

    except httpx.TimeoutException:
        result["error"] = "Request timed out"
    except httpx.RequestError as e:
        result["error"] = f"Request failed: {e}"
    except Exception as e:
        result["error"] = f"Unexpected error: {e}"

    return result


