from __future__ import annotations

import re
from datetime import UTC, timedelta, timezone
from zoneinfo import ZoneInfo

_UTC_OFFSET_RE = re.compile(r"^UTC([+-])(\d{1,2})(?::?(\d{2}))?$", flags=re.IGNORECASE)


def parse_timezone(value: str | None, default: str = "UTC+3"):
    candidate = (value or "").strip()
    if not candidate:
        candidate = default

    match = _UTC_OFFSET_RE.match(candidate)
    if match:
        sign, hours_raw, minutes_raw = match.groups()
        hours = int(hours_raw)
        minutes = int(minutes_raw or 0)
        delta = timedelta(hours=hours, minutes=minutes)
        if sign == "-":
            delta = -delta
        return timezone(delta)

    if candidate.upper() == "UTC":
        return UTC

    try:
        return ZoneInfo(candidate)
    except Exception:
        fallback = _UTC_OFFSET_RE.match(default)
        if fallback:
            sign, hours_raw, minutes_raw = fallback.groups()
            delta = timedelta(hours=int(hours_raw), minutes=int(minutes_raw or 0))
            if sign == "-":
                delta = -delta
            return timezone(delta)
        return timezone(timedelta(hours=3))

