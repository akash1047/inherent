"""Token bucket rate limiter implementation.

This module provides an in-memory rate limiter using the token bucket algorithm.
Supports per-key rate limiting with configurable limits and windows.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Protocol


@dataclass
class RateLimitInfo:
    """Current rate limit state for a key."""

    limit: int
    remaining: int
    reset_at: float  # Unix timestamp
    window_seconds: int

    @property
    def reset_in_seconds(self) -> int:
        """Seconds until the rate limit resets."""
        return max(0, int(self.reset_at - time.time()))


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    info: RateLimitInfo


class RateLimiterBackend(Protocol):
    """Protocol for rate limiter backends."""

    async def check_and_consume(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        """Check rate limit and consume a token if allowed.

        Args:
            key: Unique identifier (e.g., API key ID).
            limit: Maximum requests allowed per window.
            window_seconds: Time window in seconds.

        Returns:
            RateLimitResult indicating if request is allowed.
        """
        ...

    async def get_info(self, key: str, limit: int, window_seconds: int) -> RateLimitInfo:
        """Get current rate limit info without consuming.

        Args:
            key: Unique identifier (e.g., API key ID).
            limit: Maximum requests allowed per window.
            window_seconds: Time window in seconds.

        Returns:
            Current rate limit state.
        """
        ...


@dataclass
class _BucketState:
    """Internal state for a single rate limit bucket."""

    tokens: float
    last_update: float
    window_start: float


class InMemoryBackend:
    """In-memory rate limiter backend using token bucket algorithm.

    This backend stores rate limit state in memory and is suitable for
    single-instance deployments. For distributed deployments, use Redis.
    """

    def __init__(self) -> None:
        self._buckets: dict[str, _BucketState] = {}
        self._lock = asyncio.Lock()
        self._cleanup_interval = 300  # Clean up every 5 minutes
        self._last_cleanup = time.time()

    async def check_and_consume(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        """Check rate limit and consume a token if allowed."""
        async with self._lock:
            now = time.time()

            # Periodic cleanup of stale buckets
            if now - self._last_cleanup > self._cleanup_interval:
                await self._cleanup_stale_buckets(window_seconds)
                self._last_cleanup = now

            bucket = self._get_or_create_bucket(key, limit, now)

            # Refill tokens based on time elapsed
            self._refill_tokens(bucket, limit, window_seconds, now)

            # Check if we have tokens available
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                remaining = int(bucket.tokens)
                reset_at = bucket.window_start + window_seconds

                return RateLimitResult(
                    allowed=True,
                    info=RateLimitInfo(
                        limit=limit,
                        remaining=remaining,
                        reset_at=reset_at,
                        window_seconds=window_seconds,
                    ),
                )
            else:
                # Rate limited
                reset_at = bucket.window_start + window_seconds
                return RateLimitResult(
                    allowed=False,
                    info=RateLimitInfo(
                        limit=limit,
                        remaining=0,
                        reset_at=reset_at,
                        window_seconds=window_seconds,
                    ),
                )

    async def get_info(self, key: str, limit: int, window_seconds: int) -> RateLimitInfo:
        """Get current rate limit info without consuming."""
        async with self._lock:
            now = time.time()
            bucket = self._get_or_create_bucket(key, limit, now)
            self._refill_tokens(bucket, limit, window_seconds, now)

            return RateLimitInfo(
                limit=limit,
                remaining=int(bucket.tokens),
                reset_at=bucket.window_start + window_seconds,
                window_seconds=window_seconds,
            )

    def _get_or_create_bucket(self, key: str, limit: int, now: float) -> _BucketState:
        """Get existing bucket or create new one."""
        if key not in self._buckets:
            self._buckets[key] = _BucketState(
                tokens=float(limit),
                last_update=now,
                window_start=now,
            )
        return self._buckets[key]

    def _refill_tokens(
        self,
        bucket: _BucketState,
        limit: int,
        window_seconds: int,
        now: float,
    ) -> None:
        """Refill tokens based on elapsed time (sliding window)."""
        elapsed = now - bucket.last_update

        # Calculate tokens to add based on refill rate
        refill_rate = limit / window_seconds  # tokens per second
        tokens_to_add = elapsed * refill_rate

        bucket.tokens = min(float(limit), bucket.tokens + tokens_to_add)
        bucket.last_update = now

        # Reset window if we've fully refilled
        if bucket.tokens >= limit:
            bucket.window_start = now

    async def _cleanup_stale_buckets(self, window_seconds: int) -> None:
        """Remove buckets that haven't been used recently."""
        now = time.time()
        stale_threshold = window_seconds * 2  # Keep for 2x the window

        stale_keys = [
            key
            for key, bucket in self._buckets.items()
            if now - bucket.last_update > stale_threshold
        ]

        for key in stale_keys:
            del self._buckets[key]


class TokenBucketRateLimiter:
    """Token bucket rate limiter with pluggable backend.

    This is the main interface for rate limiting. By default uses an
    in-memory backend, but can be configured with Redis for distributed
    rate limiting.
    """

    def __init__(self, backend: RateLimiterBackend | None = None) -> None:
        """Initialize rate limiter.

        Args:
            backend: Rate limiter backend. Defaults to InMemoryBackend.
        """
        self._backend = backend or InMemoryBackend()

    async def check_rate_limit(
        self, key: str, limit: int, window_seconds: int = 60
    ) -> RateLimitResult:
        """Check if a request is allowed and consume a token.

        Args:
            key: Unique identifier (e.g., API key ID or user ID).
            limit: Maximum requests allowed per window.
            window_seconds: Time window in seconds. Default 60.

        Returns:
            RateLimitResult with allowed status and current state.
        """
        return await self._backend.check_and_consume(key, limit, window_seconds)

    async def get_current_state(
        self, key: str, limit: int, window_seconds: int = 60
    ) -> RateLimitInfo:
        """Get current rate limit state without consuming.

        Args:
            key: Unique identifier (e.g., API key ID or user ID).
            limit: Maximum requests allowed per window.
            window_seconds: Time window in seconds. Default 60.

        Returns:
            Current rate limit state.
        """
        return await self._backend.get_info(key, limit, window_seconds)


# Global rate limiter instance
_rate_limiter: TokenBucketRateLimiter | None = None


def get_rate_limiter() -> TokenBucketRateLimiter:
    """Get the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = TokenBucketRateLimiter()
    return _rate_limiter


def set_rate_limiter(limiter: TokenBucketRateLimiter) -> None:
    """Set the global rate limiter instance (for testing)."""
    global _rate_limiter
    _rate_limiter = limiter
