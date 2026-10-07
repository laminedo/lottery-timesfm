"""Blend the model components into one distribution and sample ticket lines from it."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..games import Game, dedupe_lines, validate_line

COMPONENTS = ("timesfm", "hot", "cold", "uniform")

# Strategy presets: how much each component contributes to the sampling distribution.
STRATEGIES: dict[str, dict] = {
    "balanced": {
        "label": "Balanced",
        "description": "The TimesFM core distribution on its own.",
        "weights": {"timesfm": 1.0, "hot": 0.0, "cold": 0.0, "uniform": 0.0},
    },
    "hot": {
        "label": "Hot numbers",
        "description": "Leans on numbers that have appeared often in recent draws.",
        "weights": {"timesfm": 0.25, "hot": 0.75, "cold": 0.0, "uniform": 0.0},
    },
    "cold": {
        "label": "Contrarian / cold",
        "description": "Leans on overdue numbers with the longest current gaps.",
        "weights": {"timesfm": 0.25, "hot": 0.0, "cold": 0.75, "uniform": 0.0},
    },
    "entropy": {
        "label": "High entropy",
        "description": "Pure chance: every number equally likely.",
        "weights": {"timesfm": 0.0, "hot": 0.0, "cold": 0.0, "uniform": 1.0},
    },
}

MIN_TEMPERATURE, MAX_TEMPERATURE = 0.2, 5.0
_FLOOR = 1e-12  # keeps every number drawable, so a full line always exists


def normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    """Component weights as non-negative fractions summing to 1. Unknown names are an error."""
    unknown = set(weights) - set(COMPONENTS)
    if unknown:
        raise ValueError(f"Unknown components {sorted(unknown)}; expected {list(COMPONENTS)}")
    w = {c: max(0.0, float(weights.get(c, 0.0))) for c in COMPONENTS}
    total = sum(w.values())
    if total <= 0:
        raise ValueError("At least one component weight must be positive")
    return {c: v / total for c, v in w.items()}


def blend(components: dict[str, np.ndarray], weights: dict[str, float], temperature: float = 1.0) -> np.ndarray:
    """Weighted mixture of the components, sharpened (T < 1) or flattened (T > 1). Sums to 1.

    Components may be on any common scale (presence probabilities here); each is normalised first.
    """
    w = normalize_weights(weights)
    pool = len(next(iter(components.values())))
    mix = np.zeros(pool)
    for name, weight in w.items():
        if weight > 0:
            part = np.clip(np.asarray(components[name], dtype=np.float64), 0.0, None)
            mix += weight * (part / part.sum() if part.sum() > 0 else np.full(pool, 1 / pool))
    t = float(np.clip(temperature, MIN_TEMPERATURE, MAX_TEMPERATURE))
    sharpened = np.power(np.maximum(mix, _FLOOR), 1.0 / t)
    return sharpened / sharpened.sum()


def sample_without_replacement(rng: np.random.Generator, p: np.ndarray, k: int) -> np.ndarray:
    """k distinct indices, drawn one at a time with probability proportional to p among those left.

    Uses the Gumbel top-k trick, which is equivalent to that sequential draw.
    """
    if k > len(p):
        raise ValueError(f"Cannot draw {k} distinct numbers from a pool of {len(p)}")
    keys = np.log(np.maximum(p, _FLOOR)) + rng.gumbel(size=len(p))
    return np.sort(np.argpartition(-keys, k - 1)[:k])


def top_k(p: np.ndarray, k: int) -> np.ndarray:
    """Indices of the k most probable entries; ties go to the lower number."""
    return np.sort(np.argsort(-p, kind="stable")[:k])


@dataclass(frozen=True)
class Line:
    primary: list[int]
    bonus: int | None
    lift: float  # geometric mean of p(number) / uniform over the line; 1.0 = no different from chance


def _lift(p: np.ndarray, idx: np.ndarray) -> float:
    return float(np.exp(np.mean(np.log(np.maximum(p[idx], _FLOOR) * len(p)))))


def generate_lines(
    rng: np.random.Generator,
    game: Game,
    main_p: np.ndarray,
    bonus_p: np.ndarray | None,
    count: int,
) -> list[Line]:
    """`count` distinct, rule-valid lines sampled from the given distributions."""
    if len(main_p) != game.pool:
        raise ValueError(f"main distribution has {len(main_p)} entries, {game.name} needs {game.pool}")
    if game.bonus_pool and (bonus_p is None or len(bonus_p) != game.bonus_pool):
        raise ValueError(f"{game.name} needs a bonus distribution over {game.bonus_pool} numbers")
    lines: list[Line] = []
    seen: list[tuple[list[int], int | None]] = []
    for _ in range(count * 50):  # repeats are rare; the cap only guards degenerate distributions
        idx = sample_without_replacement(rng, main_p, game.pick)
        bonus = int(rng.choice(game.bonus_pool, p=bonus_p / bonus_p.sum())) + 1 if game.bonus_pool else None
        primary, bonus = validate_line(game, [int(i) + 1 for i in idx], bonus)
        if len(dedupe_lines(seen + [(primary, bonus)])) == len(seen):
            continue
        seen.append((primary, bonus))
        lines.append(Line(primary, bonus, _lift(main_p, idx)))
        if len(lines) == count:
            break
    return lines
