"""Time-series representations and the classical statistics built on them."""
import numpy as np
import pytest

from app.analytics import features, metrics, trends
from app.games import GAMES

from .conftest import history_from, synthetic_draws

# Five draws of 2 numbers from a pool of 6.
DRAWS = np.array([[1, 2], [2, 3], [5, 6], [2, 6], [1, 4]])


def test_hit_matrix_marks_drawn_balls():
    hits = features.hit_matrix(DRAWS, 6)
    assert hits.shape == (5, 6)
    assert hits.sum(axis=1).tolist() == [2, 2, 2, 2, 2]
    assert hits[:, 1].tolist() == [1, 1, 0, 1, 0]  # ball 2


def test_rolling_density_uses_shorter_windows_at_the_start():
    density = features.rolling_density(features.hit_matrix(DRAWS, 6), 3)
    assert density[:, 1] == pytest.approx([1, 1, 2 / 3, 2 / 3, 1 / 3])


def test_ema_starts_from_the_base_rate():
    hits = features.hit_matrix(DRAWS, 6)
    out = features.ema(hits, span=3, start=1 / 3)  # alpha = 0.5
    assert out[:3, 1] == pytest.approx([0.5 + 1 / 6, 0.5 + (0.5 + 1 / 6) / 2, (0.5 + (0.5 + 1 / 6) / 2) / 2])


def test_recency_gap_counts_draws_since_last_hit():
    gap = features.recency_gap(features.hit_matrix(DRAWS, 6))
    assert gap[:, 1].tolist() == [0, 0, 1, 0, 1]  # ball 2
    assert gap[:, 3].tolist() == [1, 2, 3, 4, 0]  # ball 4: unseen until the last draw, counted from the start


def test_features_never_look_ahead():
    """Row t of every series must equal what you get from draws 0..t alone."""
    game = GAMES["wa-hit5"]
    main = history_from(game, synthetic_draws(game, 120)).main
    full = features.ball_features(main, game.pool)
    full_pos = features.positional_features(main)
    for cut in (1, 37, 90):
        part = features.ball_features(main[:cut], game.pool)
        part_pos = features.positional_features(main[:cut])
        for name in ("density_10", "density_30", "density_50", "ema_10", "ema_30", "ema_50", "gap"):
            assert np.allclose(full.channel(name)[:cut], part.channel(name)), name
        assert np.allclose(full_pos.positions[:cut], part_pos.positions)
        assert np.allclose(full_pos.moving_sum[10][:cut], part_pos.moving_sum[10])


def test_positional_features_sort_each_draw():
    pos = features.positional_features(np.array([[9, 3, 5], [1, 8, 2]]))
    assert pos.positions.tolist() == [[3, 5, 9], [1, 2, 8]]
    assert pos.sums.tolist() == [17, 11]
    assert pos.moving_sum[10].tolist() == [17, 14]


def test_pool_metrics_counts_gaps_and_hot_cold():
    m = metrics.pool_metrics(DRAWS, 6)
    by_number = {r["number"]: r for r in m["numbers"]}
    assert (m["draws"], m["pick"], m["expected_count"]) == (5, 2, pytest.approx(5 * 2 / 6))
    assert by_number[2]["count"] == 3 and by_number[2]["current_gap"] == 1
    assert by_number[2]["mean_gap"] == pytest.approx(1.5)  # hits at draws 0, 1, 3
    assert by_number[4]["max_gap"] == 4 and by_number[4]["current_gap"] == 0
    assert by_number[3]["current_gap"] == 3 and by_number[3]["max_gap"] == 3
    assert m["cold"][0] in (3, 5)  # both last seen three draws ago
    assert sum(r["count"] for r in m["numbers"]) == 10


def test_uniformity_test_accepts_fair_draws_and_rejects_a_rigged_ball():
    rng = np.random.default_rng(1)
    fair = np.array([rng.choice(40, 5, replace=False) + 1 for _ in range(3000)])
    counts = np.bincount(fair.ravel(), minlength=41)[1:]
    assert metrics.uniformity_test(counts, 5)["p_value"] > 0.01
    rigged = fair.copy()
    rigged[::4, 0] = 7  # force ball 7 into a quarter of the draws
    counts = np.bincount(rigged.ravel(), minlength=41)[1:]
    assert metrics.uniformity_test(counts, 5)["p_value"] < 1e-6


def test_chance_distributions_sum_to_one_and_match_known_values():
    for pool, pick in ((69, 5), (70, 5), (49, 6), (42, 5)):
        assert trends.odd_count_pmf(pool, pick).sum() == pytest.approx(1)
        assert trends.high_count_pmf(pool, pick).sum() == pytest.approx(1)
        assert trends.consecutive_pairs_pmf(pool, pick).sum() == pytest.approx(1)
    # 6/49: the well-known 49.5% chance that a draw holds at least one adjacent pair.
    assert 1 - trends.consecutive_pairs_pmf(49, 6)[0] == pytest.approx(0.4952, abs=1e-4)
    assert trends.sum_moments(69, 5) == (175.0, pytest.approx(43.20, abs=0.01))


def test_draw_shapes():
    shapes = trends.draw_shapes(np.array([[1, 2, 3, 40, 41], [10, 20, 30, 40, 50]]), 69)
    assert shapes["odd"].tolist() == [3, 0]
    assert shapes["high"].tolist() == [2, 2]  # upper half starts at 35
    assert shapes["consecutive"].tolist() == [3, 0]
    assert shapes["sum"].tolist() == [87, 150]
    assert shapes["spread"].tolist() == [40, 40]


def test_game_trends_observed_counts_cover_every_draw():
    game = GAMES["powerball"]
    t = trends.game_trends(history_from(game, synthetic_draws(game, 300)), window=50)
    assert t["draws"] == 300 and len(t["series"]) == 50
    for section, key in (("odd_even", "distribution"), ("high_low", "distribution"), ("consecutive", "distribution")):
        assert sum(row["observed"] for row in t[section][key]) == 300
        assert sum(row["expected"] for row in t[section][key]) == pytest.approx(300)
    assert sum(b["observed"] for b in t["sums"]["histogram"]) == 300
    assert sum(b["expected"] for b in t["sums"]["histogram"]) == pytest.approx(300, abs=1)
