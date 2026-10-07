"""Postgres access: connection pool, embedded dev server, and SQL migrations."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import BACKEND_DIR, Settings
from .games import GAMES

log = logging.getLogger(__name__)

MIGRATIONS_DIR = BACKEND_DIR / "migrations"


class Database:
    """Owns the pool (and the embedded server, when no DATABASE_URL is given)."""

    def __init__(self, url: str | None = None, pgdata_dir: Path | None = None):
        self._embedded = None
        if url is None:
            url = self._start_embedded(pgdata_dir or BACKEND_DIR / "data" / "pgdata")
        self.url = url
        self.embedded = self._embedded is not None
        self.pool = ConnectionPool(url, min_size=1, max_size=8, kwargs={"row_factory": dict_row}, open=True)
        self.pool.wait(timeout=30)

    @classmethod
    def from_settings(cls, settings: Settings) -> "Database":
        return cls(settings.database_url, settings.pgdata_dir)

    def _start_embedded(self, pgdata_dir: Path) -> str:
        try:
            import pixeltable_pgserver as pgserver
        except ImportError as e:
            raise RuntimeError(
                "DATABASE_URL is not set and the embedded Postgres is not installed. "
                "Set DATABASE_URL, or install it with: uv sync --extra embedded-pg"
            ) from e
        pgdata_dir.mkdir(parents=True, exist_ok=True)
        self._embedded = pgserver.get_server(pgdata_dir)
        log.info("Embedded Postgres running from %s", pgdata_dir)
        return self._embedded.get_uri()

    def close(self) -> None:
        self.pool.close()
        if self._embedded is not None:
            self._embedded.cleanup()
            self._embedded = None

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        """A pooled connection; commits on success, rolls back on error."""
        with self.pool.connection() as conn:
            yield conn

    def fetch_all(self, sql: str, params: Any = None) -> list[dict]:
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def fetch_one(self, sql: str, params: Any = None) -> dict | None:
        with self.connect() as conn:
            return conn.execute(sql, params).fetchone()

    def execute(self, sql: str, params: Any = None) -> None:
        with self.connect() as conn:
            conn.execute(sql, params)

    def migrate(self) -> list[str]:
        """Apply migrations/*.sql that have not run yet, in filename order. Returns the versions applied."""
        applied: list[str] = []
        with self.connect() as conn:
            conn.execute(
                "create table if not exists schema_migrations "
                "(version text primary key, applied_at timestamptz not null default now())"
            )
            conn.execute("alter table schema_migrations enable row level security")
            done = {r["version"] for r in conn.execute("select version from schema_migrations")}
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                if path.stem in done:
                    continue
                conn.execute(path.read_text())
                conn.execute("insert into schema_migrations (version) values (%s)", (path.stem,))
                applied.append(path.stem)
                log.info("Applied migration %s", path.stem)
        self.sync_games()
        return applied

    def sync_games(self) -> None:
        """Keep the games table in step with the definitions in code."""
        with self.connect() as conn:
            for g in GAMES.values():
                conn.execute(
                    """
                    insert into games (game_key, name, pick_count, pool_size, bonus_pool_size, bonus_name)
                    values (%s, %s, %s, %s, %s, %s)
                    on conflict (game_key) do update set
                        name = excluded.name, pick_count = excluded.pick_count, pool_size = excluded.pool_size,
                        bonus_pool_size = excluded.bonus_pool_size, bonus_name = excluded.bonus_name,
                        updated_at = now()
                    """,
                    (g.key, g.name, g.pick, g.pool, g.bonus_pool, g.bonus_name),
                )
