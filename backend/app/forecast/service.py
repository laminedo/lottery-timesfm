"""Forecast operations on top of the database: cached model output, distributions, line generation,
scoring of past forecasts, and backtest inputs."""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
from typing import Callable

import numpy as np
from psycopg.types.json import Jsonb

from ..analytics.history import load_history
from ..analytics.trends import sum_moments
from ..config import Settings
from ..db import Database
from ..games import Game, next_draw_at
from .backends import ForecastBackend
from .backtest import Step, match_moments, match_pmf, run_backtest
from .distribution import (
    CHANNEL_WEIGHTS,
    MIN_DRAWS,
    PIPELINE_VERSION,
    REPRESENTATION_WEIGHTS,
    GameFeatures,
    PoolFeatures,
    classical_weights,
    core_forecasts,
    game_features,
    order_statistic_pmf,
    to_jsonable,
)
from .sampler import STRATEGIES, blend, generate_lines, normalize_weights

STEPS_PER_CALL = 4  # backtest targets forecast per model call, so batches run full

DISCLAIMER = (
    "This tool provides statistical pattern analysis and experimental time-series modeling for analytical "
    "and entertainment purposes only. Lottery drawings are strictly independent random events; no machine "
    "learning model can guarantee future winning numbers."
)


class NotEnoughHistory(ValueError):
    pass


