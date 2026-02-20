from __future__ import annotations

import asyncio
from unittest.mock import patch

from bot.services.llm_rate_limiter import LLMRateLimiter, RateWindow


def test_user_limit_blocks_after_threshold() -> None:
    limiter = LLMRateLimiter(windows=(RateWindow(seconds=60, user_limit=2, global_limit=10, name="1m"),))

    async def run_case():
        first = await limiter.consume(user_id=1)
        second = await limiter.consume(user_id=1)
        third = await limiter.consume(user_id=1)
        return first, second, third

    with patch("bot.services.llm_rate_limiter.time.monotonic", return_value=100.0):
        first, second, denied = asyncio.run(run_case())
    assert first.allowed is True
    assert second.allowed is True
    assert denied.allowed is False
    assert denied.scope == "user"
    assert denied.retry_after_seconds > 0


def test_global_limit_blocks_across_users() -> None:
    limiter = LLMRateLimiter(windows=(RateWindow(seconds=60, user_limit=10, global_limit=2, name="1m"),))

    async def run_case():
        first = await limiter.consume(user_id=1)
        second = await limiter.consume(user_id=2)
        third = await limiter.consume(user_id=3)
        return first, second, third

    with patch("bot.services.llm_rate_limiter.time.monotonic", return_value=200.0):
        first, second, denied = asyncio.run(run_case())
    assert first.allowed is True
    assert second.allowed is True
    assert denied.allowed is False
    assert denied.scope == "global"
    assert denied.retry_after_seconds > 0
