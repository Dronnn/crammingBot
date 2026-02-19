from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from telegram.error import NetworkError, RetryAfter, TelegramError, TimedOut

logger = logging.getLogger(__name__)
T = TypeVar("T")


async def with_telegram_retry(
    action: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 1.0,
) -> T:
    attempt = 0
    delay = base_delay_seconds
    while True:
        attempt += 1
        try:
            return await action()
        except RetryAfter as exc:
            if attempt >= max_attempts:
                raise
            wait_for = float(getattr(exc, "retry_after", delay))
            logger.warning("Telegram 429 retry after %.2fs (attempt %d)", wait_for, attempt)
            await asyncio.sleep(wait_for)
        except (TimedOut, NetworkError):
            if attempt >= max_attempts:
                raise
            logger.warning(
                "Telegram network error; retry in %.2fs (attempt %d)",
                delay,
                attempt,
            )
            await asyncio.sleep(delay)
            delay *= 2
        except TelegramError as exc:
            details = str(exc)
            retryable = any(code in details for code in ("500", "502", "503", "504"))
            if (not retryable) or attempt >= max_attempts:
                raise
            logger.warning(
                "Telegram server error; retry in %.2fs (attempt %d): %s",
                delay,
                attempt,
                details,
            )
            await asyncio.sleep(delay)
            delay *= 2
