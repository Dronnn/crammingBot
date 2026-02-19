from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from bot.constants import MAX_SRS_INDEX, SRS_INTERVALS


@dataclass(frozen=True, slots=True)
class SRSState:
    srs_index: int
    next_review_at: datetime


class SRSService:
    def interval_for_index(self, srs_index: int):
        self._validate_index(srs_index)
        return SRS_INTERVALS[srs_index]

    def apply_correct(self, current_index: int, now: datetime | None = None) -> SRSState:
        self._validate_index(current_index)
        review_time = now or datetime.now(timezone.utc)
        next_index = min(MAX_SRS_INDEX, current_index + 1)
        return SRSState(
            srs_index=next_index,
            next_review_at=review_time + self.interval_for_index(next_index),
        )

    def apply_wrong(self, current_index: int, now: datetime | None = None) -> SRSState:
        self._validate_index(current_index)
        review_time = now or datetime.now(timezone.utc)
        next_index = max(0, current_index - 3)
        return SRSState(
            srs_index=next_index,
            next_review_at=review_time + self.interval_for_index(next_index),
        )

    @staticmethod
    def _validate_index(index: int) -> None:
        if index < 0 or index > MAX_SRS_INDEX:
            raise ValueError(
                f"srs_index {index} is out of range [0, {MAX_SRS_INDEX}]"
            )

