from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging

from telegram.ext import Application

from bot.constants import (
    DEFAULT_DAILY_REMINDER_HOUR,
    DEFAULT_INTRADAY_IDLE_HOURS,
    DEFAULT_INTRADAY_INTERVAL_MINUTES,
    DEFAULT_INTRADAY_MIN_DUE,
    DEFAULT_QUIET_HOURS_END,
    DEFAULT_QUIET_HOURS_START,
    SUPPORTED_LANGUAGES,
)
from bot.db.repositories.cards import CardsRepository
from bot.db.repositories.users import UsersRepository
from bot.domain.models import DueCardRecord
from bot.utils.telegram_retry import with_telegram_retry
from bot.utils.timezone import parse_timezone

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReminderService:
    users_repo: UsersRepository
    cards_repo: CardsRepository
    default_timezone: str = "UTC+3"

    @staticmethod
    def _as_int(value: object, *, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    @classmethod
    def _hour_setting(cls, value: object, *, default: int) -> int:
        hour = cls._as_int(value, default=default)
        return max(0, min(23, hour))

    @classmethod
    def _positive_setting(
        cls, value: object, *, default: int, minimum: int, maximum: int
    ) -> int:
        parsed = cls._as_int(value, default=default)
        return max(minimum, min(maximum, parsed))

    @classmethod
    def _is_quiet_hours(cls, local_hour: int, *, quiet_start: int, quiet_end: int) -> bool:
        start = cls._hour_setting(quiet_start, default=DEFAULT_QUIET_HOURS_START)
        end = cls._hour_setting(quiet_end, default=DEFAULT_QUIET_HOURS_END)
        if start == end:
            return False
        if start < end:
            return start <= local_hour < end
        return local_hour >= start or local_hour < end

    @staticmethod
    def _build_quiz_prompt(card: DueCardRecord) -> str:
        direction = f"{card.source_lang} -> {card.target_lang}"
        if card.direction == "forward":
            shown = card.translation
            ask_lang = SUPPORTED_LANGUAGES[card.target_lang]
        else:
            shown = card.word
            ask_lang = SUPPORTED_LANGUAGES[card.source_lang]
        return (
            "Мини-повторение (без запуска /train).\n"
            f"[Направление: {direction}]\n\n"
            f"Слово: {shown}\n\n"
            f"Переведите на {ask_lang} и отправьте ответ одним сообщением."
        )

    @staticmethod
    def _has_pending_quiz(app: Application, user_id: int) -> bool:
        user_state = app.user_data.get(user_id)
        if not isinstance(user_state, dict):
            return False
        return "reminder_state" in user_state

    @staticmethod
    def _store_quiz_state(
        app: Application, user_id: int, card: DueCardRecord, sent_at_utc: datetime
    ) -> None:
        user_state = app.user_data.setdefault(user_id, {})
        user_state["reminder_state"] = {
            "card_id": card.id,
            "user_id": card.user_id,
            "direction": card.direction,
            "source_lang": card.source_lang,
            "target_lang": card.target_lang,
            "word": card.word,
            "translation": card.translation,
            "synonyms": list(card.synonyms),
            "srs_index": card.srs_index,
            "sent_at": sent_at_utc.timestamp(),
        }

    async def _pick_due_card(self, user_id: int, pair_id: int, now_utc: datetime) -> DueCardRecord | None:
        cards = await self.cards_repo.list_due_cards(
            user_id=user_id,
            pair_id=pair_id,
            now=now_utc,
            set_id=None,
            limit=1,
        )
        if not cards:
            return None
        return cards[0]

    async def run_daily(self, app: Application) -> None:
        now_utc = datetime.now(UTC)
        candidates = await self.users_repo.list_reminder_candidates()
        for user in candidates:
            user_id = int(user["id"])
            pair_id = int(user["active_pair_id"])
            tz = parse_timezone(user.get("timezone"), self.default_timezone)
            local_now = now_utc.astimezone(tz)
            daily_hour = self._hour_setting(
                user.get("daily_reminder_hour"),
                default=DEFAULT_DAILY_REMINDER_HOUR,
            )
            if local_now.hour != daily_hour:
                continue

            local_date = local_now.date()
            if user.get("last_daily_reminder_date") == local_date:
                continue

            due_count = await self.cards_repo.count_due_for_pair(
                user_id=user_id,
                pair_id=pair_id,
                now=now_utc,
            )
            if due_count <= 0:
                continue

            if self._has_pending_quiz(app, user_id):
                continue

            card = await self._pick_due_card(user_id=user_id, pair_id=pair_id, now_utc=now_utc)
            if card is None:
                continue

            text = self._build_quiz_prompt(card)
            await with_telegram_retry(lambda: app.bot.send_message(chat_id=user_id, text=text))
            self._store_quiz_state(app, user_id, card, now_utc)
            await self.users_repo.mark_daily_reminder_date(user_id, local_date)

    async def run_intraday(self, app: Application) -> None:
        now_utc = datetime.now(UTC)
        candidates = await self.users_repo.list_reminder_candidates()
        for user in candidates:
            user_id = int(user["id"])
            pair_id = int(user["active_pair_id"])
            tz = parse_timezone(user.get("timezone"), self.default_timezone)
            local_now = now_utc.astimezone(tz)
            quiet_start = self._hour_setting(
                user.get("quiet_hours_start"),
                default=DEFAULT_QUIET_HOURS_START,
            )
            quiet_end = self._hour_setting(
                user.get("quiet_hours_end"),
                default=DEFAULT_QUIET_HOURS_END,
            )
            if self._is_quiet_hours(
                local_now.hour,
                quiet_start=quiet_start,
                quiet_end=quiet_end,
            ):
                continue

            due_count = await self.cards_repo.count_due_for_pair(
                user_id=user_id,
                pair_id=pair_id,
                now=now_utc,
            )
            min_due = self._positive_setting(
                user.get("intraday_min_due"),
                default=DEFAULT_INTRADAY_MIN_DUE,
                minimum=1,
                maximum=1000,
            )
            if due_count < min_due:
                continue

            last_training_at = user.get("last_training_at")
            if last_training_at is not None:
                idle_for = now_utc - last_training_at.astimezone(UTC)
                idle_hours = self._positive_setting(
                    user.get("intraday_idle_hours"),
                    default=DEFAULT_INTRADAY_IDLE_HOURS,
                    minimum=0,
                    maximum=72,
                )
                if idle_for < timedelta(hours=idle_hours):
                    continue

            last_intraday = user.get("last_intraday_reminder_at")
            if last_intraday is not None:
                since_last = now_utc - last_intraday.astimezone(UTC)
                interval_minutes = self._positive_setting(
                    user.get("intraday_interval_minutes"),
                    default=DEFAULT_INTRADAY_INTERVAL_MINUTES,
                    minimum=15,
                    maximum=24 * 60,
                )
                if since_last < timedelta(minutes=interval_minutes):
                    continue

            if self._has_pending_quiz(app, user_id):
                continue

            card = await self._pick_due_card(user_id=user_id, pair_id=pair_id, now_utc=now_utc)
            if card is None:
                continue

            text = self._build_quiz_prompt(card)
            await with_telegram_retry(lambda: app.bot.send_message(chat_id=user_id, text=text))
            self._store_quiz_state(app, user_id, card, now_utc)
            await self.users_repo.mark_intraday_reminder(user_id, now_utc)
