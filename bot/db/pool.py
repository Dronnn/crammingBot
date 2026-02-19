from __future__ import annotations

from psycopg_pool import AsyncConnectionPool


class DatabasePool:
    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 8) -> None:
        self._pool = AsyncConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            open=False,
            kwargs={"autocommit": False},
        )

    @property
    def pool(self) -> AsyncConnectionPool:
        return self._pool

    async def open(self) -> None:
        await self._pool.open(wait=True)

    async def close(self) -> None:
        await self._pool.close()

