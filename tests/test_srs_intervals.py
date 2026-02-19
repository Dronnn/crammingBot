from datetime import timedelta

from bot.constants import SRS_INTERVALS


def test_srs_interval_table_matches_spec_size() -> None:
    assert len(SRS_INTERVALS) == 21


def test_srs_interval_table_edges() -> None:
    assert SRS_INTERVALS[0] == timedelta(minutes=1)
    assert SRS_INTERVALS[20] == timedelta(days=180)

