"""Quantile-to-probability mapping, strategy blending and line sampling."""
import numpy as np
import pytest

from app.forecast import distribution as dist
from app.forecast import sampler
from app.forecast.backends import QUANTILE_LEVELS, SmoothingBackend
from app.games import GAMES, validate_line

from .conftest import history_from, synthetic_draws

PB, MM, LOTTO, HIT5 = (GAMES[k] for k in ("powerball", "megamillions", "wa-lotto", "wa-hit5"))


class RecordingBackend(SmoothingBackend):
    """Smoothing backend that remembers the series it was asked to forecast."""

    def __init__(self):
        super().__init__()
        self.calls: list[list[np.ndarray]] = []

    def predict_batch(self, series, horizon):
        self.calls.append([np.array(s) for s in series])
        return super().predict_batch(series, horizon)


def test_to_presence_scales_to_pick_and_caps_at_one():
    p = dist.to_presence(np.array([1.0, 1.0, 2.0, 0.0]), 2)
    assert p.sum() == pytest.approx(2) and p.tolist() == [0.5, 0.5, 1.0, 0.0]
    capped = dist.to_presence(np.array([100.0, 1.0, 1.0, 1.0]), 2)
    assert capped.max() == pytest.approx(1.0) and capped.sum() == pytest.approx(2)
    assert capped[1:] == pytest.approx([1 / 3] * 3)


def test_to_presence_falls_back_to_uniform_and_ignores_bad_values():
    assert dist.to_presence(np.zeros(4), 2).tolist() == [0.5] * 4
    assert dist.to_presence(np.array([np.nan, -3.0, 1.0, 1.0]), 1).tolist() == [0, 0, 0.5, 0.5]


def test_quantiles_to_pmf_puts_mass_between_the_quantiles():
    pmf = dist.quantiles_to_pmf(np.linspace(20, 30, 9), 69)
    assert pmf.sum() == pytest.approx(1) and (pmf >= 0).all()
    assert pmf[19:30].sum() == pytest.approx(0.8, abs=0.06)  # numbers 20..30 hold the central 80%
    assert pmf[:19].sum() == pytest.approx(0.1, abs=0.03) and pmf[30:].sum() == pytest.approx(0.1, abs=0.03)


def test_quantiles_to_pmf_survives_crossed_and_out_of_range_quantiles():
    pmf = dist.quantiles_to_pmf(np.array([-5, 3, 2, 10, 10, 10, 50, 49, 500]), 42)
    assert pmf.sum() == pytest.approx(1) and np.isfinite(pmf).all() and (pmf >= 0).all()


@pytest.mark.parametrize("pool,pick", [(69, 5), (49, 6), (26, 1)])
def test_order_statistics_are_proper_distributions(pool, pick):
    ks = np.arange(1, pool + 1)
    for k in range(1, pick + 1):
        pmf = dist.order_statistic_pmf(pool, pick, k)
        assert pmf.sum() == pytest.approx(1)
        assert pmf @ ks == pytest.approx(k * (pool + 1) / (pick + 1))  # known mean of the k-th smallest
    # Every number sits in exactly one position, so the positions together cover the pool evenly.
    total = sum(dist.order_statistic_pmf(pool, pick, k) for k in range(1, pick + 1))
    assert total == pytest.approx(np.full(pool, pick / pool))


@pytest.mark.parametrize("pool,pick", [(69, 5), (49, 6), (24, 1)])
def test_fair_positional_quantiles_map_to_a_flat_distribution(pool, pick):
    fair = np.array([dist.order_statistic_quantiles(pool, pick, k) for k in range(1, pick + 1)])
    assert len(QUANTILE_LEVELS) == fair.shape[1]
    assert dist.positional_presence(fair, pool) == pytest.approx(np.full(pool, pick / pool))


def test_positional_presence_follows_a_shifted_forecast():
    fair = np.array([dist.order_statistic_quantiles(69, 5, k) for k in range(1, 6)])
    low = dist.positional_presence(np.clip(fair - 8, 1, 69), 69)
    assert low.sum() == pytest.approx(5)
    assert low[:20].mean() > 5 / 69 > low[-20:].mean()


