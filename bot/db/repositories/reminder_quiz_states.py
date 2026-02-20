from __future__ import annotations

from datetime import datetime

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


class ReminderQuizStatesRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def has_pending(self, user_id: int) -> bool:
        query = "SELECT 1 FROM reminder_quiz_states WHERE user_id = %s"
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (user_id,))
                return await cursor.fetchone() is not None

    async def upsert(
        self,
        *,
        user_id: int,
        card_id: int,
        direction: str,
        source_lang: str,
        target_lang: str,
        word: str,
        translation: str,
        synonyms: tuple[str, ...],
        srs_index: int,
        sent_at: datetime,
    ) -> None:
        query = """
        INSERT INTO reminder_quiz_states (
            user_id,
            card_id,
            direction,
            source_lang,
            target_lang,
            word,
            translation,
            synonyms,
            srs_index,
            sent_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (user_id) DO UPDATE SET
            card_id = EXCLUDED.card_id,
            direction = EXCLUDED.direction,
            source_lang = EXCLUDED.source_lang,
            target_lang = EXCLUDED.target_lang,
            word = EXCLUDED.word,
            translation = EXCLUDED.translation,
            synonyms = EXCLUDED.synonyms,
            srs_index = EXCLUDED.srs_index,
            sent_at = EXCLUDED.sent_at,
            updated_at = NOW()
        """
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    query,
                    (
                        user_id,
                        card_id,
                        direction,
                        source_lang,
                        target_lang,
                        word,
                        translation,
                        list(synonyms),
                        srs_index,
                        sent_at,
                    ),
                )
            await conn.commit()

    async def get(self, user_id: int) -> dict | None:
        query = """
        SELECT
            card_id,
            direction,
            source_lang,
            target_lang,
            word,
            translation,
            synonyms,
            srs_index,
            sent_at
        FROM reminder_quiz_states
        WHERE user_id = %s
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, (user_id,))
                row = await cursor.fetchone()
        return dict(row) if row else None

    async def clear(self, user_id: int) -> None:
        query = "DELETE FROM reminder_quiz_states WHERE user_id = %s"
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (user_id,))
            await conn.commit()
