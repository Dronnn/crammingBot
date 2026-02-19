from datetime import timedelta

from bot.utils.timezone import parse_timezone


def test_parse_timezone_utc_offset() -> None:
    tz = parse_timezone("UTC+3")
    assert tz.utcoffset(None) == timedelta(hours=3)


def test_parse_timezone_fallback_when_invalid() -> None:
    tz = parse_timezone("Invalid/Zone", default="UTC+3")
    assert tz.utcoffset(None) == timedelta(hours=3)