@pytest.mark.parametrize("game", [PB, MM, LOTTO, HIT5], ids=lambda g: g.key)
def test_core_forecast_is_a_valid_distribution(game):
    gf = dist.game_features(history_from(game, synthetic_draws(game, 150)))
    out = dist.core_forecast(SmoothingBackend(), gf, len(gf.history))
    main = out["main"]
    assert main["informative"] and main["core"].shape == (game.pool,)
    for name in ("core", "representation_a", "representation_b", *[f"channels.{c}" for c in dist.CHANNEL_WEIGHTS]):
        vec = main["channels"][name.split(".")[1]] if "." in name else main[name]
        assert vec.sum() == pytest.approx(game.pick), name
        assert ((vec >= 0) & (vec <= 1)).all(), name
    assert (main["rate_low"] <= main["rate_high"] + 1e-9).all()
    assert len(main["positions"]) == game.pick
    if game.bonus_pool:
        assert out["bonus"]["core"].shape == (game.bonus_pool,)
        assert out["bonus"]["core"].sum() == pytest.approx(1)
    else:
        assert out["bonus"] is None


def test_core_forecast_sees_only_draws_before_the_target():
    draws = synthetic_draws(HIT5, 140)
    gf_a = dist.game_features(history_from(HIT5, draws))
    changed = draws[:100] + synthetic_draws(HIT5, 40, seed=99)  # same first 100 draws, different future
    gf_b = dist.game_features(history_from(HIT5, changed))
    backend = RecordingBackend()
    a = dist.core_forecast(backend, gf_a, 100)
    b = dist.core_forecast(backend, gf_b, 100)
    assert np.array_equal(a["main"]["core"], b["main"]["core"])
    # And every series handed to the model stops at row 100.
    assert max(len(s) for s in backend.calls[0]) == 100


def test_context_window_limits_the_series_length():
    gf = dist.game_features(history_from(HIT5, synthetic_draws(HIT5, 140)))
    backend = RecordingBackend()
    dist.core_forecast(backend, gf, 140, context=64)
    assert {len(s) for s in backend.calls[0]} == {64}


def test_short_history_gives_a_uniform_pool_without_calling_the_model():
    gf = dist.game_features(history_from(HIT5, synthetic_draws(HIT5, dist.MIN_DRAWS - 1)))
    backend = RecordingBackend()
    out = dist.core_forecast(backend, gf, len(gf.history))
    assert not out["main"]["informative"] and not backend.calls
    assert out["main"]["core"] == pytest.approx(np.full(42, 5 / 42))


def test_mega_ball_forecast_uses_only_draws_of_the_current_bonus_pool():
    from datetime import date

    # 60 draws ending just before the April 2025 change, then 40 under the 24-ball matrix.
    old = synthetic_draws(MM, 60, seed=1, end=date(2025, 4, 4))
    new = synthetic_draws(MM, 40, seed=2, end=date(2025, 8, 26))
    assert all(d.draw_date < MM.bonus_since for d in old) and all(d.draw_date >= MM.bonus_since for d in new)
    gf = dist.game_features(history_from(MM, old + new))
    assert len(gf.bonus) == 40 and gf.bonus_upto(100) == 40 and gf.bonus_upto(50) == 0
    out = dist.core_forecast(SmoothingBackend(), gf, 100)
    assert out["bonus"]["context_draws"] == 40 and len(out["bonus"]["core"]) == 24
    early = dist.core_forecast(SmoothingBackend(), gf, 70)  # only 10 bonus draws so far: not enough
    assert not early["bonus"]["informative"] and early["main"]["informative"]


def test_classical_weights_favour_recent_hits_and_long_gaps():
    main = np.array([[1, 2]] * 30 + [[3, 4]] * 15)  # balls 1-2 are old news; 3-4 are recent; 5-6 never drawn
    f = dist.PoolFeatures(dist.ball_features(main, 6), dist.positional_features(main), 6, 2)
    w = dist.classical_weights(f, len(main))
    assert w["hot"].sum() == pytest.approx(2) and w["cold"].sum() == pytest.approx(2)
    assert w["hot"][2] > w["hot"][0] > w["hot"][4]
    assert w["cold"][4] > w["cold"][0] > w["cold"][2]
    assert dist.classical_weights(f, 0)["hot"] == pytest.approx(np.full(6, 2 / 6))


def test_blend_mixes_normalised_components():
    comps = {"timesfm": np.array([4.0, 0, 0, 0]), "hot": np.array([0, 1.0, 1.0, 0]),
             "cold": np.array([0, 0, 0, 9.0]), "uniform": np.ones(4)}
    p = sampler.blend(comps, {"timesfm": 1, "hot": 1})
    assert p == pytest.approx([0.5, 0.25, 0.25, 0], abs=1e-9)
    assert sampler.blend(comps, sampler.STRATEGIES["entropy"]["weights"]) == pytest.approx([0.25] * 4)


