"""From TimesFM's continuous quantile forecasts to a discrete probability for every ball.

One forecast step ("what do we expect for the draw after row `upto`?") sends every series of both
representations through the backend in a single batch, then maps the output back to the pool:

Representation A. Each ball has seven series. Each gives an estimate of the ball's hit rate over the
coming draws:
  density_w  forecast w draws ahead: by then the window holds only future draws, so the forecast
             *is* the expected hit rate. Its 10%/90% quantiles are the confidence band.
  ema_w      forecast 2w draws ahead, with the remaining weight of the past (1-alpha)^(2w) removed.
  gap        forecast 51-100 draws ahead, far enough that today's gap no longer matters. A ball
             with hit rate p has been absent (1 - p) / p draws on average, so p = 1 / (1 + mean gap).
Each channel's rates are scaled to sum to `pick` (one draw holds exactly `pick` balls), then averaged
with CHANNEL_WEIGHTS.

Representation B. Each sorted position has a series. Its nine quantiles for the next draw define a
piecewise-linear CDF, which is cut at half-integers into a probability for each ball number. A ball
can sit in only one position, so summing over positions gives its presence probability. That sum is
divided by the same construction applied to the exact order-statistic quantiles of a fair draw, so an
uninformative forecast maps to a flat distribution instead of to the artefacts of a 9-point CDF.

The core distribution is REPRESENTATION_WEIGHTS-weighted A and B. All vectors here are presence
probabilities: they sum to `pick`, and a fair draw has pick / pool everywhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import comb

import numpy as np

from ..analytics.features import WINDOWS, BallFeatures, PositionalFeatures, ball_features, positional_features
from ..analytics.history import History
from .backends import MEAN, Q10, Q90, QUANTILE_LEVELS, ForecastBackend

PIPELINE_VERSION = "2"
CHANNEL_WEIGHTS = {
    "density_10": 0.2, "density_30": 0.2, "density_50": 0.2,
    "ema_10": 0.1, "ema_30": 0.1, "ema_50": 0.1,
    "gap": 0.1,
}
REPRESENTATION_WEIGHTS = {"A": 0.7, "B": 0.3}
MIN_DRAWS = 20  # with less history than this a pool is reported as uniform
RATE_CAP = 5.0  # a channel may put at most this multiple of the base rate on one ball
GAP_HORIZONS = slice(50, 100)  # forecast steps 51..100, averaged for the gap channel
LIFT_RANGE = (0.2, 5.0)
HORIZON = 2 * max(WINDOWS)  # longest look-ahead any channel needs


def channel_horizon(name: str) -> int:
    """How many draws ahead a density or EMA channel is read."""
    kind, window = name.split("_")
    return int(window) if kind == "density" else 2 * int(window)


def to_presence(rates: np.ndarray, pick: int) -> np.ndarray:
    """Scale non-negative rates so they sum to `pick`, with no entry above 1. All zero -> uniform."""
    rates = np.clip(np.nan_to_num(np.asarray(rates, dtype=np.float64), nan=0.0, posinf=0.0), 0.0, None)
    pool = len(rates)
    if rates.sum() <= 0:
        return np.full(pool, pick / pool)
    p = rates * pick / rates.sum()
    for _ in range(pool):  # move any excess above 1 onto the other balls
        over = p > 1
        if not over.any():
            break
        free = ~over & (p > 0)
        excess = (p[over] - 1).sum()
        p[over] = 1.0
        if not free.any():
            break
        p[free] += excess * p[free] / p[free].sum()
    return p


def quantiles_to_pmf(quantiles: np.ndarray, pool: int) -> np.ndarray:
    """Nine quantile values (10%..90%) of a number in 1..pool -> probability of each integer.

    The CDF runs linearly through the quantile points and reaches 0 and 1 at the edges of the pool.
    """
    lo, hi = 0.5, pool + 0.5
    q = np.maximum.accumulate(np.clip(np.asarray(quantiles, dtype=np.float64), lo, hi))
    xs = np.concatenate([[lo], q, [hi]])
    xs = np.maximum.accumulate(xs + np.arange(len(xs)) * 1e-9)  # strictly increasing for interpolation
    cdf = np.interp(np.arange(pool + 1) + 0.5, xs, np.concatenate([[0.0], QUANTILE_LEVELS, [1.0]]))
    pmf = np.clip(np.diff(cdf), 0.0, None)
    return pmf / pmf.sum()


def order_statistic_pmf(pool: int, pick: int, k: int) -> np.ndarray:
    """P(the k-th smallest of `pick` numbers drawn from 1..pool equals n), n = 1..pool. k is 1-based."""
    total = comb(pool, pick)
    return np.array([comb(n - 1, k - 1) * comb(pool - n, pick - k) / total for n in range(1, pool + 1)])


def order_statistic_quantiles(pool: int, pick: int, k: int) -> np.ndarray:
    """Quantiles (10%..90%) of the k-th smallest number in a fair draw, on the continuous scale
    where integer n covers [n - 0.5, n + 0.5]."""
    cdf = np.concatenate([[0.0], np.cumsum(order_statistic_pmf(pool, pick, k))])
    return np.interp(QUANTILE_LEVELS, cdf, np.arange(pool + 1) + 0.5)


def positional_presence(position_quantiles: np.ndarray, pool: int) -> np.ndarray:
    """Representation B -> presence probabilities. `position_quantiles` is (pick, 9)."""
    pick = len(position_quantiles)
    forecast = sum(quantiles_to_pmf(position_quantiles[k], pool) for k in range(pick))
    fair = sum(quantiles_to_pmf(order_statistic_quantiles(pool, pick, k + 1), pool) for k in range(pick))
    lift = np.clip(forecast / np.maximum(fair, 1e-12), *LIFT_RANGE)
    return to_presence(lift, pick)


@dataclass(frozen=True)
class PoolFeatures:
    balls: BallFeatures
    positions: PositionalFeatures
    pool: int
    pick: int

    def __len__(self) -> int:
        return len(self.balls.hits)


@dataclass(frozen=True)
class GameFeatures:
    """Both representations for a game's main pool and, if it has one, its bonus pool."""

    history: History
    main: PoolFeatures
    bonus: PoolFeatures | None

    def bonus_upto(self, upto: int) -> int:
        """Rows of the bonus series known before main-history row `upto`."""
        return max(0, upto - self.history.bonus_start)