class ForecastService:
    def __init__(self, db: Database, backend: ForecastBackend, settings: Settings):
        self.db = db
        self.backend = backend
        self.context = settings.timesfm_context
        self._settings = settings
        self._features: dict[str, tuple[tuple[int, int], GameFeatures]] = {}
        self._lock = threading.Lock()

    # ---- inputs ----

    def pipeline_key(self) -> str:
        """Identifies everything that shapes a cached model output besides the draws themselves."""
        s = self._settings
        parts = {
            "v": PIPELINE_VERSION,
            "backend": self.backend.name,
            "model": s.timesfm_model if self.backend.name == "timesfm" else None,
            "context": self.context,
            "flip": s.timesfm_flip_invariance,
            "channels": CHANNEL_WEIGHTS,
            "repr": REPRESENTATION_WEIGHTS,
        }
        digest = hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:12]
        return f"{self.backend.name}:{digest}"

    def features(self, game: Game) -> GameFeatures:
        """Feature matrices for the game's stored draws, rebuilt only when the draws change."""
        stamp = self.db.fetch_one(
            "select count(*) as n, coalesce(max(draw_id), 0) as last from draws where game_key = %s and draw_date >= %s",
            (game.key, game.main_since),
        )
        key = (stamp["n"], stamp["last"])
        with self._lock:
            cached = self._features.get(game.key)
            if cached and cached[0] == key:
                return cached[1]
        gf = game_features(load_history(self.db, game))
        with self._lock:
            self._features[game.key] = (key, gf)
        return gf

    def cores(
        self,
        gf: GameFeatures,
        indices: list[int],
        progress: Callable[[int, int], None] | None = None,
    ) -> tuple[dict[int, dict], int]:
        """Model output (JSON form) for the draw after each row in `indices`.

        Cached outputs are read from Postgres; the rest are computed a few targets per model call and
        stored. Returns ({row: output}, how many were already cached). `progress(done, missing)` is
        called as the missing ones complete.
        """
        game, prefix = gf.history.game, self.pipeline_key()
        for upto in indices:
            if upto < MIN_DRAWS:
                raise NotEnoughHistory(f"{game.name} needs at least {MIN_DRAWS} draws, has {upto}")
        key_of = {i: f"{prefix}:n{i}" for i in indices}
        rows = self.db.fetch_all(
            "select pipeline_key, payload from model_outputs where game_key = %s and pipeline_key = any(%s)",
            (game.key, list(key_of.values())),
        )
        by_key = {r["pipeline_key"]: r["payload"] for r in rows}
        out = {i: by_key[k] for i, k in key_of.items() if k in by_key}
        missing = [i for i in indices if i not in out]
        cached = len(out)
        for start in range(0, len(missing), STEPS_PER_CALL):
            chunk = missing[start : start + STEPS_PER_CALL]
            payloads = [to_jsonable(p) for p in core_forecasts(self.backend, gf, chunk, self.context)]
            with self.db.connect() as conn:
                for i, payload in zip(chunk, payloads):
                    conn.execute(
                        "insert into model_outputs (game_key, as_of_draw_id, pipeline_key, payload) "
                        "values (%s, %s, %s, %s) on conflict (game_key, as_of_draw_id, pipeline_key) do nothing",
                        (game.key, int(gf.history.draw_ids[i - 1]), key_of[i], Jsonb(payload)),
                    )
                    out[i] = payload
            if progress:
                progress(min(start + STEPS_PER_CALL, len(missing)), len(missing))
        return out, cached

    def core(self, gf: GameFeatures, upto: int) -> dict:
        """Model output for the draw after row `upto`, from the cache or computed and stored."""
        return self.cores(gf, [upto])[0][upto]

    @staticmethod
    def _components(f: PoolFeatures, upto: int, pool_payload: dict) -> dict[str, np.ndarray]:
        classical = classical_weights(f, upto)
        return {
            "timesfm": np.asarray(pool_payload["core"], dtype=np.float64),
            "hot": classical["hot"],
            "cold": classical["cold"],
            "uniform": np.full(f.pool, f.pick / f.pool),
        }

    def components(self, gf: GameFeatures, upto: int, payload: dict) -> tuple[dict, dict | None]:
        main = self._components(gf.main, upto, payload["main"])
        bonus = None
        if gf.bonus is not None:
            bonus = self._components(gf.bonus, gf.bonus_upto(upto), payload["bonus"])
        return main, bonus

    # ---- next-draw forecast ----

    def _target(self, game: Game, gf: GameFeatures) -> dict:
        h = gf.history
        last = len(h) - 1
        return {
            "target_draw_at": next_draw_at(game).isoformat(),
            "as_of": {
                "draw_id": int(h.draw_ids[last]),
                "draw_date": h.dates[last].isoformat(),
                "primary_numbers": h.main[last].tolist(),
                "bonus_number": int(h.bonus[last]) or None,
            },
        }

    def distribution(self, game: Game) -> dict:
        """Everything the forecast screen shows: per-number probabilities from each model, with bands."""
        gf = self.features(game)
        upto = len(gf.history)
        payload = self.core(gf, upto)
        main_c, bonus_c = self.components(gf, upto, payload)

        def pool_view(f: PoolFeatures, comps: dict, p: dict) -> dict:
            base = f.pick / f.pool
            numbers = []
            for n in range(f.pool):
                numbers.append(
                    {
                        "number": n + 1,
                        "timesfm": float(comps["timesfm"][n]),
                        "hot": float(comps["hot"][n]),
                        "cold": float(comps["cold"][n]),
                        "representation_a": p["representation_a"][n],
                        "representation_b": p["representation_b"][n],
                        "rate": p["rate"][n],
                        "rate_low": p["rate_low"][n],
                        "rate_high": p["rate_high"][n],
                    }
                )
            return {
                "pool": f.pool,
                "pick": f.pick,
                "baseline": base,
                "informative": p["informative"],
                "context_draws": p["context_draws"],
                "numbers": numbers,
                "channels": p["channels"],
            }

        main = pool_view(gf.main, main_c, payload["main"])
        exp_sum, sd_sum = sum_moments(game.pool, game.pick)
        ks = np.arange(1, game.pool + 1)
        main["positions"] = [
            {**pos, "expected": float(order_statistic_pmf(game.pool, game.pick, pos["position"]) @ ks)}
            for pos in payload["main"]["positions"]
        ]
        main["sum"] = payload["main"]["sum"] and {**payload["main"]["sum"], "expected_mean": exp_sum, "expected_sd": sd_sum}
        main["moving_sum"] = payload["main"]["moving_sum"]
        bonus = pool_view(gf.bonus, bonus_c, payload["bonus"]) if gf.bonus is not None else None
        return {
            "game": game.key,
            "backend": self.backend.describe(),
            **self._target(game, gf),
            "main": main,
            "bonus": bonus,
            "strategies": STRATEGIES,
            "weights": {"channels": CHANNEL_WEIGHTS, "representations": REPRESENTATION_WEIGHTS},
            "disclaimer": DISCLAIMER,
        }

    def generate(
        self,
        game: Game,
        count: int = 3,
        strategy: str = "balanced",
        weights: dict[str, float] | None = None,
        temperature: float = 1.0,
        seed: int | None = None,
    ) -> dict:
        """Sample `count` candidate lines for the next draw and store them for later scoring."""
        if weights is None:
            if strategy not in STRATEGIES:
                raise ValueError(f"Unknown strategy '{strategy}'; expected one of {list(STRATEGIES)}")
            used = dict(STRATEGIES[strategy]["weights"])
        else:
            used, strategy = normalize_weights(weights), "custom"
        gf = self.features(game)
        upto = len(gf.history)
        payload = self.core(gf, upto)
        main_c, bonus_c = self.components(gf, upto, payload)
        main_p = blend(main_c, used, temperature)
        bonus_p = blend(bonus_c, used, temperature) if bonus_c is not None else None
        seed = secrets.randbits(31) if seed is None else int(seed)
        lines = generate_lines(np.random.default_rng(seed), game, main_p, bonus_p, count)

        target = self._target(game, gf)
        sum_band = payload["main"]["sum"]
        params = {"weights": used, "temperature": temperature, "seed": seed, "count": count}
        with self.db.connect() as conn:
            fid = conn.execute(
                "insert into forecasts (game_key, target_draw_date, as_of_draw_id, strategy, backend, params) "
                "values (%s, %s, %s, %s, %s, %s) returning forecast_id, created_at",
                (game.key, target["target_draw_at"][:10], target["as_of"]["draw_id"], strategy, self.backend.name, Jsonb(params)),
            ).fetchone()
            for i, line in enumerate(lines, start=1):
                conn.execute(
                    "insert into forecast_lines (forecast_id, line_no, primary_numbers, bonus_number) values (%s, %s, %s, %s)",
                    (fid["forecast_id"], i, line.primary, line.bonus),
                )
        out_lines = []
        for line in lines:
            total = sum(line.primary)
            in_band = None
            if sum_band:
                in_band = bool(sum_band["quantiles"][0] <= total <= sum_band["quantiles"][-1])
            out_lines.append(
                {
                    "primary_numbers": line.primary,
                    "bonus_number": line.bonus,
                    "lift": line.lift,
                    "sum": total,
                    "odd": sum(n % 2 for n in line.primary),
                    "sum_in_forecast_band": in_band,
                }
            )
        return {
            "forecast_id": fid["forecast_id"],
            "created_at": fid["created_at"].isoformat(),
            "game": game.key,
            "strategy": strategy,
            "backend": self.backend.describe(),
            **params,
            **target,
            "lines": out_lines,
            "jackpot_odds": game.jackpot_odds,
            "disclaimer": DISCLAIMER,
        }

    # ---- scoring past forecasts ----

    def evaluate_pending(self) -> int:
        """Score every stored line whose target draw has since been ingested. Returns lines scored."""
        with self.db.connect() as conn:
            cur = conn.execute(
                """
                update forecast_lines l set
                    draw_id = d.draw_id,
                    main_matches = (select count(*) from unnest(l.primary_numbers) x where x = any(d.primary_numbers)),
                    bonus_match = case when l.bonus_number is null then null else l.bonus_number = d.bonus_number end,
                    evaluated_at = now()
                from forecasts f
                join draws d on d.game_key = f.game_key and d.draw_date = f.target_draw_date
                where l.forecast_id = f.forecast_id and l.draw_id is null
                """
            )
            return cur.rowcount

    def accuracy(self, game: Game) -> dict:
        """How stored forecast lines have done against real draws, next to the chance expectation."""
        rows = self.db.fetch_all(
            """
            select f.strategy,
                   count(*) filter (where l.draw_id is not null) as scored,
                   count(*) filter (where l.draw_id is null) as pending,
                   avg(l.main_matches) filter (where l.draw_id is not null) as mean_matches,
                   max(l.main_matches) as best,
                   count(*) filter (where l.bonus_match) as bonus_hits
            from forecast_lines l join forecasts f using (forecast_id)
            where f.game_key = %s group by f.strategy order by f.strategy
            """,
            (game.key,),
        )
        scored = sum(r["scored"] for r in rows)
        total_matches = sum(float(r["mean_matches"] or 0) * r["scored"] for r in rows)
        mu, _ = match_moments(game.pool, game.pick)
        latest = self.db.fetch_one(
            "select run_id, finished_at, params, result from backtest_runs "
            "where game_key = %s and status = 'done' order by finished_at desc limit 1",
            (game.key,),
        )
        backtest = None
        if latest:
            r = latest["result"]
            backtest = {
                "run_id": latest["run_id"],
                "finished_at": latest["finished_at"].isoformat(),
                "draws": r["draws"],
                "from": r["from"],
                "to": r["to"],
                "strategies": [
                    {"key": s["key"], "label": s["label"], "mean_matches": s["top_pick"]["mean_matches"],
                     "p_value": s["top_pick"]["p_value"], "consistent_with_chance": s["top_pick"]["consistent_with_chance"]}
                    for s in r["strategies"]
                ],
            }
        return {
            "game": game.key,
            "expected_matches": mu,
            "match_pmf": match_pmf(game.pool, game.pick).tolist(),
            "live": {
                "scored_lines": scored,
                "pending_lines": sum(r["pending"] for r in rows),
                "mean_matches": total_matches / scored if scored else None,
                "by_strategy": [
                    {"strategy": r["strategy"], "scored": r["scored"], "pending": r["pending"],
                     "mean_matches": float(r["mean_matches"]) if r["mean_matches"] is not None else None,
                     "best": r["best"], "bonus_hits": r["bonus_hits"]}
                    for r in rows
                ],
            },
            "backtest": backtest,
        }

    def recent_forecasts(self, game: Game, limit: int = 20) -> list[dict]:
        rows = self.db.fetch_all(
            """
            select f.forecast_id, f.created_at, f.target_draw_date, f.strategy, f.backend, f.params,
                   json_agg(json_build_object(
                       'primary_numbers', l.primary_numbers, 'bonus_number', l.bonus_number,
                       'main_matches', l.main_matches, 'bonus_match', l.bonus_match, 'scored', l.draw_id is not null
                   ) order by l.line_no) as lines,
                   (select json_build_object('primary_numbers', d.primary_numbers, 'bonus_number', d.bonus_number)
                      from draws d where d.game_key = f.game_key and d.draw_date = f.target_draw_date) as draw
            from forecasts f join forecast_lines l using (forecast_id)
            where f.game_key = %s group by f.forecast_id order by f.created_at desc limit %s
            """,
            (game.key, limit),
        )
        for r in rows:
            r["created_at"] = r["created_at"].isoformat()
            r["target_draw_date"] = r["target_draw_date"].isoformat()
        return rows

    # ---- backtest ----

    def backtest(
        self,
        game: Game,
        draws: int = 100,
        strategies: list[str] | None = None,
        samples: int = 20,
        seed: int = 0,
        progress: Callable[[float, str], None] | None = None,
    ) -> dict:
        """Walk forward over the last `draws` draws. Model outputs are cached, so reruns are fast."""
        strategies = strategies or list(STRATEGIES)
        gf = self.features(game)
        total = len(gf.history)
        first = max(MIN_DRAWS, total - draws)
        indices = list(range(first, total))
        if not indices:
            raise NotEnoughHistory(f"{game.name} has {total} draws; a backtest needs more than {MIN_DRAWS}")
        label = self.backend.describe().get("label", self.backend.name)

        def report(done: int, missing: int) -> None:
            if progress:
                progress(0.95 * done / missing, f"{label}: forecast {done} of {missing} draws")

        payloads, cached = self.cores(gf, indices, report)
        bonus_start = gf.history.bonus_start
        steps: list[Step] = []
        for i in indices:
            main_c, bonus_c = self.components(gf, i, payloads[i])
            # A draw from before the current bonus matrix cannot be scored against today's bonus pool.
            has_bonus = gf.bonus is not None and i >= bonus_start
            steps.append(
                Step(
                    draw_date=gf.history.dates[i],
                    actual_main=gf.history.main[i],
                    actual_bonus=int(gf.history.bonus[i]) if has_bonus else None,
                    main_components=main_c,
                    bonus_components=bonus_c if has_bonus else None,
                )
            )
        if progress:
            progress(0.97, "Scoring strategies")
        result = run_backtest(game, steps, strategies, samples=samples, seed=seed)
        result["backend"] = self.backend.describe()
        result["cached_steps"] = cached
        return result
