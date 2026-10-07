from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from app.analytics.history import History
from app.config import Settings
from app.db import Database
from app.games import GAMES, Game
from app.ingest.sources import RawDraw

TABLES = "forecast_lines, forecasts, backtest_runs, model_outputs, jackpot_estimates, draws"


def synthetic_draws(game: Game, n: int, seed: int = 0, end: date | None = None) -> list[RawDraw]:
    """`n` fair random draws on the game's most recent scheduled dates up to `end` (default yesterday)."""
    rng = np.random.default_rng(seed)
    day = end or date.today() - timedelta(days=1)
    dates: list[date] = []
    while len(dates) < n:
        if day.weekday() in game.draw_days:
            dates.append(day)
        day -= timedelta(days=1)
    out = []
    for d in reversed(dates):
        primary = tuple(sorted(int(x) + 1 for x in rng.choice(game.pool, game.pick, replace=False)))
        pool = game.bonus_pool_on(d)
        bonus = int(rng.integers(1, pool + 1)) if pool else None
        out.append(RawDraw(game.key, d, primary, bonus, source="synthetic"))
    return out


def history_from(game: Game, draws: list[RawDraw]) -> History:
    rows = [
        {"draw_id": i + 1, "draw_date": d.draw_date, "primary_numbers": list(d.primary_numbers), "bonus_number": d.bonus_number}
        for i, d in enumerate(draws)
    ]
    return History.from_rows(game, rows)


@pytest.fixture(scope="session")
def _database(tmp_path_factory) -> Database:
    """One embedded Postgres for the whole test session."""
    db = Database(pgdata_dir=tmp_path_factory.mktemp("pg"))
    db.migrate()
    yield db
    db.close()


@pytest.fixture
def db(_database: Database) -> Database:
    _database.execute(f"truncate {TABLES} restart identity cascade")
    return _database


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=None,
        seed_dir=tmp_path / "seed",
        forecast_backend="smoothing",
        auto_refresh=False,
        _env_file=None,
    )


@pytest.fixture
def powerball() -> Game:
    return GAMES["powerball"]
