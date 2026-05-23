"""Unit tests for the token bucket rate limiter."""

import asyncio
import time

import pytest

from src.core.rate_limiter import (
    InMemoryBackend,
    RateLimitInfo,
    TokenBucketRateLimiter,
)


class TestRateLimitInfo:
    """Tests for RateLimitInfo dataclass."""

    def test_reset_in_seconds_positive(self):
        """Test reset_in_seconds when reset is in the future."""
        info = RateLimitInfo(
            limit=100,
            remaining=50,
            reset_at=time.time() + 30,
            window_seconds=60,
        )
        assert 28 <= info.reset_in_seconds <= 30

    def test_reset_in_seconds_zero(self):
        """Test reset_in_seconds when reset is in the past."""
        info = RateLimitInfo(
            limit=100,
            remaining=50,
            reset_at=time.time() - 10,
            window_seconds=60,
        )
        assert info.reset_in_seconds == 0


class TestInMemoryBackend:
    """Tests for InMemoryBackend."""

    @pytest.fixture
    def backend(self) -> InMemoryBackend:
        return InMemoryBackend()

    @pytest.mark.asyncio
    async def test_first_request_allowed(self, backend: InMemoryBackend):
        """First request should always be allowed."""
        result = await backend.check_and_consume("key1", limit=10, window_seconds=60)
        assert result.allowed is True
        assert result.info.remaining == 9
        assert result.info.limit == 10

    @pytest.mark.asyncio
    async def test_multiple_requests_consume_tokens(self, backend: InMemoryBackend):
        """Multiple requests should consume tokens."""
        for i in range(5):
            result = await backend.check_and_consume("key1", limit=10, window_seconds=60)
            assert result.allowed is True
            assert result.info.remaining == 10 - i - 1

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self, backend: InMemoryBackend):
        """Requests should be denied when limit is exceeded."""
        # Consume all tokens
        for _ in range(10):
            await backend.check_and_consume("key1", limit=10, window_seconds=60)

        # Next request should be denied
        result = await backend.check_and_consume("key1", limit=10, window_seconds=60)
        assert result.allowed is False
        assert result.info.remaining == 0

    @pytest.mark.asyncio
    async def test_different_keys_independent(self, backend: InMemoryBackend):
        """Different keys should have independent limits."""
        # Exhaust key1
        for _ in range(5):
            await backend.check_and_consume("key1", limit=5, window_seconds=60)

        # key1 should be rate limited
        result1 = await backend.check_and_consume("key1", limit=5, window_seconds=60)
        assert result1.allowed is False

        # key2 should still be allowed
        result2 = await backend.check_and_consume("key2", limit=5, window_seconds=60)
        assert result2.allowed is True

    @pytest.mark.asyncio
    async def test_tokens_refill_over_time(self, backend: InMemoryBackend):
        """Tokens should refill based on elapsed time."""
        # Consume all tokens
        for _ in range(10):
            await backend.check_and_consume("key1", limit=10, window_seconds=1)

        # Should be rate limited
        result = await backend.check_and_consume("key1", limit=10, window_seconds=1)
        assert result.allowed is False

        # Wait for refill
        await asyncio.sleep(0.2)

        # Should have some tokens now
        result = await backend.check_and_consume("key1", limit=10, window_seconds=1)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_get_info_does_not_consume(self, backend: InMemoryBackend):
        """get_info should not consume tokens."""
        # Check info twice
        info1 = await backend.get_info("key1", limit=10, window_seconds=60)
        info2 = await backend.get_info("key1", limit=10, window_seconds=60)

        assert info1.remaining == info2.remaining


class TestTokenBucketRateLimiter:
    """Tests for TokenBucketRateLimiter."""

    @pytest.fixture
    def limiter(self) -> TokenBucketRateLimiter:
        return TokenBucketRateLimiter()

    @pytest.mark.asyncio
    async def test_check_rate_limit_allowed(self, limiter: TokenBucketRateLimiter):
        """Rate limit check should return allowed=True when tokens available."""
        result = await limiter.check_rate_limit("key1", limit=100, window_seconds=60)
        assert result.allowed is True
        assert result.info.remaining == 99

    @pytest.mark.asyncio
    async def test_check_rate_limit_denied(self, limiter: TokenBucketRateLimiter):
        """Rate limit check should return allowed=False when tokens exhausted."""
        # Exhaust tokens
        for _ in range(5):
            await limiter.check_rate_limit("key1", limit=5, window_seconds=60)

        result = await limiter.check_rate_limit("key1", limit=5, window_seconds=60)
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_get_current_state(self, limiter: TokenBucketRateLimiter):
        """Should return current state without consuming."""
        await limiter.check_rate_limit("key1", limit=10, window_seconds=60)

        state = await limiter.get_current_state("key1", limit=10, window_seconds=60)
        assert state.remaining == 9

        # Check again - should be the same
        state2 = await limiter.get_current_state("key1", limit=10, window_seconds=60)
        assert state2.remaining == 9
