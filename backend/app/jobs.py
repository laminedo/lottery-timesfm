"""Background work: backtest runs (one at a time, progress in Postgres) and the periodic data refresh."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from psycopg.types.json import Jsonb

from .db import Database
from .forecast.service import ForecastService
from .games import GAMES, Game
from .ingest import pipeline

log = logging.getLogger(__name__)


class BacktestRunner:
    """Queues backtests on a single worker so runs never compete for the model."""

    def __init__(self, db: Database, service: ForecastService):
        self.db = db
        self.service = service
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="backtest")
        # Runs left queued or running by a previous process will never finish.
        db.execute(
            "update backtest_runs set status = 'failed', error = 'Interrupted by a server restart', "
            "finished_at = now() where status in ('queued', 'running')"
        )

    def submit(self, game: Game, params: dict) -> int:
        row = self.db.fetch_one(
            "insert into backtest_runs (game_key, params, message) values (%s, %s, 'Queued') returning run_id",
            (game.key, Jsonb(params)),
        )
        self._pool.submit(self._run, row["run_id"], game, params)
        return row["run_id"]

    def _run(self, run_id: int, game: Game, params: dict) -> None:
        last_write = 0.0

        def progress(fraction: float, message: str) -> None:
            nonlocal last_write
            if time.monotonic() - last_write < 0.5 and fraction < 0.95:
                return
            last_write = time.monotonic()
            self.db.execute(
                "update backtest_runs set progress = %s, message = %s where run_id = %s", (fraction, message, run_id)
            )

        try:
            self.db.execute("update backtest_runs set status = 'running', message = 'Starting' where run_id = %s", (run_id,))
            result = self.service.backtest(game, progress=progress, **params)
            self.db.execute(
                "update backtest_runs set status = 'done', progress = 1, message = 'Done', result = %s, "
                "finished_at = now() where run_id = %s",
                (Jsonb(result), run_id),
            )
        except Exception as e:
            log.exception("Backtest %s failed", run_id)
            self.db.execute(
                "update backtest_runs set status = 'failed', error = %s, finished_at = now() where run_id = %s",
                (str(e), run_id),
            )

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


class Refresher:
    """Pulls new draws on a timer, scores forecasts that were waiting on them, and warms the model cache."""

    def __init__(self, db: Database, service: ForecastService, hours: float):
        self.db = db
        self.service = service
        self.interval = hours * 3600
        self.last_run: float | None = None
        self.last_results: list[dict] = []
        self._stop = threading.Event()
        self._busy = threading.Lock()
        self._thread = threading.Thread(target=self._loop, name="refresher", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def run_once(self, warm: bool = True) -> list[dict]:
        """Refresh every game now. Concurrent calls wait for the running one and reuse its result."""
        if not self._busy.acquire(blocking=False):
            with self._busy:
                return self.last_results
        try:
            self.last_results = pipeline.refresh_all(self.db)
            self.last_run = time.time()
            scored = self.service.evaluate_pending()
            if scored:
                log.info("Scored %d forecast lines against new draws", scored)
            if warm:
                self.warm()
            return self.last_results
        finally:
            self._busy.release()

    def warm(self) -> None:
        """Compute the next-draw model output for each game so the first page load does not wait on it."""
        for game in GAMES.values():
            if self._stop.is_set():
                return
            try:
                gf = self.service.features(game)
                self.service.core(gf, len(gf.history))
            except Exception as e:
                log.warning("Could not warm %s: %r", game.key, e)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                log.exception("Refresh failed")
            self._stop.wait(self.interval)
