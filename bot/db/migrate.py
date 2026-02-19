from __future__ import annotations

from pathlib import Path

from psycopg import connect


def apply_migrations(database_url: str) -> None:
    migrations_dir = Path(__file__).resolve().parents[2] / "migrations"
    migration_files = sorted(
        path
        for path in migrations_dir.glob("*.sql")
        if path.is_file() and not path.name.endswith("_down.sql")
    )
    if not migration_files:
        raise FileNotFoundError(f"No migration files found in: {migrations_dir}")

    with connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(255) PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT NOW()
                )
                """
            )
            for migration_file in migration_files:
                version = migration_file.stem
                cursor.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = %s",
                    (version,),
                )
                if cursor.fetchone():
                    continue
                sql = migration_file.read_text(encoding="utf-8")
                cursor.execute(sql)
                cursor.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (version,),
                )
