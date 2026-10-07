"""Write a read-only snapshot of the API as JSON files, for the static demo (GitHub Pages).

The files mirror the API's responses, so the web app reads them in place of the live routes:

    health.json
    backtests/{run_id}.json           one full backtest result
    {game}/game.json                  GET /api/games/{game}
    {game}/draws.json                 every draw, newest first
    {game}/metrics.json, trends.json  GET .../metrics, .../trends
    {game}/forecast.json              GET .../forecast
    {game}/backtests.json             GET .../backtests (summaries of the precomputed runs)
    {game}/accuracy.json              GET .../accuracy

Nothing here is computed differently from the live API; a backtest is simply run ahead of time for
each of a few sizes, because the hosted demo has no model to run it with.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .analytics.history import load_history
from .analytics.metrics import game_metrics
from .analytics.trends import game_trends
from .db import Database
from .forecast.backtest import match_moments, match_pmf
from .forecast.sampler import STRATEGIES
from .forecast.service import ForecastService, backtest_digest
from .games import GAMES
from .views import draw_row, game_summary, run_row

BACKTEST_DRAWS = (25, 50, 100, 200)  # the sizes the web app offers
FEATURED_BACKTEST = 100  # the one shown first and used for the accuracy tracker
TREND_WINDOW = 500  # the longest window the web app offers; shorter ones are cut from it in the browser


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":"), default=str))


def export_static(
    db: Database,
    service: ForecastService,
    out_dir: Path,
    backtest_draws: tuple[int, ...] = BACKTEST_DRAWS,
    featured: int = FEATURED_BACKTEST,
    log: Callable[[str], None] = print,
) -> dict:
    """Export every game to `out_dir`, replacing what is there. Returns a summary of what was written."""
    if featured not in backtest_draws:
        raise ValueError(f"featured backtest size {featured} must be one of {backtest_draws}")
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    params_base = {"strategies": list(STRATEGIES), "samples": 20, "seed": 0}
    latest: dict[str, str | None] = {}
    files = 0

    for g, game in enumerate(GAMES.values()):
        history = load_history(db, game)
        summary = game_summary(db, game)
        latest[game.key] = summary["latest_draw"]["draw_date"] if summary["latest_draw"] else None
        rows = db.fetch_all(
            "select * from draws where game_key = %s and draw_date >= %s order by draw_date desc",
            (game.key, game.main_since),
        )
        gdir = out_dir / game.key
        _write(gdir / "game.json", summary)
        _write(gdir / "draws.json", {"game": game.key, "total": len(rows), "draws": [draw_row(r) for r in rows]})
        _write(gdir / "metrics.json", game_metrics(history))
        _write(gdir / "trends.json", game_trends(history, window=TREND_WINDOW))
        _write(gdir / "forecast.json", service.distribution(game))
        files += 5

        runs, featured_run = [], None
        for i, n in enumerate(backtest_draws):
            log(f"{game.key}: backtest over {n} draws")
            result = service.backtest(game, draws=n, **params_base)
            row = {
                "run_id": g * 100 + i + 1,
                "game_key": game.key,
                "status": "done",
                "progress": 1.0,
                "message": "Done",
                "error": None,
                "params": {"draws": n, **params_base},
                "created_at": datetime.fromisoformat(now),
                "finished_at": datetime.fromisoformat(now),
                "result": result,
            }
            _write(out_dir / "backtests" / f"{row['run_id']}.json", run_row(row, with_result=True))
            runs.append(row)
            if n == featured:
                featured_run = row
            files += 1
        # The featured run goes first: the web app opens the first finished run in the list.
        runs.sort(key=lambda r: (r is not featured_run, r["params"]["draws"]))
        _write(gdir / "backtests.json", [run_row(r, with_result=False) for r in runs])
        _write(
            gdir / "accuracy.json",
            {
                "game": game.key,
                "expected_matches": match_moments(game.pool, game.pick)[0],
                "match_pmf": match_pmf(game.pool, game.pick).tolist(),
                "live": {"scored_lines": 0, "pending_lines": 0, "mean_matches": None, "by_strategy": []},
                "backtest": backtest_digest(featured_run["run_id"], now, featured_run["result"]),
            },
        )
        files += 2

    health = {
        "status": "ok",
        "static": True,
        "exported_at": now,
        "backend": service.backend.describe(),
        "draws": {r["game_key"]: r["n"] for r in db.fetch_all("select game_key, count(*) as n from draws group by 1")},
        "latest_draws": latest,
        "last_refresh": None,
    }
    _write(out_dir / "health.json", health)
    return {"out_dir": str(out_dir), "files": files + 1, "exported_at": now, "latest_draws": latest}