def game_features(history: History) -> GameFeatures:
    game = history.game
    main = PoolFeatures(ball_features(history.main, game.pool), positional_features(history.main), game.pool, game.pick)
    bonus = None
    if game.bonus_pool:
        values = history.bonus_values()
        bonus = PoolFeatures(ball_features(values, game.bonus_pool), positional_features(values), game.bonus_pool, 1)
    return GameFeatures(history, main, bonus)


def _pool_series(f: PoolFeatures, upto: int, context: int) -> list[np.ndarray]:
    """Every series for one pool, cut at `upto`: A channels ball by ball, then positions, sum, moving sum."""
    lo = max(0, upto - context)
    out = [f.balls.channel(name)[lo:upto, n] for name in CHANNEL_WEIGHTS for n in range(f.pool)]
    out += [f.positions.positions[lo:upto, k] for k in range(f.pick)]
    out += [f.positions.sums[lo:upto], f.positions.moving_sum[10][lo:upto]]
    return out


def _series_count(f: PoolFeatures) -> int:
    return len(CHANNEL_WEIGHTS) * f.pool + f.pick + 2


def _finite(values: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    return np.where(np.isfinite(values), values, fallback)


def _decode_pool(f: PoolFeatures, upto: int, fc: np.ndarray) -> dict:
    """Turn one pool's slice of the forecast batch, shape (series, HORIZON, 10), into probabilities."""
    pool, pick, base = f.pool, f.pick, f.balls.base_rate
    cap = min(1.0, RATE_CAP * base)
    channels: dict[str, np.ndarray] = {}
    rate_parts, low_parts, high_parts = [], [], []
    for c, name in enumerate(CHANNEL_WEIGHTS):
        series_fc = fc[c * pool : (c + 1) * pool]
        last = f.balls.channel(name)[upto - 1]
        if name == "gap":
            long_run = _finite(series_fc[:, GAP_HORIZONS, MEAN], 1 / base - 1).mean(axis=1)
            channels[name] = to_presence(np.clip(1 / (1 + np.maximum(long_run, 0.0)), 0.0, cap), pick)
            continue
        h = channel_horizon(name)
        block = series_fc[:, h - 1]
        if name.startswith("ema"):
            alpha = 2.0 / (int(name.split("_")[1]) + 1)
            past = (1 - alpha) ** h
            rates = np.clip((_finite(block[:, MEAN], last) - past * last) / (1 - past), 0.0, cap)
        else:
            rates = np.clip(_finite(block[:, MEAN], last), 0.0, cap)
            rate_parts.append(np.clip(_finite(block[:, MEAN], last), 0.0, 1.0))
            low_parts.append(np.clip(_finite(block[:, Q10], last), 0.0, 1.0))
            high_parts.append(np.clip(_finite(block[:, Q90], last), 0.0, 1.0))
        channels[name] = to_presence(rates, pick)

    weight_sum = sum(CHANNEL_WEIGHTS.values())
    rep_a = sum(CHANNEL_WEIGHTS[name] * channels[name] for name in channels) / weight_sum

    offset = len(CHANNEL_WEIGHTS) * pool
    pos_fc = fc[offset : offset + pick, 0]  # next draw
    last_pos = f.positions.positions[upto - 1]
    pos_q = np.clip(_finite(pos_fc[:, Q10 : Q90 + 1], last_pos[:, None]), 1.0, pool)
    rep_b = positional_presence(pos_q, pool)

    core = REPRESENTATION_WEIGHTS["A"] * rep_a + REPRESENTATION_WEIGHTS["B"] * rep_b
    sum_fc, moving_fc = fc[offset + pick, 0], fc[offset + pick + 1, 9]
    return {
        "informative": True,
        "context_draws": int(upto),
        "core": core,
        "representation_a": rep_a,
        "representation_b": rep_b,
        "channels": channels,
        # Raw TimesFM forecast of the hit rate (average of the three density windows) with its 80% band.
        "rate": np.mean(rate_parts, axis=0),
        "rate_low": np.mean(low_parts, axis=0),
        "rate_high": np.mean(high_parts, axis=0),
        "positions": [
            {"position": k + 1, "mean": float(_finite(pos_fc[k, MEAN], last_pos[k])), "quantiles": pos_q[k]}
            for k in range(pick)
        ],
        "sum": {"mean": float(sum_fc[MEAN]), "quantiles": sum_fc[Q10 : Q90 + 1]},
        "moving_sum": {"mean": float(moving_fc[MEAN]), "low": float(moving_fc[Q10]), "high": float(moving_fc[Q90])},
    }


def _uniform_pool(f: PoolFeatures, upto: int) -> dict:
    flat = np.full(f.pool, f.pick / f.pool)
    return {"informative": False, "context_draws": int(upto), "core": flat, "representation_a": flat,
            "representation_b": flat, "channels": {}, "rate": flat, "rate_low": flat, "rate_high": flat,
            "positions": [], "sum": None, "moving_sum": None}


def core_forecasts(backend: ForecastBackend, gf: GameFeatures, uptos: list[int], context: int = 512) -> list[dict]:
    """Forecasts for several target rows in one model call (a backtest fills whole batches this way).

    Element i is the forecast for the draw after row `uptos[i]`, using only rows before it:
    {"main": pool forecast, "bonus": pool forecast or None}. Arrays are numpy; see `to_jsonable`.
    """
    batch: list[np.ndarray] = []
    plans = []
    for upto in uptos:
        pools = [("main", gf.main, upto)]
        if gf.bonus is not None:
            pools.append(("bonus", gf.bonus, gf.bonus_upto(upto)))
        spans: dict[str, tuple[int, int]] = {}
        for name, f, n in pools:
            if n >= MIN_DRAWS:
                spans[name] = (len(batch), len(batch) + _series_count(f))
                batch += _pool_series(f, n, context)
        plans.append((pools, spans))
    fc = backend.predict_batch(batch, HORIZON) if batch else np.zeros((0, HORIZON, 10))

    results = []
    for pools, spans in plans:
        out: dict = {"main": None, "bonus": None}
        for name, f, n in pools:
            out[name] = _decode_pool(f, n, fc[slice(*spans[name])]) if name in spans else _uniform_pool(f, n)
        results.append(out)
    return results


def core_forecast(backend: ForecastBackend, gf: GameFeatures, upto: int, context: int = 512) -> dict:
    """The model's forecast for the draw after row `upto`, using only rows before it."""
    return core_forecasts(backend, gf, [upto], context)[0]


def classical_weights(f: PoolFeatures, upto: int) -> dict[str, np.ndarray]:
    """Presence probabilities from the two classical models, known before row `upto`.

    hot:  recency-weighted hit rate (10/30/50-draw EMAs).
    cold: the moving-gap model. A ball's weight is the chance it would have appeared by now,
          1 - (1 - base)^(gap + 1): near the base rate just after a hit, approaching 1 when long overdue.
    """
    flat = np.full(f.pool, f.pick / f.pool)
    if upto <= 0:
        return {"hot": flat, "cold": flat}
    b = f.balls
    hot = 0.5 * b.ema[10][upto - 1] + 0.3 * b.ema[30][upto - 1] + 0.2 * b.ema[50][upto - 1]
    cold = 1.0 - (1.0 - b.base_rate) ** (b.gap[upto - 1] + 1.0)
    return {"hot": to_presence(hot, f.pick), "cold": to_presence(cold, f.pick)}


def to_jsonable(value, digits: int = 6):
    """Numpy arrays and scalars -> rounded plain lists and floats, recursively."""
    if isinstance(value, dict):
        return {k: to_jsonable(v, digits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v, digits) for v in value]
    if isinstance(value, np.ndarray):
        return [round(float(x), digits) for x in value]
    if isinstance(value, (np.floating, float)):
        return round(float(value), digits)
    if isinstance(value, np.integer):
        return int(value)
    return value
