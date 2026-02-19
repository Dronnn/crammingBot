from datetime import datetime, timezone

from bot.constants import SRS_INTERVALS
from bot.domain.srs import SRSService


def test_apply_correct_increments_and_caps() -> None:
    service = SRSService()
    now = datetime(2026, 2, 19, 12, 0, tzinfo=timezone.utc)

    next_state = service.apply_correct(current_index=0, now=now)
    assert next_state.srs_index == 1
    assert next_state.next_review_at == now + SRS_INTERVALS[1]

    max_state = service.apply_correct(current_index=20, now=now)
    assert max_state.srs_index == 20
    assert max_state.next_review_at == now + SRS_INTERVALS[20]


def test_apply_wrong_rolls_back_three_levels() -> None:
    service = SRSService()
    now = datetime(2026, 2, 19, 12, 0, tzinfo=timezone.utc)

    rolled_back = service.apply_wrong(current_index=7, now=now)
    assert rolled_back.srs_index == 4
    assert rolled_back.next_review_at == now + SRS_INTERVALS[4]

    floor_state = service.apply_wrong(current_index=2, now=now)
    assert floor_state.srs_index == 0
    assert floor_state.next_review_at == now + SRS_INTERVALS[0]

