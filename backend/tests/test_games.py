"""Draw rule validation: counts, ranges, duplicates, bonus balls, format eras, schedules."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.games import (
    GAMES,
    DrawValidationError,
    dedupe_lines,
    next_draw_at,
    next_draw_date_after,
    validate_draw,
    validate_line,
)

PB, MM, LOTTO, HIT5 = (GAMES[k] for k in ("powerball", "megamillions", "wa-lotto", "wa-hit5"))


def test_game_matrices_match_the_published_rules():
    assert (PB.pick, PB.pool, PB.bonus_pool) == (5, 69, 26)
    assert (MM.pick, MM.pool, MM.bonus_pool) == (5, 70, 24)
    assert (LOTTO.pick, LOTTO.pool, LOTTO.bonus_pool) == (6, 49, None)
    assert (HIT5.pick, HIT5.pool, HIT5.bonus_pool) == (5, 42, None)


def test_jackpot_odds_match_the_published_odds():
    assert PB.jackpot_odds == 292_201_338
    assert MM.jackpot_odds == 290_472_336
    assert LOTTO.jackpot_odds == 13_983_816
    assert HIT5.jackpot_odds == 850_668


def test_valid_line_is_returned_sorted():
    assert validate_line(PB, [69, 1, 35, 20, 7], 26) == ([1, 7, 20, 35, 69], 26)
    assert validate_line(LOTTO, [49, 1, 2, 3, 4, 5]) == ([1, 2, 3, 4, 5, 49], None)


@pytest.mark.parametrize("numbers", [[0, 1, 2, 3, 4], [1, 2, 3, 4, 70], [-5, 1, 2, 3, 4]])
def test_main_numbers_outside_the_pool_are_rejected(numbers):
    with pytest.raises(DrawValidationError, match="must be 1-69"):
        validate_line(PB, numbers, 1)


def test_pool_upper_bound_is_per_game():
    validate_line(MM, [1, 2, 3, 4, 70], 1)  # 70 is valid for Mega Millions
    with pytest.raises(DrawValidationError, match="must be 1-42"):
        validate_line(HIT5, [1, 2, 3, 4, 43])


def test_duplicate_main_numbers_are_rejected():
    with pytest.raises(DrawValidationError, match=r"duplicate main numbers \[7\]"):
        validate_line(PB, [7, 7, 1, 2, 3], 1)


@pytest.mark.parametrize("numbers", [[1, 2, 3, 4], [1, 2, 3, 4, 5, 6]])
def test_wrong_number_count_is_rejected(numbers):
    with pytest.raises(DrawValidationError, match="expected 5 main numbers"):
        validate_line(PB, numbers, 1)


@pytest.mark.parametrize("numbers", [[1, 2, 3, 4, 5.0], [1, 2, 3, 4, "5"], [1, 2, 3, 4, True]])
def test_non_integer_numbers_are_rejected(numbers):
    with pytest.raises(DrawValidationError, match="whole numbers"):
        validate_line(PB, numbers, 1)


@pytest.mark.parametrize("bonus", [0, 27, -1])
def test_bonus_outside_its_own_pool_is_rejected(bonus):
    with pytest.raises(DrawValidationError, match="Powerball must be 1-26"):
        validate_line(PB, [1, 2, 3, 4, 5], bonus)


def test_bonus_may_repeat_a_main_number():
    # The bonus ball comes from a separate drum, so the same value is legal.
    assert validate_line(PB, [1, 2, 3, 4, 5], 5) == ([1, 2, 3, 4, 5], 5)


def test_missing_bonus_is_rejected_when_the_game_has_one():
    with pytest.raises(DrawValidationError, match="missing Powerball"):
        validate_line(PB, [1, 2, 3, 4, 5], None)


def test_bonus_is_rejected_when_the_game_has_none():
    with pytest.raises(DrawValidationError, match="no bonus ball"):
        validate_line(HIT5, [1, 2, 3, 4, 5], 3)


def test_mega_ball_25_is_valid_only_before_the_2025_change():
    assert validate_draw(MM, [1, 2, 3, 4, 5], 25, date(2025, 4, 4)) == ([1, 2, 3, 4, 5], 25)
    with pytest.raises(DrawValidationError, match="Mega Ball must be 1-24"):
        validate_draw(MM, [1, 2, 3, 4, 5], 25, date(2025, 4, 8))
    with pytest.raises(DrawValidationError, match="Mega Ball must be 1-24"):
        validate_line(MM, [1, 2, 3, 4, 5], 25)


def test_draws_before_the_current_format_are_rejected():
    with pytest.raises(DrawValidationError, match="before the current 5-of-69 format"):
        validate_draw(PB, [1, 2, 3, 4, 5], 1, date(2015, 10, 3))
    with pytest.raises(DrawValidationError, match="before the current 5-of-42 format"):
        validate_draw(HIT5, [1, 2, 3, 4, 5], None, date(2020, 8, 29))


def test_dedupe_lines_removes_repeats_regardless_of_number_order():
    lines = [([5, 1, 3, 2, 4], 9), ([1, 2, 3, 4, 5], 9), ([1, 2, 3, 4, 5], 10), ([1, 2, 3, 4, 6], 9)]
    assert dedupe_lines(lines) == [([1, 2, 3, 4, 5], 9), ([1, 2, 3, 4, 5], 10), ([1, 2, 3, 4, 6], 9)]


def test_next_draw_is_the_same_evening_before_draw_time():
    et = ZoneInfo("America/New_York")
    wednesday_noon = datetime(2026, 10, 7, 12, 0, tzinfo=et)
    assert next_draw_at(PB, wednesday_noon) == datetime(2026, 10, 7, 22, 59, tzinfo=et)


def test_next_draw_skips_to_the_next_draw_day_after_draw_time():
    et = ZoneInfo("America/New_York")
    wednesday_late = datetime(2026, 10, 7, 23, 30, tzinfo=et)
    assert next_draw_at(PB, wednesday_late) == datetime(2026, 10, 10, 22, 59, tzinfo=et)  # Saturday
    assert next_draw_at(MM, wednesday_late) == datetime(2026, 10, 9, 23, 0, tzinfo=et)  # Friday


def test_next_draw_converts_from_other_timezones():
    # 03:30 UTC Thursday is 20:30 Wednesday in Seattle: Wednesday's 20:00 Lotto draw has passed.
    now = datetime(2026, 10, 8, 3, 30, tzinfo=ZoneInfo("UTC"))
    assert next_draw_at(LOTTO, now).date() == date(2026, 10, 10)
    assert next_draw_at(HIT5, now).date() == date(2026, 10, 8)  # daily


def test_next_draw_date_after():
    assert next_draw_date_after(MM, date(2026, 10, 6)) == date(2026, 10, 9)
    assert next_draw_date_after(HIT5, date(2026, 10, 6)) == date(2026, 10, 7)
