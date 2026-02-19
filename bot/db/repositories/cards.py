from __future__ import annotations

from datetime import datetime

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from bot.domain.models import DueCardRecord, ExampleRecord


class CardsRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def count_all_for_pair(
        self, *, user_id: int, pair_id: int, set_id: int | None = None
    ) -> int:
        if set_id is None:
            query = """
            SELECT COUNT(*)
            FROM cards c
            JOIN words w ON w.id = c.word_id
            WHERE c.user_id = %s AND c.language_pair_id = %s
            """
            params = (user_id, pair_id)
        else:
            query = """
            SELECT COUNT(*)
            FROM cards c
            JOIN words w ON w.id = c.word_id
            WHERE c.user_id = %s AND c.language_pair_id = %s AND w.vocabulary_set_id = %s
            """
            params = (user_id, pair_id, set_id)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, params)
                row = await cursor.fetchone()
        return int(row[0] if row else 0)

    async def count_due_for_pair(
        self,
        *,
        user_id: int,
        pair_id: int,
        now: datetime,
        set_id: int | None = None,
    ) -> int:
        if set_id is None:
            query = """
            SELECT COUNT(*)
            FROM cards c
            JOIN words w ON w.id = c.word_id
            WHERE c.user_id = %s
              AND c.language_pair_id = %s
              AND c.next_review_at <= %s
            """
            params = (user_id, pair_id, now)
        else:
            query = """
            SELECT COUNT(*)
            FROM cards c
            JOIN words w ON w.id = c.word_id
            WHERE c.user_id = %s
              AND c.language_pair_id = %s
              AND c.next_review_at <= %s
              AND w.vocabulary_set_id = %s
            """
            params = (user_id, pair_id, now, set_id)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, params)
                row = await cursor.fetchone()
        return int(row[0] if row else 0)

    async def next_review_at(
        self, *, user_id: int, pair_id: int, set_id: int | None = None
    ) -> datetime | None:
        if set_id is None:
            query = """
            SELECT MIN(next_review_at)
            FROM cards c
            JOIN words w ON w.id = c.word_id
            WHERE c.user_id = %s
              AND c.language_pair_id = %s
            """
            params = (user_id, pair_id)
        else:
            query = """
            SELECT MIN(next_review_at)
            FROM cards c
            JOIN words w ON w.id = c.word_id
            WHERE c.user_id = %s
              AND c.language_pair_id = %s
              AND w.vocabulary_set_id = %s
            """
            params = (user_id, pair_id, set_id)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, params)
                row = await cursor.fetchone()
        if not row or row[0] is None:
            return None
        return row[0]

    async def list_due_cards(
        self,
        *,
        user_id: int,
        pair_id: int,
        now: datetime,
        set_id: int | None = None,
        limit: int = 200,
    ) -> list[DueCardRecord]:
        if set_id is None:
            where_clause = ""
            params: tuple = (user_id, pair_id, now, limit)
        else:
            where_clause = "AND w.vocabulary_set_id = %s"
            params = (user_id, pair_id, now, set_id, limit)
        query = f"""
        SELECT
            c.id,
            c.user_id,
            c.word_id,
            c.language_pair_id,
            c.direction,
            c.srs_index,
            c.next_review_at,
            c.correct_count,
            c.incorrect_count,
            lp.source_lang,
            lp.target_lang,
            w.word,
            w.translation,
            w.synonyms,
            w.gender,
            w.declension,
            w.tts_word_file_id,
            (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'sentence', e.sentence,
                        'translation_ru', e.translation_ru,
                        'translation_de', e.translation_de,
                        'translation_en', e.translation_en,
                        'translation_hy', e.translation_hy,
                        'tts_file_id', e.tts_file_id,
                        'sort_order', e.sort_order
                    )
                    ORDER BY e.sort_order ASC, e.id ASC
                )
                FROM examples e
                WHERE e.word_id = w.id
            ) AS examples
        FROM cards c
        JOIN words w ON w.id = c.word_id
        JOIN language_pairs lp ON lp.id = c.language_pair_id
        WHERE c.user_id = %s
          AND c.language_pair_id = %s
          AND c.next_review_at <= %s
          {where_clause}
        ORDER BY c.next_review_at ASC
        LIMIT %s
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, params)
                rows = await cursor.fetchall()
        return [_row_to_due_card(row) for row in rows]

    async def list_due_page(
        self,
        *,
        user_id: int,
        pair_id: int,
        now: datetime,
        page: int,
        page_size: int = 20,
        set_id: int | None = None,
    ) -> list[dict]:
        offset = page * page_size
        if set_id is None:
            query = """
            SELECT
                c.id,
                c.next_review_at,
                w.word,
                w.translation,
                c.direction,
                c.srs_index
            FROM cards c
            JOIN words w ON w.id = c.word_id
            WHERE c.user_id = %s
              AND c.language_pair_id = %s
              AND c.next_review_at <= %s
            ORDER BY c.next_review_at ASC
            LIMIT %s OFFSET %s
            """
            params = (user_id, pair_id, now, page_size, offset)
        else:
            query = """
            SELECT
                c.id,
                c.next_review_at,
                w.word,
                w.translation,
                c.direction,
                c.srs_index
            FROM cards c
            JOIN words w ON w.id = c.word_id
            WHERE c.user_id = %s
              AND c.language_pair_id = %s
              AND c.next_review_at <= %s
              AND w.vocabulary_set_id = %s
            ORDER BY c.next_review_at ASC
            LIMIT %s OFFSET %s
            """
            params = (user_id, pair_id, now, set_id, page_size, offset)
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, params)
                rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def update_after_correct(
        self,
        *,
        card_id: int,
        next_index: int,
        next_review_at: datetime,
    ) -> None:
        query = """
        UPDATE cards
        SET srs_index = %s,
            next_review_at = %s,
            correct_count = correct_count + 1
        WHERE id = %s
        """
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (next_index, next_review_at, card_id))
            await conn.commit()

    async def update_after_wrong(
        self,
        *,
        card_id: int,
        next_index: int,
        next_review_at: datetime,
    ) -> None:
        query = """
        UPDATE cards
        SET srs_index = %s,
            next_review_at = %s,
            incorrect_count = incorrect_count + 1
        WHERE id = %s
        """
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (next_index, next_review_at, card_id))
            await conn.commit()


def _row_to_due_card(row: dict) -> DueCardRecord:
    examples_raw = row.get("examples") or []
    examples = tuple(
        ExampleRecord(
            sentence=str(item.get("sentence", "")),
            translation_ru=str(item.get("translation_ru", "")),
            translation_de=str(item.get("translation_de", "")),
            translation_en=str(item.get("translation_en", "")),
            translation_hy=str(item.get("translation_hy", "")),
            tts_file_id=item.get("tts_file_id"),
            sort_order=int(item.get("sort_order", 0)),
        )
        for item in examples_raw
    )

    synonyms_raw = row.get("synonyms") or []
    synonyms = tuple(str(item) for item in synonyms_raw if str(item).strip())

    declension_raw = row.get("declension")
    declension: dict[str, str] | None = None
    if isinstance(declension_raw, dict):
        declension = {str(k): str(v) for k, v in declension_raw.items()}

    return DueCardRecord(
        id=row["id"],
        user_id=row["user_id"],
        word_id=row["word_id"],
        language_pair_id=row["language_pair_id"],
        direction=row["direction"],
        srs_index=row["srs_index"],
        next_review_at=row["next_review_at"],
        correct_count=row["correct_count"],
        incorrect_count=row["incorrect_count"],
        source_lang=row["source_lang"],
        target_lang=row["target_lang"],
        word=row["word"],
        translation=row["translation"],
        synonyms=synonyms,
        gender=row.get("gender"),
        declension=declension,
        tts_word_file_id=row.get("tts_word_file_id"),
        examples=examples,
    )

