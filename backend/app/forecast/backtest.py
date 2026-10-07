"""Walk-forward backtest: score each strategy against draws it had not seen, next to what chance gives.

For every tested draw the strategy sees only earlier draws. Two things are scored:
  - the "top pick": the `pick` numbers the strategy rates most likely, as one line per draw;
  - sampled lines: the average over lines drawn from the strategy's distribution.

A fixed line matched against a fair draw has a hypergeometric number of matches. That gives the exact
chance baseline, and the test of whether a strategy's average is distinguishable from it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import sqrt
from typing import Iterable

import numpy as np
from scipy import stats

from ..games import Game
from .sampler import STRATEGIES, blend, sample_without_replacement, top_k


def match_pmf(pool: int, pick: int) -> np.ndarray:
    """P(a line shares m numbers with a fair draw), m = 0..pick."""
    return stats.hypergeom(pool, pick, pick).pmf(np.arange(pick + 1))


def match_moments(pool: int, pick: int) -> tuple[float, float]:
    """Mean and standard deviation of the number of matches for one line against a fair draw."""
    p = pick / pool
    return pick * p, sqrt(pick * p * (1 - p) * (pool - pick) / (pool - 1))


def count_matches(line: Iterable[int], actual: Iterable[int]) -> int:
    return len(set(int(n) for n in line) & set(int(n) for n in actual))


def chance_test(mean_matches: float, draws: int, pool: int, pick: int) -> dict:
    """Two-sided z-test of an average match count against the hypergeometric mean (normal approximation)."""
    mu, sigma = match_moments(pool, pick)
    if draws == 0 or sigma == 0:
        return {"z": None, "p_value": None}
    z = (mean_matches - mu) / (sigma / sqrt(draws))
    return {"z": float(z), "p_value": float(2 * stats.norm.sf(abs(z)))}


@dataclass(frozen=True)
class Step:
    """One tested draw: the actual result and each component's distribution from earlier draws only."""

    draw_date: date
    actual_main: np.ndarray  # (pick,) ball numbers
    actual_bonus: int | None
    main_components: dict[str, np.ndarray]
    bonus_components: dict[str, np.ndarray] | None


def _is_flat(p: np.ndarray) -> bool:
    return float(p.max() - p.min()) < 1e-12


def run_backtest(game: Game, steps: list[Step], strategies: list[str], samples: int = 20, seed: int = 0) -> dict:
    """Score `strategies` over `steps` (oldest first). Deterministic for a given seed."""
    unknown = [s for s in strategies if s not in STRATEGIES]
    if unknown:
        raise ValueError(f"Unknown strategies {unknown}; expected some of {list(STRATEGIES)}")
    pool, pick, bonus_pool = game.pool, game.pick, game.bonus_pool
    n = len(steps)
    mu, sigma = match_moments(pool, pick)
    rng = np.random.default_rng(seed)

    top = {s: np.zeros(n, dtype=np.int64) for s in strategies}
    sampled = {s: np.zeros(n) for s in strategies}
    log_lift = {s: np.zeros(n) for s in strategies}
    bonus_top = {s: np.zeros(n, dtype=bool) for s in strategies}
    bonus_prob = {s: np.zeros(n) for s in strategies}
    bonus_scored = np.zeros(n, dtype=bool)  # draws whose bonus ball belongs to the current bonus pool
    timeline = []

    for i, step in enumerate(steps):
        actual = np.asarray(step.actual_main, dtype=np.int64)
        row: dict = {"date": step.draw_date.isoformat(), "actual": actual.tolist(), "bonus": step.actual_bonus}
        for s in strategies:
            weights = STRATEGIES[s]["weights"]
            p = blend(step.main_components, weights)
            # A flat distribution has no "most likely" numbers; its pick is a random line.
            pick_idx = sample_without_replacement(rng, p, pick) if _is_flat(p) else top_k(p, pick)
            line = pick_idx + 1
            top[s][i] = count_matches(line, actual)
            draws_idx = [sample_without_replacement(rng, p, pick) for _ in range(samples)]
            sampled[s][i] = np.mean([count_matches(d + 1, actual) for d in draws_idx]) if samples else np.nan
            log_lift[s][i] = float(np.mean(np.log(p[actual - 1] * pool)))
            row[s] = {"line": line.tolist(), "matches": int(top[s][i])}
            if bonus_pool and step.bonus_components is not None and step.actual_bonus:
                bonus_scored[i] = True
                bp = blend(step.bonus_components, weights)
                guess = int(rng.integers(bonus_pool)) if _is_flat(bp) else int(np.argmax(bp))
                bonus_top[s][i] = guess + 1 == step.actual_bonus
                bonus_prob[s][i] = bp[step.actual_bonus - 1]
                row[s]["bonus"] = guess + 1
                row[s]["bonus_match"] = bool(bonus_top[s][i])
        timeline.append(row)

    results = []
    for s in strategies:
        mean = float(top[s].mean()) if n else 0.0
        sd = float(top[s].std(ddof=1)) if n > 1 else 0.0
        half = 1.96 * sd / sqrt(n) if n else 0.0
        test = chance_test(mean, n, pool, pick)
        entry = {
            "key": s,
            "label": STRATEGIES[s]["label"],
            "top_pick": {
                "mean_matches": mean,
                "total_matches": int(top[s].sum()),
                "ci95": [mean - half, mean + half],
                "histogram": np.bincount(top[s], minlength=pick + 1)[: pick + 1].tolist(),
                "best": int(top[s].max()) if n else 0,
                **test,
                "consistent_with_chance": test["p_value"] is None or test["p_value"] >= 0.05,
            },
            "sampled": {"mean_matches": float(np.nanmean(sampled[s])) if n and samples else None, "lines_per_draw": samples},
            # Average log of p(drawn number) / uniform. Zero means no better than chance; negative, worse.
            "mean_log_lift": float(log_lift[s].mean()) if n else 0.0,
            "bonus": None,
        }
        if bonus_pool:
            m = int(bonus_scored.sum())
            entry["bonus"] = {
                "scored_draws": m,
                "top_hits": int(bonus_top[s].sum()),
                "top_hit_rate": float(bonus_top[s][bonus_scored].mean()) if m else None,
                "mean_probability_on_drawn": float(bonus_prob[s][bonus_scored].mean()) if m else None,
            }
        results.append(entry)

    return {
        "game": game.key,
        "draws": n,
        "from": steps[0].draw_date.isoformat() if n else None,
        "to": steps[-1].draw_date.isoformat() if n else None,
        "seed": seed,
        "baseline": {
            "expected_matches": mu,
            "sd_matches": sigma,
            "match_pmf": match_pmf(pool, pick).tolist(),
            "bonus_hit_rate": 1 / bonus_pool if bonus_pool else None,
        },
        "strategies": results,
        "timeline": timeline,
    }
