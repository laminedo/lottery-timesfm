"""Classical per-number statistics: frequency, skip/gap intervals, hot/cold and rolling momentum."""
from __future__ import annotations

import numpy as np
from scipy import stats

from .features import WINDOWS, ball_features
from .history import History

HOT_COLD_COUNT = 10  # how many numbers the hot and cold lists hold


def uniformity_test(counts: np.ndarray, pick: int) -> dict:
    """Chi-square test that every ball is equally likely.

    Balls within a draw are sampled without replacement, so counts are negatively correlated and the
    plain statistic is too small by (pool - pick) / (pool - 1); dividing by it restores a chi-square
    with pool - 1 degrees of freedom (Joe, 1993, "Tests of uniformity for sets of lotto numbers").
    """
    pool, total = len(counts), float(np.sum(counts))
    if total == 0 or pool < 2:
        return {"statistic": None, "p_value": None, "dof": pool - 1}
    expected = total / pool
    raw = float(np.sum((counts - expected) ** 2) / expected)
    stat = raw * (pool - 1) / (pool - pick) if pool > pick else raw
    return {"statistic": stat, "p_value": float(stats.chi2.sf(stat, pool - 1)), "dof": pool - 1}


def gap_stats(hits: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per ball: (mean draws from one appearance to the next, longest run of draws without it).

    The mean is NaN for a ball with fewer than two appearances. The longest run includes the stretch
    before the first appearance and the one still open at the end of the history.
    """
    total, pool = hits.shape
    mean, longest = np.full(pool, np.nan), np.zeros(pool)
    for n in range(pool):
        idx = np.flatnonzero(hits[:, n])
        if len(idx) == 0:
            longest[n] = total
            continue
        between = np.diff(idx)
        if len(between):
            mean[n] = between.mean()
        longest[n] = max(idx[0], total - 1 - idx[-1], (between.max() - 1) if len(between) else 0)
    return mean, longest


def pool_metrics(numbers: np.ndarray, pool: int) -> dict:
    """Statistics for one pool (main numbers, or the bonus ball with one number per draw)."""
    numbers = np.asarray(numbers, dtype=np.int64).reshape(len(numbers), -1)
    total, pick = numbers.shape
    f = ball_features(numbers, pool)
    counts = f.hits.sum(axis=0)
    expected = total * pick / pool
    sd = np.sqrt(total * (pick / pool) * (1 - pick / pool)) if total else 0.0
    z = (counts - expected) / sd if sd > 0 else np.zeros(pool)
    mean_gap, max_gap = gap_stats(f.hits) if total else (np.full(pool, np.nan), np.zeros(pool))
    channels = {"gap": f.gap, **{f"ema_{w}": f.ema[w] for w in WINDOWS}}
    last = {name: (arr[-1] if total else np.zeros(pool)) for name, arr in channels.items()}
    recent = {w: f.hits[-w:].sum(axis=0) for w in WINDOWS}
    # Momentum: short-run hit rate minus long-run hit rate. Positive means appearing more often lately.
    momentum = last["ema_10"] - last["ema_50"]

    # Hot: most hits in the last 30 draws (ties by the 10-draw EMA). Cold: longest current gap.
    hot_order = np.lexsort((-last["ema_10"], -recent[30]))[:HOT_COLD_COUNT]
    cold_order = np.argsort(-last["gap"], kind="stable")[:HOT_COLD_COUNT]
    hot, cold = set(hot_order.tolist()), set(cold_order.tolist())

    rows = []
    for n in range(pool):
        rows.append(
            {
                "number": n + 1,
                "count": int(counts[n]),
                "frequency": float(counts[n] / total) if total else 0.0,
                "z_score": float(z[n]),
                "current_gap": int(last["gap"][n]),
                "mean_gap": None if np.isnan(mean_gap[n]) else float(mean_gap[n]),
                "max_gap": int(max_gap[n]),
                "hits_10": int(recent[10][n]),
                "hits_30": int(recent[30][n]),
                "hits_50": int(recent[50][n]),
                "ema_10": float(last["ema_10"][n]),
                "ema_30": float(last["ema_30"][n]),
                "ema_50": float(last["ema_50"][n]),
                "momentum": float(momentum[n]),
                "status": "hot" if n in hot else "cold" if n in cold else "neutral",
            }
        )
    return {
        "draws": total,
        "pick": pick,
        "pool": pool,
        "expected_count": expected,
        "expected_frequency": pick / pool,
        "expected_gap": pool / pick,
        "uniformity": uniformity_test(counts, pick),
        "hot": [int(n) + 1 for n in hot_order],
        "cold": [int(n) + 1 for n in cold_order],
        "numbers": rows,
    }


def game_metrics(history: History) -> dict:
    game = history.game
    out = {"game": game.key, "main": pool_metrics(history.main, game.pool), "bonus": None}
    if game.bonus_pool:
        out["bonus"] = pool_metrics(history.bonus_values(), game.bonus_pool)
        out["bonus"]["since"] = game.bonus_since.isoformat()
    return out
