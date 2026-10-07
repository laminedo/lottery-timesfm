"""Backtest arithmetic: chance baselines, match counting, and the walk-forward scorer."""
from datetime import date, timedelta
from math import comb

import numpy as np
import pytest

from app.forecast import backtest as bt
from app.games import GAMES

PB, MM, LOTTO, HIT5 = (GAMES[k] for k in ("powerball", "megamillions", "wa-lotto", "wa-hit5"))
ALL = ["balanced", "hot", "cold", "entropy"]


def steps_for(game, n, components_for, seed=0):
    """`n` fair draws; `components_for(actual_main, actual_bonus)` supplies each step's distributions."""
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        actual = np.sort(rng.choice(game.pool, game.pick, replace=False) + 1)
        bonus = int(rng.integers(1, game.bonus_pool + 1)) if game.bonus_pool else None
        main_c, bonus_c = components_for(actual, bonus)
        out.append(bt.Step(date(2026, 1, 1) + timedelta(days=i), actual, bonus, main_c, bonus_c))
    return out


def flat(game):
    main = {c: np.full(game.pool, game.pick / game.pool) for c in ("timesfm", "hot", "cold", "uniform")}
    bonus = {c: np.full(game.bonus_pool, 1 / game.bonus_pool) for c in main} if game.bonus_pool else None
    return main, bonus


@pytest.mark.parametrize("pool,pick", [(69, 5), (70, 5), (49, 6), (42, 5)])
def test_match_pmf_is_hypergeometric(pool, pick):
    pmf = bt.match_pmf(pool, pick)
    assert pmf.sum() == pytest.approx(1)
    for m in range(pick + 1):
        assert pmf[m] == pytest.approx(comb(pick, m) * comb(pool - pick, pick - m) / comb(pool, pick))
    mean, sd = bt.match_moments(pool, pick)
    assert mean == pytest.approx(pmf @ np.arange(pick + 1)) == pytest.approx(pick * pick / pool)
    assert sd**2 == pytest.approx(pmf @ (np.arange(pick + 1) - mean) ** 2)


def test_expected_matches_for_each_game():
    assert bt.match_moments(69, 5)[0] == pytest.approx(25 / 69)  # Powerball: 0.362 per line
    assert bt.match_moments(49, 6)[0] == pytest.approx(36 / 49)
    assert bt.match_pmf(42, 5)[5] == pytest.approx(1 / 850_668)  # all five = the Hit 5 jackpot odds


def test_count_matches():
    assert bt.count_matches([1, 2, 3, 4, 5], [5, 4, 9, 10, 11]) == 2
    assert bt.count_matches(np.array([1, 2, 3]), np.array([4, 5, 6])) == 0
    assert bt.count_matches([7, 8, 9], [9, 8, 7]) == 3


def test_chance_test_z_and_p_value():
    mu, sigma = bt.match_moments(69, 5)
    at_chance = bt.chance_test(mu, 100, 69, 5)
    assert at_chance["z"] == pytest.approx(0) and at_chance["p_value"] == pytest.approx(1)
    high = bt.chance_test(mu + 2 * sigma / 10, 100, 69, 5)  # two standard errors above chance
    assert high["z"] == pytest.approx(2) and high["p_value"] == pytest.approx(0.0455, abs=1e-4)
    low = bt.chance_test(mu - 2 * sigma / 10, 100, 69, 5)
    assert low["z"] == pytest.approx(-2) and low["p_value"] == pytest.approx(high["p_value"])
    assert bt.chance_test(0.4, 0, 69, 5) == {"z": None, "p_value": None}


def test_a_strategy_that_knows_the_answer_scores_every_number():
    def oracle(actual, bonus):
        main, bonus_c = flat(PB)
        main["timesfm"] = np.full(PB.pool, 1e-9)
        main["timesfm"][actual - 1] = 1.0
        bonus_c["timesfm"] = np.full(PB.bonus_pool, 1e-9)
        bonus_c["timesfm"][bonus - 1] = 1.0
        return main, bonus_c

    result = bt.run_backtest(PB, steps_for(PB, 40, oracle), ["balanced", "entropy"], samples=5)
    balanced, entropy = result["strategies"]
    assert balanced["top_pick"]["mean_matches"] == 5 and balanced["top_pick"]["histogram"] == [0, 0, 0, 0, 0, 40]
    assert balanced["top_pick"]["p_value"] < 1e-12 and not balanced["top_pick"]["consistent_with_chance"]
    assert balanced["bonus"]["top_hits"] == 40 and balanced["bonus"]["top_hit_rate"] == 1.0
    assert balanced["mean_log_lift"] > 2
    assert balanced["sampled"]["mean_matches"] == pytest.approx(5, abs=0.01)
    # The uniform strategy saw the same draws and stays near chance.
    assert entropy["top_pick"]["mean_matches"] < 1.5 and entropy["mean_log_lift"] == pytest.approx(0)


