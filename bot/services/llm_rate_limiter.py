from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import math
import time


@dataclass(frozen=True, slots=True)
class RateWindow:
    seconds: int
    user_limit: int
    global_limit: int
    name: str


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0
    scope: str = ""
    window_name: str = ""


class LLMRateLimiter:
    def __init__(self, windows: tuple[RateWindow, ...] | None = None) -> None:
        self._windows = windows or (
            RateWindow(seconds=60, user_limit=40, global_limit=200, name="1m"),
            RateWindow(seconds=3600, user_limit=300, global_limit=1200, name="1h"),
            RateWindow(seconds=86400, user_limit=1200, global_limit=5000, name="24h"),
        )
        self._max_window = max(window.seconds for window in self._windows)
        self._user_events: dict[int, deque[float]] = {}
        self._global_events: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def consume(self, *, user_id: int) -> RateLimitDecision:
        now = time.monotonic()
        async with self._lock:
            self._cleanup(now)
            user_events = self._user_events.setdefault(user_id, deque())

            for window in self._windows:
                user_count = self._count_recent(user_events, now, window.seconds)
                if user_count >= window.user_limit:
                    retry_after = self._retry_after(user_events, now, window.seconds)
                    return RateLimitDecision(
                        allowed=False,
                        retry_after_seconds=retry_after,
                        scope="user",
                        window_name=window.name,
                    )

                global_count = self._count_recent(self._global_events, now, window.seconds)
                if global_count >= window.global_limit:
                    retry_after = self._retry_after(self._global_events, now, window.seconds)
                    return RateLimitDecision(
                        allowed=False,
                        retry_after_seconds=retry_after,
                        scope="global",
                        window_name=window.name,
                    )

            user_events.append(now)
            self._global_events.append(now)
            return RateLimitDecision(allowed=True)

    def _cleanup(self, now: float) -> None:
        cutoff = now - self._max_window
        while self._global_events and self._global_events[0] < cutoff:
            self._global_events.popleft()
        stale_user_ids: list[int] = []
        for user_id, events in self._user_events.items():
            while events and events[0] < cutoff:
                events.popleft()
            if not events:
                stale_user_ids.append(user_id)
        for user_id in stale_user_ids:
            self._user_events.pop(user_id, None)

    @staticmethod
    def _count_recent(events: deque[float], now: float, window_seconds: int) -> int:
        count = 0
        for ts in reversed(events):
            if now - ts > window_seconds:
                break
            count += 1
        return count

    @staticmethod
    def _retry_after(events: deque[float], now: float, window_seconds: int) -> int:
        for ts in events:
            if now - ts <= window_seconds:
                wait = (ts + window_seconds) - now
                return max(1, int(math.ceil(wait)))
        return 1
