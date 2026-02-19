from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging

from telegram.ext import Application

from bot.db.repositories.cards import CardsRepository
from bot.db.repositories.users import UsersRepository
from bot.utils.telegram_retry import with_telegram_retry
from bot.utils.timezone import parse_timezone

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReminderService:
    users_repo: UsersRepository
    cards_repo: CardsRepository
    default_timezone: str = "UTC+3"

    async def run_daily(self, app: Application) -> None:
        now_utc = datetime.now(UTC)
        candidates = await self.users_repo.list_reminder_candidates()
        for user in candidates:
            user_id = int(user["id"])
            pair_id = int(user["active_pair_id"])
            tz = parse_timezone(user.get("timezone"), self.default_timezone)
            local_now = now_utc.astimezone(tz)
            if local_now.hour != 9:
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

            text = f"У вас {due_count} карточек для повторения. Начать: /train"
            await with_telegram_retry(lambda: app.bot.send_message(chat_id=user_id, text=text))
            await self.users_repo.mark_daily_reminder_date(user_id, local_date)

    async def run_intraday(self, app: Application) -> None:
        now_utc = datetime.now(UTC)
        candidates = await self.users_repo.list_reminder_candidates()
        for user in candidates:
            user_id = int(user["id"])
            pair_id = int(user["active_pair_id"])
            due_count = await self.cards_repo.count_due_for_pair(
                user_id=user_id,
                pair_id=pair_id,
                now=now_utc,
            )
            if due_count < 5:
                continue

            last_training_at = user.get("last_training_at")
            if last_training_at is not None:
                idle_for = now_utc - last_training_at.astimezone(UTC)
                if idle_for < timedelta(hours=2):
                    continue

            last_intraday = user.get("last_intraday_reminder_at")
            if last_intraday is not None:
                since_last = now_utc - last_intraday.astimezone(UTC)
                if since_last < timedelta(minutes=60):
                    continue

            text = f"У вас накопилось {due_count} карточек для повторения. Запустить: /train"
            await with_telegram_retry(lambda: app.bot.send_message(chat_id=user_id, text=text))
            await self.users_repo.mark_intraday_reminder(user_id, now_utc)

