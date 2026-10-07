"""Time-series representations of a draw history.

Lottery numbers are labels, not magnitudes, so the raw balls are never treated as one continuous line.

Representation A (per ball): for every ball in the pool, series of
  - density_w: share of the last w draws that contained the ball (w = 10, 30, 50),
  - ema_w:     exponentially weighted hit rate with span w,
  - gap:       draws since the ball last appeared.

Representation B (per sorted position): the k-th smallest number of each draw, plus the draw sum and
its moving average.

Every value at row t depends only on draws 0..t, so slicing any series at [:i] gives exactly what was
known before draw i. Walk-forward backtests rely on that.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.signal import lfilter

WINDOWS = (10, 30, 50)


def hit_matrix(numbers: np.ndarray, pool: int) -> np.ndarray:
    """(T, k) ball numbers -> (T, pool) indicator, column n-1 is 1.0 when ball n was drawn."""
    numbers = np.asarray(numbers, dtype=np.int64).reshape(len(numbers), -1)
    hits = np.zeros((len(numbers), pool), dtype=np.float64)
    if numbers.size:
        hits[np.arange(len(numbers))[:, None], numbers - 1] = 1.0
    return hits


def rolling_density(hits: np.ndarray, window: int) -> np.ndarray:
    """Mean of the last `window` rows (fewer at the start of the history)."""
    return pd.DataFrame(hits).rolling(window, min_periods=1).mean().to_numpy()


def ema(hits: np.ndarray, span: int, start: float) -> np.ndarray:
    """EMA with alpha = 2 / (span + 1), started at `start` (the base rate) rather than the first row."""
    alpha = 2.0 / (span + 1)
    if len(hits) == 0:
        return hits.copy()
    zi = np.full((1, hits.shape[1]), (1 - alpha) * start)
    out, _ = lfilter([alpha], [1.0, -(1 - alpha)], hits, axis=0, zi=zi)
    return out


def recency_gap(hits: np.ndarray) -> np.ndarray:
    """Draws since each ball last appeared: 0 on a draw that contains it, then 1, 2, ...

    Before a ball's first appearance the gap counts from the start of the history.
    """
    t = np.arange(len(hits))[:, None]
    last_hit = np.maximum.accumulate(np.where(hits > 0, t, -1), axis=0)
    return (t - last_hit).astype(np.float64)


@dataclass(frozen=True)
class BallFeatures:
    """Representation A. Every array is (T, pool)."""

    hits: np.ndarray
    density: dict[int, np.ndarray]
    ema: dict[int, np.ndarray]
    gap: np.ndarray
    base_rate: float

    def channel(self, name: str) -> np.ndarray:
        """Series by channel name: 'density_30', 'ema_10', 'gap'."""
        if name == "gap":
            return self.gap
        kind, window = name.split("_")
        return (self.density if kind == "density" else self.ema)[int(window)]


def ball_features(numbers: np.ndarray, pool: int) -> BallFeatures:
    numbers = np.asarray(numbers, dtype=np.int64).reshape(len(numbers), -1)
    hits = hit_matrix(numbers, pool)
    base = numbers.shape[1] / pool
    return BallFeatures(
        hits=hits,
        density={w: rolling_density(hits, w) for w in WINDOWS},
        ema={w: ema(hits, w, base) for w in WINDOWS},
        gap=recency_gap(hits),
        base_rate=base,
    )


@dataclass(frozen=True)
class PositionalFeatures:
    """Representation B."""

    positions: np.ndarray  # (T, k), column j is the (j+1)-th smallest number
    sums: np.ndarray  # (T,)
    moving_sum: dict[int, np.ndarray]  # rolling mean of the draw sum


def positional_features(numbers: np.ndarray) -> PositionalFeatures:
    positions = np.sort(np.asarray(numbers, dtype=np.float64).reshape(len(numbers), -1), axis=1)
    sums = positions.sum(axis=1)
    moving = {w: pd.Series(sums).rolling(w, min_periods=1).mean().to_numpy() for w in WINDOWS}
    return PositionalFeatures(positions=positions, sums=sums, moving_sum=moving)
