from __future__ import annotations

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from bot.domain.models import LanguageCode, LanguagePairRecord
from bot.errors import RepositoryError


class LanguagePairsRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def get_by_id(self, pair_id: int) -> LanguagePairRecord | None:
        query = """
        SELECT id, user_id, source_lang, target_lang, created_at
        FROM language_pairs
        WHERE id = %s
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, (pair_id,))
                row = await cursor.fetchone()
        return LanguagePairRecord(**row) if row else None

    async def list_for_user(self, user_id: int) -> list[LanguagePairRecord]:
        query = """
        SELECT id, user_id, source_lang, target_lang, created_at
        FROM language_pairs
        WHERE user_id = %s
        ORDER BY created_at ASC
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, (user_id,))
                rows = await cursor.fetchall()
        return [LanguagePairRecord(**row) for row in rows]

    async def create_or_get(
        self, user_id: int, source_lang: LanguageCode, target_lang: LanguageCode
    ) -> LanguagePairRecord:
        query = """
        INSERT INTO language_pairs (user_id, source_lang, target_lang)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, source_lang, target_lang) DO UPDATE SET
            source_lang = EXCLUDED.source_lang,
            target_lang = EXCLUDED.target_lang
        RETURNING id, user_id, source_lang, target_lang, created_at
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, (user_id, source_lang, target_lang))
                row = await cursor.fetchone()
            await conn.commit()
        if row is None:
            raise RepositoryError("failed to create language pair")
        return LanguagePairRecord(**row)

    async def ensure_belongs_to_user(self, pair_id: int, user_id: int) -> None:
        query = "SELECT 1 FROM language_pairs WHERE id = %s AND user_id = %s"
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (pair_id, user_id))
                row = await cursor.fetchone()
        if row is None:
            raise RepositoryError("language pair does not belong to user")
