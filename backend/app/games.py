"""Game definitions, draw rules and schedules.

A game's history is only comparable within one number matrix, so each game records when its
current main matrix and its current bonus matrix began. Mega Millions is the case that needs both:
the white balls have been 5 of 70 since 2017, but the Mega Ball pool shrank from 25 to 24 in April 2025.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from math import comb
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo


class DrawValidationError(ValueError):
    """A draw or ticket line breaks the game's rules."""


@dataclass(frozen=True)
class Game:
    key: str
    name: str
    pick: int  # main numbers per draw
    pool: int  # main numbers are 1..pool
    main_since: date  # first draw under the current main matrix
    draw_days: tuple[int, ...]  # Monday = 0
    draw_time: time
    tz: str
    bonus_name: str | None = None
    # (first draw date, pool size) for each bonus matrix that shares the current main matrix, oldest first.
    bonus_eras: tuple[tuple[date, int], ...] = ()
    region: str = "US"

    @property
    def bonus_pool(self) -> int | None:
        """Current bonus pool size, or None when the game has no bonus ball."""
        return self.bonus_eras[-1][1] if self.bonus_eras else None

    @property
    def bonus_since(self) -> date | None:
        return self.bonus_eras[-1][0] if self.bonus_eras else None

    def bonus_pool_on(self, day: date) -> int | None:
        """Bonus pool size in force on `day` (None when the game has no bonus ball)."""
        pool = None
        for start, size in self.bonus_eras:
            if day >= start:
                pool = size
        return pool

    @property
    def jackpot_odds(self) -> int:
        """Number of equally likely outcomes: one line wins the top prize with probability 1/this."""
        return comb(self.pool, self.pick) * (self.bonus_pool or 1)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "region": self.region,
            "pick": self.pick,
            "pool": self.pool,
            "bonus_pool": self.bonus_pool,
            "bonus_name": self.bonus_name,
            "main_since": self.main_since.isoformat(),
            "bonus_since": self.bonus_since.isoformat() if self.bonus_since else None,
            "draw_days": list(self.draw_days),
            "draw_time": self.draw_time.strftime("%H:%M"),
            "timezone": self.tz,
            "jackpot_odds": self.jackpot_odds,
        }


GAMES: dict[str, Game] = {
    g.key: g
    for g in (
        Game(
            key="powerball",
            name="Powerball",
            pick=5,
            pool=69,
            main_since=date(2015, 10, 7),
            bonus_name="Powerball",
            bonus_eras=((date(2015, 10, 7), 26),),
            draw_days=(0, 2, 5),
            draw_time=time(22, 59),
            tz="America/New_York",
        ),
        Game(
            key="megamillions",
            name="Mega Millions",
            pick=5,
            pool=70,
            main_since=date(2017, 10, 31),
            bonus_name="Mega Ball",
            bonus_eras=((date(2017, 10, 31), 25), (date(2025, 4, 8), 24)),
            draw_days=(1, 4),
            draw_time=time(23, 0),
            tz="America/New_York",
        ),
        Game(
            key="wa-lotto",
            name="Lotto",
            region="WA",
            pick=6,
            pool=49,
            main_since=date(2003, 10, 8),
            draw_days=(0, 2, 5),
            draw_time=time(20, 0),
            tz="America/Los_Angeles",
        ),
        Game(
            key="wa-hit5",
            name="Hit 5",
            region="WA",
            pick=5,
            pool=42,
            main_since=date(2020, 8, 30),
            draw_days=(0, 1, 2, 3, 4, 5, 6),
            draw_time=time(20, 0),
            tz="America/Los_Angeles",
        ),
    )
}


def get_game(key: str) -> Game:
    try:
        return GAMES[key]
    except KeyError:
        raise KeyError(f"Unknown game '{key}'. Known games: {', '.join(GAMES)}") from None


def _check_main(game: Game, primary: Sequence[int]) -> list[int]:
    nums = list(primary)
    if any(isinstance(n, bool) or not isinstance(n, int) for n in nums):
        raise DrawValidationError(f"{game.name}: numbers must be whole numbers, got {nums}")
    if len(nums) != game.pick:
        raise DrawValidationError(f"{game.name}: expected {game.pick} main numbers, got {len(nums)}")
    out_of_range = [n for n in nums if not 1 <= n <= game.pool]
    if out_of_range:
        raise DrawValidationError(f"{game.name}: main numbers must be 1-{game.pool}, got {out_of_range}")
    if len(set(nums)) != len(nums):
        dupes = sorted({n for n in nums if nums.count(n) > 1})
        raise DrawValidationError(f"{game.name}: duplicate main numbers {dupes}")
    return sorted(nums)


def _check_bonus(game: Game, bonus: int | None, pool: int | None) -> int | None:
    if pool is None:
        if bonus is not None:
            raise DrawValidationError(f"{game.name} has no bonus ball, got {bonus}")
        return None
    if bonus is None:
        raise DrawValidationError(f"{game.name}: missing {game.bonus_name}")
    if isinstance(bonus, bool) or not isinstance(bonus, int) or not 1 <= bonus <= pool:
        raise DrawValidationError(f"{game.name}: {game.bonus_name} must be 1-{pool}, got {bonus}")
    return bonus


def validate_draw(
    game: Game, primary: Sequence[int], bonus: int | None, draw_date: date
) -> tuple[list[int], int | None]:
    """Check an official result against the rules in force on its date. Returns (sorted main, bonus)."""
    if draw_date < game.main_since:
        raise DrawValidationError(
            f"{game.name}: {draw_date} is before the current {game.pick}-of-{game.pool} format "
            f"({game.main_since})"
        )
    return _check_main(game, primary), _check_bonus(game, bonus, game.bonus_pool_on(draw_date))


def validate_line(game: Game, primary: Sequence[int], bonus: int | None = None) -> tuple[list[int], int | None]:
    """Check a ticket line against the game's current rules. Returns (sorted main, bonus)."""
    return _check_main(game, primary), _check_bonus(game, bonus, game.bonus_pool)


def dedupe_lines(lines: Iterable[tuple[Sequence[int], int | None]]) -> list[tuple[list[int], int | None]]:
    """Drop repeated ticket lines (same main set and bonus), keeping first-seen order."""
    seen: set[tuple[tuple[int, ...], int | None]] = set()
    out: list[tuple[list[int], int | None]] = []
    for primary, bonus in lines:
        key = (tuple(sorted(primary)), bonus)
        if key not in seen:
            seen.add(key)
            out.append((list(key[0]), bonus))
    return out


def draw_datetime(game: Game, day: date) -> datetime:
    return datetime.combine(day, game.draw_time, tzinfo=ZoneInfo(game.tz))


def next_draw_at(game: Game, now: datetime | None = None) -> datetime:
    """The next scheduled drawing strictly after `now`, as an aware datetime in the game's timezone."""
    tz = ZoneInfo(game.tz)
    now = (now or datetime.now(tz)).astimezone(tz)
    for offset in range(8):
        day = now.date() + timedelta(days=offset)
        if day.weekday() in game.draw_days:
            at = draw_datetime(game, day)
            if at > now:
                return at
    raise RuntimeError(f"{game.name} has no draw days configured")


def next_draw_date_after(game: Game, day: date) -> date:
    """The first scheduled draw date strictly after `day`."""
    for offset in range(1, 9):
        nxt = day + timedelta(days=offset)
        if nxt.weekday() in game.draw_days:
            return nxt
    raise RuntimeError(f"{game.name} has no draw days configured")
