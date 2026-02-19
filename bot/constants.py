from __future__ import annotations

from datetime import timedelta

SUPPORTED_LANGUAGES: dict[str, str] = {
    "RU": "Русский",
    "DE": "Deutsch",
    "EN": "English",
    "HY": "Հայերեն",
}

SRS_INTERVALS: tuple[timedelta, ...] = (
    timedelta(minutes=1),
    timedelta(minutes=3),
    timedelta(minutes=5),
    timedelta(minutes=10),
    timedelta(minutes=30),
    timedelta(hours=1),
    timedelta(hours=2),
    timedelta(hours=3),
    timedelta(hours=5),
    timedelta(hours=10),
    timedelta(days=1),
    timedelta(days=2),
    timedelta(days=3),
    timedelta(days=5),
    timedelta(days=7),
    timedelta(days=10),
    timedelta(days=14),
    timedelta(days=30),
    timedelta(days=60),
    timedelta(days=90),
    timedelta(days=180),
)

MAX_SRS_INDEX = len(SRS_INTERVALS) - 1

ACTIVE_PAIR_REQUIRED_COMMANDS_EXCEPTIONS: frozenset[str] = frozenset(
    {"/start"}
)
