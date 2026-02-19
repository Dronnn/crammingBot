from __future__ import annotations

from psycopg_pool import AsyncConnectionPool


class ReviewsRepository:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def add_review(
        self,
        *,
        card_id: int,
        user_id: int,
        answer: str,
        is_correct: bool,
        response_time_ms: int | None,
    ) -> None:
        query = """
        INSERT INTO reviews (card_id, user_id, answer, is_correct, response_time_ms)
        VALUES (%s, %s, %s, %s, %s)
        """
        async with self._pool.connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    query,
                    (card_id, user_id, answer, is_correct, response_time_ms),
                )
            await conn.commit()

