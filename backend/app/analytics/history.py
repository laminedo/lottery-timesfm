"""A game's draws as arrays, oldest first."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from ..db import Database
from ..games import Game


@dataclass(frozen=True)
class History:
    game: Game
    draw_ids: np.ndarray  # (T,)
    dates: tuple[date, ...]
    main: np.ndarray  # (T, pick) sorted ascending, 1-based ball numbers
    bonus: np.ndarray  # (T,) bonus ball, 0 where the draw has none
    jackpots: tuple[int | None, ...]

    def __len__(self) -> int:
        return len(self.dates)

    @property
    def bonus_start(self) -> int:
        """Index of the first draw under the current bonus matrix (len(self) when there is none)."""
        since = self.game.bonus_since
        if since is None:
            return len(self)
        return next((i for i, d in enumerate(self.dates) if d >= since), len(self))

    def bonus_values(self, upto: int | None = None) -> np.ndarray:
        """Bonus balls drawn under the current bonus matrix, before index `upto`. Shape (n, 1)."""
        end = len(self) if upto is None else upto
        return self.bonus[self.bonus_start : max(end, self.bonus_start)].reshape(-1, 1)

    @classmethod
    def from_rows(cls, game: Game, rows: list[dict]) -> "History":
        rows = sorted(rows, key=lambda r: r["draw_date"])
        return cls(
            game=game,
            draw_ids=np.array([r.get("draw_id", i) for i, r in enumerate(rows)], dtype=np.int64),
            dates=tuple(r["draw_date"] for r in rows),
            main=np.array([sorted(r["primary_numbers"]) for r in rows], dtype=np.int64).reshape(len(rows), game.pick),
            bonus=np.array([r.get("bonus_number") or 0 for r in rows], dtype=np.int64),
            jackpots=tuple(r.get("jackpot_usd") for r in rows),
        )


def load_history(db: Database, game: Game) -> History:
    rows = db.fetch_all(
        "select draw_id, draw_date, primary_numbers, bonus_number, jackpot_usd from draws "
        "where game_key = %s and draw_date >= %s order by draw_date",
        (game.key, game.main_since),
    )
    return History.from_rows(game, rows)
