from __future__ import annotations

from datetime import date, datetime

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from bot.domain.models import UserRecord


class UsersRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def get_or_create(
        self, user_id: int, username: str | None, first_name: str | None
    ) -> UserRecord:
        query = """
        INSERT INTO users (id, username, first_name)
        VALUES (%s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            username = EXCLUDED.username,
            first_name = EXCLUDED.first_name
        RETURNING id, username, first_name, active_pair_id, reminders_enabled, timezone
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, (user_id, username, first_name))
                row = await cursor.fetchone()
            await conn.commit()
        if row is None:
            raise RuntimeError("failed to upsert user")
        return UserRecord(**row)

    async def get(self, user_id: int) -> UserRecord | None:
        query = """
        SELECT id, username, first_name, active_pair_id, reminders_enabled, timezone
        FROM users
        WHERE id = %s
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, (user_id,))
                row = await cursor.fetchone()
        return UserRecord(**row) if row else None

    async def get_active_pair_id(self, user_id: int) -> int | None:
        query = "SELECT active_pair_id FROM users WHERE id = %s"
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (user_id,))
                row = await cursor.fetchone()
        return row[0] if row else None

    async def set_active_pair_id(self, user_id: int, pair_id: int | None) -> None:
        query = "UPDATE users SET active_pair_id = %s WHERE id = %s"
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (pair_id, user_id))
            await conn.commit()

    async def set_reminders_enabled(self, user_id: int, enabled: bool) -> None:
        query = "UPDATE users SET reminders_enabled = %s WHERE id = %s"
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (enabled, user_id))
            await conn.commit()

    async def touch_training_activity(self, user_id: int, at: datetime) -> None:
        query = "UPDATE users SET last_training_at = %s WHERE id = %s"
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (at, user_id))
            await conn.commit()

    async def list_reminder_candidates(self) -> list[dict]:
        query = """
        SELECT
            id,
            active_pair_id,
            reminders_enabled,
            timezone,
            last_training_at,
            last_daily_reminder_date,
            last_intraday_reminder_at
        FROM users
        WHERE reminders_enabled = TRUE
          AND active_pair_id IS NOT NULL
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query)
                rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def mark_daily_reminder_date(self, user_id: int, local_date: date) -> None:
        query = "UPDATE users SET last_daily_reminder_date = %s WHERE id = %s"
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (local_date, user_id))
            await conn.commit()

    async def mark_intraday_reminder(self, user_id: int, at: datetime) -> None:
        query = "UPDATE users SET last_intraday_reminder_at = %s WHERE id = %s"
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (at, user_id))
            await conn.commit()
