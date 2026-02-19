from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from bot.domain.models import VocabularySetRecord


class VocabularySetsRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def list_for_pair(self, user_id: int, pair_id: int) -> list[VocabularySetRecord]:
        query = """
        SELECT id, user_id, language_pair_id, name
        FROM vocabulary_sets
        WHERE user_id = %s AND language_pair_id = %s
        ORDER BY name ASC
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, (user_id, pair_id))
                rows = await cursor.fetchall()
        return [VocabularySetRecord(**row) for row in rows]

    async def get_by_id(
        self, *, user_id: int, pair_id: int, set_id: int
    ) -> VocabularySetRecord | None:
        query = """
        SELECT id, user_id, language_pair_id, name
        FROM vocabulary_sets
        WHERE id = %s AND user_id = %s AND language_pair_id = %s
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, (set_id, user_id, pair_id))
                row = await cursor.fetchone()
        return VocabularySetRecord(**row) if row else None

    async def create_or_get(
        self, *, user_id: int, pair_id: int, name: str
    ) -> VocabularySetRecord:
        query = """
        INSERT INTO vocabulary_sets (user_id, language_pair_id, name)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, language_pair_id, name) DO UPDATE SET
            name = EXCLUDED.name
        RETURNING id, user_id, language_pair_id, name
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, (user_id, pair_id, name))
                row = await cursor.fetchone()
            await conn.commit()
        if row is None:
            raise RuntimeError("failed to create vocabulary set")
        return VocabularySetRecord(**row)