def test_a_strategy_that_avoids_the_answer_scores_zero():
    def anti(actual, bonus):
        main, bonus_c = flat(HIT5)
        main["timesfm"] = np.ones(HIT5.pool)
        main["timesfm"][actual - 1] = 0.0
        return main, bonus_c

    result = bt.run_backtest(HIT5, steps_for(HIT5, 30, anti), ["balanced"], samples=10)
    (s,) = result["strategies"]
    assert s["top_pick"]["total_matches"] == 0 and s["sampled"]["mean_matches"] == 0
    assert s["bonus"] is None and result["baseline"]["bonus_hit_rate"] is None


def test_uninformed_strategies_land_on_the_chance_baseline():
    result = bt.run_backtest(LOTTO, steps_for(LOTTO, 3000, lambda a, b: flat(LOTTO)), ALL, samples=1, seed=5)
    mu, sigma = bt.match_moments(49, 6)
    assert result["baseline"]["expected_matches"] == pytest.approx(mu)
    for s in result["strategies"]:
        top = s["top_pick"]
        assert abs(top["mean_matches"] - mu) < 4 * sigma / np.sqrt(3000), s["key"]
        assert sum(top["histogram"]) == 3000
        assert top["ci95"][0] < top["mean_matches"] < top["ci95"][1]
        assert s["mean_log_lift"] == pytest.approx(0)
    observed = np.array(result["strategies"][0]["top_pick"]["histogram"]) / 3000
    assert observed == pytest.approx(result["baseline"]["match_pmf"], abs=0.03)


def test_backtest_is_deterministic_for_a_seed_and_reports_every_draw():
    steps = steps_for(PB, 25, lambda a, b: flat(PB))
    a = bt.run_backtest(PB, steps, ALL, samples=3, seed=11)
    b = bt.run_backtest(PB, steps, ALL, samples=3, seed=11)
    c = bt.run_backtest(PB, steps, ALL, samples=3, seed=12)
    assert a == b and a["timeline"] != c["timeline"]
    assert (a["draws"], a["from"], a["to"]) == (25, "2026-01-01", "2026-01-25")
    assert len(a["timeline"]) == 25
    row = a["timeline"][0]
    assert row["actual"] == steps[0].actual_main.tolist()
    for key in ALL:
        assert len(set(row[key]["line"])) == 5 and all(1 <= n <= 69 for n in row[key]["line"])
        assert row[key]["matches"] == bt.count_matches(row[key]["line"], row["actual"])
        assert 1 <= row[key]["bonus"] <= 26


def test_bonus_is_scored_only_on_draws_of_the_current_bonus_pool():
    steps = steps_for(MM, 20, lambda a, b: flat(MM))
    # The first eight draws predate the 24-ball matrix: no bonus distribution, ball possibly 25.
    steps = [bt.Step(s.draw_date, s.actual_main, None, s.main_components, None) for s in steps[:8]] + steps[8:]
    result = bt.run_backtest(MM, steps, ["balanced"], samples=0)
    bonus = result["strategies"][0]["bonus"]
    assert bonus["scored_draws"] == 12
    assert bonus["mean_probability_on_drawn"] == pytest.approx(1 / 24)
    assert result["strategies"][0]["sampled"]["mean_matches"] is None  # samples=0


def test_unknown_strategy_is_an_error():
    with pytest.raises(ValueError, match="Unknown strategies"):
        bt.run_backtest(PB, [], ["lucky"])


def test_empty_backtest_does_not_divide_by_zero():
    result = bt.run_backtest(PB, [], ALL)
    assert result["draws"] == 0 and result["from"] is None
    assert result["strategies"][0]["top_pick"]["p_value"] is None
