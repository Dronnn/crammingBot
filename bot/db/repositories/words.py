from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from bot.domain.normalization import search_variants
from bot.domain.content import ExampleContent, GeneratedWordContent
from bot.domain.models import ExampleRecord, WordRecord


class WordsRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def create_word_bundle(
        self,
        *,
        user_id: int,
        pair_id: int,
        set_id: int | None,
        content: GeneratedWordContent,
        next_review_at: datetime,
    ) -> int:
        insert_word_sql = """
        INSERT INTO words (
            user_id, language_pair_id, vocabulary_set_id, word, translation, synonyms,
            part_of_speech, gender, declension, transcription
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s)
        RETURNING id
        """
        insert_example_sql = """
        INSERT INTO examples (
            word_id, sentence, translation_ru, translation_de, translation_en, translation_hy, sort_order
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        insert_card_sql = """
        INSERT INTO cards (
            user_id, word_id, language_pair_id, direction, srs_index, next_review_at
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        """

        async with self._pool.connection() as conn:
            try:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        insert_word_sql,
                        (
                            user_id,
                            pair_id,
                            set_id,
                            content.word,
                            content.translation,
                            json.dumps(list(content.synonyms), ensure_ascii=False),
                            content.part_of_speech,
                            content.gender,
                            json.dumps(content.declension or {}, ensure_ascii=False),
                            content.transcription,
                        ),
                    )
                    row = await cursor.fetchone()
                    if row is None:
                        raise RuntimeError("failed to insert word")
                    word_id = int(row[0])

                    for index, example in enumerate(content.examples):
                        await cursor.execute(
                            insert_example_sql,
                            (
                                word_id,
                                example.sentence,
                                example.translation_ru,
                                example.translation_de,
                                example.translation_en,
                                example.translation_hy,
                                index,
                            ),
                        )

                    await cursor.execute(
                        insert_card_sql,
                        (user_id, word_id, pair_id, "forward", 0, next_review_at),
                    )
                    await cursor.execute(
                        insert_card_sql,
                        (user_id, word_id, pair_id, "reverse", 0, next_review_at),
                    )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
        return word_id

    async def update_tts_word_file_id(self, *, word_id: int, file_id: str | None) -> None:
        query = "UPDATE words SET tts_word_file_id = %s WHERE id = %s"
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (file_id, word_id))
            await conn.commit()

    async def exists_word_translation(
        self,
        *,
        user_id: int,
        pair_id: int,
        word: str,
        translation: str,
    ) -> bool:
        query = """
        SELECT 1
        FROM words
        WHERE user_id = %s
          AND language_pair_id = %s
          AND lower(word) = lower(%s)
          AND lower(translation) = lower(%s)
        LIMIT 1
        """
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (user_id, pair_id, word, translation))
                row = await cursor.fetchone()
        return row is not None

    async def find_by_word(
        self,
        *,
        user_id: int,
        pair_id: int,
        word: str,
    ) -> WordRecord | None:
        query = """
        SELECT
            id, user_id, language_pair_id, vocabulary_set_id, word, translation, synonyms,
            part_of_speech, gender, declension, transcription, note, tts_word_file_id
        FROM words
        WHERE user_id = %s AND language_pair_id = %s AND lower(word) = lower(%s)
        ORDER BY id ASC
        LIMIT 1
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, (user_id, pair_id, word))
                row = await cursor.fetchone()
        return _row_to_word_record(row) if row else None

    async def find_by_word_for_lookup(
        self,
        *,
        user_id: int,
        pair_id: int,
        word: str,
    ) -> WordRecord | None:
        exact = await self.find_by_word(user_id=user_id, pair_id=pair_id, word=word)
        if exact is not None:
            return exact

        target_variants = search_variants(word)
        if not target_variants:
            return None

        query = """
        SELECT
            id, user_id, language_pair_id, vocabulary_set_id, word, translation, synonyms,
            part_of_speech, gender, declension, transcription, note, tts_word_file_id
        FROM words
        WHERE user_id = %s AND language_pair_id = %s
        ORDER BY id ASC
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, (user_id, pair_id))
                rows = await cursor.fetchall()

        for row in rows:
            if not isinstance(row, dict):
                continue
            candidate_word = str(row.get("word") or "")
            candidate_variants = search_variants(candidate_word)
            if target_variants.intersection(candidate_variants):
                return _row_to_word_record(row)
        return None

    async def get_by_id(
        self,
        *,
        user_id: int,
        pair_id: int,
        word_id: int,
    ) -> WordRecord | None:
        query = """
        SELECT
            id, user_id, language_pair_id, vocabulary_set_id, word, translation, synonyms,
            part_of_speech, gender, declension, transcription, note, tts_word_file_id
        FROM words
        WHERE id = %s AND user_id = %s AND language_pair_id = %s
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, (word_id, user_id, pair_id))
                row = await cursor.fetchone()
        return _row_to_word_record(row) if row else None

    async def list_examples(self, *, word_id: int) -> tuple[ExampleRecord, ...]:
        query = """
        SELECT sentence, translation_ru, translation_de, translation_en, translation_hy, tts_file_id, sort_order
        FROM examples
        WHERE word_id = %s
        ORDER BY sort_order ASC, id ASC
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, (word_id,))
                rows = await cursor.fetchall()
        return tuple(
            ExampleRecord(
                sentence=row["sentence"],
                translation_ru=row["translation_ru"] or "",
                translation_de=row["translation_de"] or "",
                translation_en=row["translation_en"] or "",
                translation_hy=row["translation_hy"] or "",
                tts_file_id=row.get("tts_file_id"),
                sort_order=row.get("sort_order", 0),
            )
            for row in rows
        )

    async def get_full_snapshot(self, *, word_id: int) -> dict[str, Any] | None:
        query = "SELECT payload FROM word_full_snapshots WHERE word_id = %s"
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, (word_id,))
                row = await cursor.fetchone()
        if not row:
            return None
        payload = row.get("payload")
        return payload if isinstance(payload, dict) else None

    async def upsert_full_snapshot(self, *, word_id: int, payload: dict[str, Any]) -> None:
        query = """
        INSERT INTO word_full_snapshots (word_id, payload)
        VALUES (%s, %s::jsonb)
        ON CONFLICT (word_id) DO UPDATE
        SET payload = EXCLUDED.payload,
            updated_at = NOW()
        """
        payload_json = json.dumps(payload, ensure_ascii=False)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (word_id, payload_json))
            await conn.commit()

    async def count_words(
        self,
        *,
        user_id: int,
        pair_id: int,
        set_id: int | None = None,
    ) -> int:
        if set_id is None:
            query = """
            SELECT COUNT(*)
            FROM words
            WHERE user_id = %s AND language_pair_id = %s
            """
            params = (user_id, pair_id)
        else:
            query = """
            SELECT COUNT(*)
            FROM words
            WHERE user_id = %s AND language_pair_id = %s AND vocabulary_set_id = %s
            """
            params = (user_id, pair_id, set_id)
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, params)
                row = await cursor.fetchone()
        return int(row[0] if row else 0)

    async def list_words_page(
        self,
        *,
        user_id: int,
        pair_id: int,
        page: int,
        page_size: int = 20,
        set_id: int | None = None,
    ) -> list[dict]:
        offset = page * page_size
        if set_id is None:
            query = """
            SELECT
                w.id,
                w.word,
                w.translation,
                COALESCE(cf.srs_index, 0) AS forward_srs_index
            FROM words w
            LEFT JOIN cards cf ON cf.word_id = w.id AND cf.direction = 'forward'
            WHERE w.user_id = %s AND w.language_pair_id = %s
            ORDER BY w.id ASC
            LIMIT %s OFFSET %s
            """
            params = (user_id, pair_id, page_size, offset)
        else:
            query = """
            SELECT
                w.id,
                w.word,
                w.translation,
                COALESCE(cf.srs_index, 0) AS forward_srs_index
            FROM words w
            LEFT JOIN cards cf ON cf.word_id = w.id AND cf.direction = 'forward'
            WHERE w.user_id = %s AND w.language_pair_id = %s AND w.vocabulary_set_id = %s
            ORDER BY w.id ASC
            LIMIT %s OFFSET %s
            """
            params = (user_id, pair_id, set_id, page_size, offset)
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, params)
                rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def delete_word(self, *, user_id: int, pair_id: int, word_id: int) -> bool:
        query = """
        DELETE FROM words
        WHERE id = %s AND user_id = %s AND language_pair_id = %s
        """
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (word_id, user_id, pair_id))
                affected = cursor.rowcount or 0
            await conn.commit()
        return affected > 0

    async def update_translation_and_synonyms(
        self,
        *,
        word_id: int,
        translation: str,
        synonyms: Iterable[str],
    ) -> None:
        query = """
        UPDATE words
        SET translation = %s, synonyms = %s::jsonb
        WHERE id = %s
        """
        payload = json.dumps(list(dict.fromkeys([s.strip() for s in synonyms if s.strip()])))
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (translation, payload, word_id))
            await conn.commit()

    async def update_note(self, *, word_id: int, note: str | None) -> None:
        query = "UPDATE words SET note = %s WHERE id = %s"
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(query, (note, word_id))
            await conn.commit()

    async def replace_examples(
        self,
        *,
        word_id: int,
        examples: Iterable[ExampleContent],
    ) -> None:
        delete_query = "DELETE FROM examples WHERE word_id = %s"
        insert_query = """
        INSERT INTO examples (
            word_id, sentence, translation_ru, translation_de, translation_en, translation_hy, sort_order
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        async with self._pool.connection() as conn:
            try:
                async with conn.cursor() as cursor:
                    await cursor.execute(delete_query, (word_id,))
                    for index, example in enumerate(examples):
                        await cursor.execute(
                            insert_query,
                            (
                                word_id,
                                example.sentence,
                                example.translation_ru,
                                example.translation_de,
                                example.translation_en,
                                example.translation_hy,
                                index,
                            ),
                        )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    async def list_export_rows(self, *, user_id: int, pair_id: int) -> list[dict]:
        query = """
        SELECT
            w.word,
            w.translation,
            w.part_of_speech,
            COALESCE(vs.name, '') AS theme,
            COALESCE(cf.srs_index, 0) AS srs_index,
            COALESCE(cf.correct_count, 0) AS correct_count,
            COALESCE(cf.incorrect_count, 0) AS incorrect_count
        FROM words w
        LEFT JOIN vocabulary_sets vs ON vs.id = w.vocabulary_set_id
        LEFT JOIN cards cf ON cf.word_id = w.id AND cf.direction = 'forward'
        WHERE w.user_id = %s AND w.language_pair_id = %s
        ORDER BY w.id ASC
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, (user_id, pair_id))
                rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def stats_for_pair(self, *, user_id: int, pair_id: int) -> dict[str, float]:
        query = """
        WITH per_word AS (
            SELECT
                w.id,
                COALESCE(MAX(c.srs_index), 0) AS max_srs,
                COALESCE(SUM(c.incorrect_count), 0) AS mistakes
            FROM words w
            LEFT JOIN cards c ON c.word_id = w.id
            WHERE w.user_id = %s AND w.language_pair_id = %s
            GROUP BY w.id
        )
        SELECT
            COUNT(*) AS total_words,
            COUNT(*) FILTER (WHERE max_srs >= 20) AS learned_words,
            COALESCE(AVG(mistakes), 0) AS avg_mistakes
        FROM per_word
        """
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(query, (user_id, pair_id))
                row = await cursor.fetchone()
        if not row:
            return {"total_words": 0, "learned_words": 0, "avg_mistakes": 0.0}
        total_words = int(row["total_words"] or 0)
        learned_words = int(row["learned_words"] or 0)
        return {
            "total_words": total_words,
            "learned_words": learned_words,
            "in_progress_words": max(0, total_words - learned_words),
            "avg_mistakes": float(row["avg_mistakes"] or 0.0),
        }


def _row_to_word_record(row: dict) -> WordRecord:
    synonyms_raw = row.get("synonyms")
    if isinstance(synonyms_raw, list):
        synonyms = tuple(str(item) for item in synonyms_raw if str(item).strip())
    else:
        synonyms = ()

    declension_raw = row.get("declension")
    declension: dict[str, str] | None = None
    if isinstance(declension_raw, dict):
        declension = {str(k): str(v) for k, v in declension_raw.items()}

    return WordRecord(
        id=row["id"],
        user_id=row["user_id"],
        language_pair_id=row["language_pair_id"],
        vocabulary_set_id=row.get("vocabulary_set_id"),
        word=row["word"],
        translation=row["translation"],
        synonyms=synonyms,
        part_of_speech=row.get("part_of_speech"),
        gender=row.get("gender"),
        declension=declension,
        transcription=row.get("transcription"),
        note=row.get("note"),
        tts_word_file_id=row.get("tts_word_file_id"),
    )
