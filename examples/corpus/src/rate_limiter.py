"""Token bucket rate limiting for the API gateway."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class TokenBucket:
    """A token bucket that refills at ``rate`` tokens/second up to ``burst`` tokens.

    Each allowed request consumes one token, so short bursts are permitted while the
    long-run average is capped at ``rate``.
    """

    rate: float
    burst: int
    tokens: float = field(init=False)
    last_refill: float = field(init=False)

    def __post_init__(self) -> None:
        self.tokens = float(self.burst)
        self.last_refill = time.monotonic()

    def _refill(self, now: float) -> None:
        elapsed = now - self.last_refill
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        self.last_refill = now

    def allow(self, now: float | None = None) -> bool:
        """Consume a token if one is available. Returns False when rate limited."""
        self._refill(time.monotonic() if now is None else now)
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False

    def retry_after(self) -> float:
        """Seconds until the next token becomes available (for the Retry-After header)."""
        missing = max(0.0, 1 - self.tokens)
        return missing / self.rate if self.rate > 0 else float("inf")


class RateLimiter:
    """Keeps one TokenBucket per client key (API key or IP address)."""

    PLANS = {"free": (5, 20), "pro": (50, 200), "enterprise": (500, 1000)}

    def __init__(self) -> None:
        self._buckets: dict[str, TokenBucket] = {}

    def check(self, client_key: str, plan: str = "free") -> tuple[bool, float]:
        """Return ``(allowed, retry_after_seconds)`` for a request from ``client_key``."""
        bucket = self._buckets.get(client_key)
        if bucket is None:
            rate, burst = self.PLANS.get(plan, self.PLANS["free"])
            bucket = self._buckets[client_key] = TokenBucket(rate, burst)
        allowed = bucket.allow()
        return allowed, 0.0 if allowed else bucket.retry_after()