def test_blend_temperature_sharpens_and_flattens():
    comps = {c: np.array([0.5, 0.3, 0.2]) for c in sampler.COMPONENTS}
    w = {"timesfm": 1}
    cool, neutral, warm = (sampler.blend(comps, w, t) for t in (0.5, 1.0, 3.0))
    assert neutral == pytest.approx([0.5, 0.3, 0.2])
    assert cool[0] > neutral[0] > warm[0] and cool[2] < neutral[2] < warm[2]
    assert cool.sum() == pytest.approx(1) and warm.sum() == pytest.approx(1)


def test_blend_rejects_bad_weights():
    comps = {c: np.ones(3) for c in sampler.COMPONENTS}
    with pytest.raises(ValueError, match="Unknown components"):
        sampler.blend(comps, {"lucky": 1.0})
    with pytest.raises(ValueError, match="must be positive"):
        sampler.blend(comps, {"timesfm": 0.0, "hot": -1.0})


def test_every_strategy_preset_is_a_full_weighting():
    for name, preset in sampler.STRATEGIES.items():
        assert set(preset["weights"]) == set(sampler.COMPONENTS), name
        assert sum(preset["weights"].values()) == pytest.approx(1), name


def test_sampling_without_replacement_never_repeats_and_tracks_the_weights():
    rng = np.random.default_rng(0)
    p = np.array([0.4, 0.3, 0.2, 0.1, 0.0])
    picks = np.array([sampler.sample_without_replacement(rng, p, 2) for _ in range(4000)])
    assert (picks[:, 0] != picks[:, 1]).all()
    seen = np.bincount(picks.ravel(), minlength=5) / 4000
    assert seen[0] > seen[1] > seen[2] > seen[3] > seen[4] == 0
    with pytest.raises(ValueError, match="Cannot draw 6"):
        sampler.sample_without_replacement(rng, p, 6)


@pytest.mark.parametrize("game", [PB, MM, LOTTO, HIT5], ids=lambda g: g.key)
def test_generated_lines_obey_the_game_rules(game):
    rng = np.random.default_rng(3)
    main_p = rng.dirichlet(np.ones(game.pool))
    bonus_p = rng.dirichlet(np.ones(game.bonus_pool)) if game.bonus_pool else None
    lines = sampler.generate_lines(rng, game, main_p, bonus_p, 5)
    assert len(lines) == 5
    for line in lines:
        assert validate_line(game, line.primary, line.bonus) == (line.primary, line.bonus)  # valid and sorted
        assert len(set(line.primary)) == game.pick
    assert len({(tuple(line.primary), line.bonus) for line in lines}) == 5  # no repeated lines


def test_generated_lines_are_reproducible_by_seed():
    p, bp = np.full(69, 1 / 69), np.full(26, 1 / 26)
    a = sampler.generate_lines(np.random.default_rng(7), PB, p, bp, 3)
    b = sampler.generate_lines(np.random.default_rng(7), PB, p, bp, 3)
    c = sampler.generate_lines(np.random.default_rng(8), PB, p, bp, 3)
    assert a == b and a != c


def test_duplicate_lines_are_dropped_when_the_distribution_allows_only_a_few():
    # Six numbers carry all the weight, so only C(6,5) = 6 distinct Hit 5 lines exist in practice.
    p = np.zeros(42)
    p[:6] = 1 / 6
    lines = sampler.generate_lines(np.random.default_rng(0), HIT5, p, None, 6)
    assert len({tuple(line.primary) for line in lines}) == len(lines) == 6


def test_generate_lines_checks_distribution_sizes():
    with pytest.raises(ValueError, match="needs 69"):
        sampler.generate_lines(np.random.default_rng(0), PB, np.ones(70) / 70, np.ones(26) / 26, 1)
    with pytest.raises(ValueError, match="bonus distribution over 26"):
        sampler.generate_lines(np.random.default_rng(0), PB, np.ones(69) / 69, None, 1)


def test_line_lift_is_one_under_a_flat_distribution():
    (line,) = sampler.generate_lines(np.random.default_rng(0), HIT5, np.full(42, 1 / 42), None, 1)
    assert line.lift == pytest.approx(1.0)
