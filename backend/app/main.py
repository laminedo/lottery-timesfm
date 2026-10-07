"""FastAPI application: draw data, historical metrics, forecasts and backtests."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .analytics.history import load_history
from .analytics.metrics import game_metrics
from .analytics.trends import game_trends
from .config import Settings, get_settings
from .db import Database
from .forecast.backends import make_backend
from .forecast.sampler import COMPONENTS, MAX_TEMPERATURE, MIN_TEMPERATURE, STRATEGIES
from .forecast.service import DISCLAIMER, ForecastService, NotEnoughHistory
from .games import GAMES, Game
from .ingest import pipeline
from .jobs import BacktestRunner, Refresher
from .views import draw_row, game_summary, run_row

log = logging.getLogger(__name__)

HELP = {
    "name": "National Council on Problem Gambling",
    "phone": "1-800-GAMBLER",
    "url": "https://www.ncpgambling.org/help-treatment/",
}
REFRESH_COOLDOWN = 60  # seconds between manual refreshes of the official feeds


class State:
    """Everything a request handler needs, built once at startup."""

    def __init__(self, settings: Settings, db: Database | None = None, backend=None):
        self.settings = settings
        self.db = db or Database.from_settings(settings)
        self.db.migrate()
        pipeline.seed_if_empty(self.db, settings.seed_dir)
        self.backend = backend or make_backend(settings)
        self.service = ForecastService(self.db, self.backend, settings)
        self.backtests = BacktestRunner(self.db, self.service)
        self.refresher = Refresher(self.db, self.service, settings.refresh_hours)

    def close(self) -> None:
        self.refresher.stop()
        self.backtests.shutdown()
        self.db.close()


router = APIRouter(prefix="/api")


def ctx(request: Request) -> State:
    return request.app.state.ctx


def game_or_404(key: str) -> Game:
    if key not in GAMES:
        raise HTTPException(404, f"Unknown game '{key}'. Known games: {', '.join(GAMES)}")
    return GAMES[key]


@router.get("/health")
def health(s: State = Depends(ctx)) -> dict:
    counts = s.db.fetch_all("select game_key, count(*) as n from draws group by 1 order by 1")
    return {
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "database": "embedded" if s.db.embedded else "external",
        "backend": s.backend.describe(),
        "draws": {r["game_key"]: r["n"] for r in counts},
        "last_refresh": s.refresher.last_run and datetime.fromtimestamp(s.refresher.last_run, timezone.utc).isoformat(timespec="seconds"),
        "disclaimer": DISCLAIMER,
        "help": HELP,
    }


@router.get("/games")
def list_games(s: State = Depends(ctx)) -> list[dict]:
    return [game_summary(s.db, g) for g in GAMES.values()]


@router.get("/games/{key}")
def get_game_summary(key: str, s: State = Depends(ctx)) -> dict:
    return game_summary(s.db, game_or_404(key))


@router.get("/games/{key}/draws")
def list_draws(
    key: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    s: State = Depends(ctx),
) -> dict:
    game = game_or_404(key)
    total = s.db.fetch_one(
        "select count(*) as n from draws where game_key = %s and draw_date >= %s", (game.key, game.main_since)
    )["n"]
    rows = s.db.fetch_all(
        "select * from draws where game_key = %s and draw_date >= %s order by draw_date desc limit %s offset %s",
        (game.key, game.main_since, limit, offset),
    )
    return {"game": game.key, "total": total, "limit": limit, "offset": offset, "draws": [draw_row(r) for r in rows]}


@router.get("/games/{key}/metrics")
def metrics(key: str, s: State = Depends(ctx)) -> dict:
    return game_metrics(load_history(s.db, game_or_404(key)))


@router.get("/games/{key}/trends")
def trends(key: str, window: int = Query(200, ge=10, le=2000), s: State = Depends(ctx)) -> dict:
    return game_trends(load_history(s.db, game_or_404(key)), window=window)


@router.get("/games/{key}/forecast")
def forecast_distribution(key: str, s: State = Depends(ctx)) -> dict:
    try:
        return s.service.distribution(game_or_404(key))
    except NotEnoughHistory as e:
        raise HTTPException(409, str(e)) from e


class GenerateRequest(BaseModel):
    lines: int = Field(3, ge=1, le=10, description="How many candidate lines to generate")
    strategy: Literal["balanced", "hot", "cold", "entropy"] = "balanced"
    weights: dict[str, float] | None = Field(
        None, description=f"Custom component weights over {list(COMPONENTS)}; overrides `strategy`"
    )
    temperature: float = Field(1.0, ge=MIN_TEMPERATURE, le=MAX_TEMPERATURE)
    seed: int | None = Field(None, ge=0, description="Fix the random seed to reproduce a result")


@router.post("/games/{key}/forecast/generate")
def generate(key: str, body: GenerateRequest, s: State = Depends(ctx)) -> dict:
    game = game_or_404(key)
    try:
        return s.service.generate(game, body.lines, body.strategy, body.weights, body.temperature, body.seed)
    except NotEnoughHistory as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/games/{key}/forecasts")
def forecasts(key: str, limit: int = Query(20, ge=1, le=100), s: State = Depends(ctx)) -> list[dict]:
    return s.service.recent_forecasts(game_or_404(key), limit)


@router.get("/games/{key}/accuracy")
def accuracy(key: str, s: State = Depends(ctx)) -> dict:
    return s.service.accuracy(game_or_404(key))


class BacktestRequest(BaseModel):
    draws: int = Field(100, ge=10, le=500, description="How many of the most recent draws to test")
    strategies: list[Literal["balanced", "hot", "cold", "entropy"]] = Field(default_factory=lambda: list(STRATEGIES))
    samples: int = Field(20, ge=0, le=200, description="Sampled lines per draw and strategy")
    seed: int = Field(0, ge=0)


@router.post("/games/{key}/backtests", status_code=202)
def start_backtest(key: str, body: BacktestRequest, s: State = Depends(ctx)) -> dict:
    game = game_or_404(key)
    if not body.strategies:
        raise HTTPException(422, "Choose at least one strategy")
    run_id = s.backtests.submit(game, body.model_dump())
    return run_row(s.db.fetch_one("select * from backtest_runs where run_id = %s", (run_id,)), with_result=False)


@router.get("/games/{key}/backtests")
def list_backtests(key: str, limit: int = Query(10, ge=1, le=50), s: State = Depends(ctx)) -> list[dict]:
    game = game_or_404(key)
    rows = s.db.fetch_all(
        "select * from backtest_runs where game_key = %s order by created_at desc limit %s", (game.key, limit)
    )
    return [run_row(r, with_result=False) for r in rows]


@router.get("/backtests/{run_id}")
def get_backtest(run_id: int, s: State = Depends(ctx)) -> dict:
    row = s.db.fetch_one("select * from backtest_runs where run_id = %s", (run_id,))
    if not row:
        raise HTTPException(404, f"No backtest run {run_id}")
    return run_row(row, with_result=True)


@router.post("/refresh")
def refresh(s: State = Depends(ctx)) -> dict:
    """Fetch new draws from the official sources now."""
    last = s.refresher.last_run
    if last and time.time() - last < REFRESH_COOLDOWN:
        raise HTTPException(429, f"Refreshed {int(time.time() - last)}s ago; wait {REFRESH_COOLDOWN}s between refreshes")
    return {"results": s.refresher.run_once(warm=False)}


def create_app(settings: Settings | None = None, state: State | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.ctx = state or State(settings)
        if settings.auto_refresh and state is None:
            app.state.ctx.refresher.start()
        yield
        if state is None:
            app.state.ctx.close()

    app = FastAPI(title="Lottery Forecast API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
