"""The real TimesFM model. Slow; deselect with `pytest -m "not timesfm"`."""
import numpy as np
import pytest

from app.config import Settings
from app.forecast import distribution as dist
from app.forecast.backends import Q10, Q90, TimesFMBackend
from app.games import GAMES

from .conftest import history_from, synthetic_draws

pytestmark = pytest.mark.timesfm


@pytest.fixture(scope="module")
def backend():
    if not TimesFMBackend.available():
        pytest.skip("timesfm is not installed")
    b = TimesFMBackend(Settings(_env_file=None, timesfm_batch_size=32))
    try:
        b.ensure_loaded()
    except Exception as e:  # no cached weights and no network
        pytest.skip(f"TimesFM weights unavailable: {e!r}")
    return b


def test_predict_batch_shape_for_ragged_and_partial_batches(backend):
    rng = np.random.default_rng(0)
    # 37 series is not a multiple of the batch size, and lengths differ, including longer than the context.
    series = [rng.random(n) for n in ([600, 512, 200, 40, 20] * 8)[:37]]
    out = backend.predict_batch(series, 12)
    assert out.shape == (37, 12, 10) and np.isfinite(out).all()
    assert (out[:, :, Q10] <= out[:, :, Q90] + 1e-6).all()
    assert (out >= 0).all()  # non-negative inputs give non-negative forecasts


def test_constant_and_empty_inputs(backend):
    out = backend.predict_batch([np.zeros(100), np.full(100, 0.25)], 5)
    assert np.isfinite(out).all()
    assert out[1, :, 0] == pytest.approx(0.25, abs=0.05)
    assert backend.predict_batch([], 5).shape == (0, 5, 10)
    with pytest.raises(ValueError, match="exceeds"):
        backend.predict_batch([np.ones(10)], 500)


def test_a_trend_is_extrapolated(backend):
    out = backend.predict_batch([np.linspace(0, 10, 256)], 8)
    assert out[0, -1, 0] > 10  # keeps rising


def test_core_forecast_with_timesfm_is_a_valid_distribution(backend):
    game = GAMES["wa-hit5"]
    gf = dist.game_features(history_from(game, synthetic_draws(game, 200)))
    core = dist.core_forecast(backend, gf, 200)["main"]["core"]
    assert core.sum() == pytest.approx(5) and ((core > 0) & (core < 1)).all()
    assert backend.describe()["device"] in ("mps", "cuda", "cpu")
