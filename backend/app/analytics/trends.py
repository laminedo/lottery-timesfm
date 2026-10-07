"""Draw-shape trends: odd/even, high/low, consecutive numbers and sums, each next to what chance predicts."""
from __future__ import annotations

from math import comb, sqrt

import numpy as np
import pandas as pd
from scipy import stats

from .history import History

ROLLING = 30  # window for the smoothed lines on the trend charts


def odd_count_pmf(pool: int, pick: int) -> np.ndarray:
    """P(a draw has k odd numbers), k = 0..pick."""
    return stats.hypergeom(pool, (pool + 1) // 2, pick).pmf(np.arange(pick + 1))


def high_count_pmf(pool: int, pick: int) -> np.ndarray:
    """P(a draw has k numbers in the upper half), k = 0..pick. The upper half starts at pool // 2 + 1."""
    return stats.hypergeom(pool, pool - pool // 2, pick).pmf(np.arange(pick + 1))


def consecutive_pairs_pmf(pool: int, pick: int) -> np.ndarray:
    """P(a draw has exactly j adjacent pairs such as 17-18), j = 0..pick-1.

    A pick-subset with j adjacent pairs is pick - j runs: C(pick-1, j) ways to cut the numbers into
    runs, times C(pool-pick+1, pick-j) ways to place the runs.
    """
    total = comb(pool, pick)
    return np.array([comb(pick - 1, j) * comb(pool - pick + 1, pick - j) / total for j in range(pick)])


def sum_moments(pool: int, pick: int) -> tuple[float, float]:
    """Mean and standard deviation of the sum of `pick` numbers drawn without replacement from 1..pool."""
    return pick * (pool + 1) / 2, sqrt(pick * (pool + 1) * (pool - pick) / 12)


def draw_shapes(main: np.ndarray, pool: int) -> dict[str, np.ndarray]:
    """Per-draw odd count, high count, adjacent-pair count, sum and spread."""
    main = np.sort(np.asarray(main, dtype=np.int64).reshape(len(main), -1), axis=1)
    return {
        "odd": (main % 2 == 1).sum(axis=1),
        "high": (main > pool // 2).sum(axis=1),
        "consecutive": (np.diff(main, axis=1) == 1).sum(axis=1),
        "sum": main.sum(axis=1),
        "spread": main[:, -1] - main[:, 0] if main.size else np.zeros(0, dtype=np.int64),
    }


def _distribution(values: np.ndarray, pmf: np.ndarray, label: str) -> list[dict]:
    n = len(values)
    observed = np.bincount(values, minlength=len(pmf))[: len(pmf)]
    return [
        {label: k, "observed": int(observed[k]), "observed_share": float(observed[k] / n) if n else 0.0,
         "expected": float(pmf[k] * n), "expected_share": float(pmf[k])}
        for k in range(len(pmf))
    ]


def _sum_histogram(sums: np.ndarray, pool: int, pick: int, bins: int = 24) -> list[dict]:
    """Observed sums per bin, with the normal approximation of what chance predicts for the same bin."""
    mean, sd = sum_moments(pool, pick)
    lo, hi = pick * (pick + 1) // 2, pick * (2 * pool - pick + 1) // 2  # smallest and largest possible sums
    width = max(1, int(np.ceil((hi - lo + 1) / bins)))
    edges = np.arange(lo, hi + width + 1, width)
    observed, _ = np.histogram(sums, bins=edges)
    cdf = stats.norm(mean, sd).cdf(edges - 0.5)
    expected = np.diff(cdf) * len(sums)
    return [
        {"from": int(edges[i]), "to": int(edges[i + 1] - 1), "observed": int(observed[i]), "expected": float(expected[i])}
        for i in range(len(observed))
    ]


def game_trends(history: History, window: int = 200) -> dict:
    """Trend data for a game. `window` is how many of the latest draws the time series cover."""
    game = history.game
    pool, pick, total = game.pool, game.pick, len(history)
    shapes = draw_shapes(history.main, pool)
    sum_mean, sum_sd = sum_moments(pool, pick)
    rolling = {k: pd.Series(v).rolling(ROLLING, min_periods=1).mean().to_numpy() for k, v in shapes.items()}

    start = max(0, total - window)
    series = [
        {
            "date": history.dates[i].isoformat(),
            "odd": int(shapes["odd"][i]),
            "even": int(pick - shapes["odd"][i]),
            "high": int(shapes["high"][i]),
            "low": int(pick - shapes["high"][i]),
            "consecutive": int(shapes["consecutive"][i]),
            "sum": int(shapes["sum"][i]),
            "spread": int(shapes["spread"][i]),
            "odd_avg": float(rolling["odd"][i]),
            "high_avg": float(rolling["high"][i]),
            "consecutive_avg": float(rolling["consecutive"][i]),
            "sum_avg": float(rolling["sum"][i]),
        }
        for i in range(start, total)
    ]
    cons_pmf = consecutive_pairs_pmf(pool, pick)
    return {
        "game": game.key,
        "draws": total,
        "window": len(series),
        "rolling_window": ROLLING,
        "odd_even": {
            "distribution": _distribution(shapes["odd"], odd_count_pmf(pool, pick), "odd"),
            "mean_odd": float(shapes["odd"].mean()) if total else None,
            "expected_odd": pick * ((pool + 1) // 2) / pool,
        },
        "high_low": {
            "distribution": _distribution(shapes["high"], high_count_pmf(pool, pick), "high"),
            "split_at": pool // 2,
            "mean_high": float(shapes["high"].mean()) if total else None,
            "expected_high": pick * (pool - pool // 2) / pool,
        },
        "consecutive": {
            "distribution": _distribution(shapes["consecutive"], cons_pmf, "pairs"),
            "share_with_any": float((shapes["consecutive"] > 0).mean()) if total else None,
            "expected_share_with_any": float(1 - cons_pmf[0]),
        },
        "sums": {
            "histogram": _sum_histogram(shapes["sum"], pool, pick),
            "mean": float(shapes["sum"].mean()) if total else None,
            "sd": float(shapes["sum"].std(ddof=1)) if total > 1 else None,
            "expected_mean": sum_mean,
            "expected_sd": sum_sd,
            "min": int(shapes["sum"].min()) if total else None,
            "max": int(shapes["sum"].max()) if total else None,
        },
        "series": series,
    }
