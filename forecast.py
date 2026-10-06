"""Forecast per-number draw frequency with Google TimesFM (falls back to smoothing)."""
import random

WINDOW = 20      # rolling window (draws) used to build each number's frequency series
HORIZON = 8      # steps forecast ahead; the mean is the number's score

_model = None
_backend = None  # "timesfm" or "smoothing"


def _load_timesfm():
    global _model, _backend
    if _backend:
        return
    try:
        import numpy  # noqa: F401
        import timesfm
        m = timesfm.TimesFM_2p5_200M_torch.from_pretrained("google/timesfm-2.5-200m-pytorch")
        m.compile(timesfm.ForecastConfig(max_context=512, max_horizon=32, normalize_inputs=True))
        _model, _backend = m, "timesfm"
    except Exception as e:  # not installed, no weights, wrong Python...
        _backend = "smoothing"
        print("TimesFM unavailable, using smoothing fallback:", repr(e)[:160])


def backend():
    _load_timesfm()
    return _backend


def freq_series(draws, maxnum):
    """For each number 1..maxnum, rolling frequency series over the draws."""
    series = {}
    for n in range(1, maxnum + 1):
        hits = [1.0 if n in d else 0.0 for d in draws]
        out, run = [], 0.0
        for i, h in enumerate(hits):
            run += h
            if i >= WINDOW:
                run -= hits[i - WINDOW]
            out.append(run / min(i + 1, WINDOW))
        series[n] = out
    return series


def _smooth(s, alpha=0.15):
    lvl = s[0]
    for x in s[1:]:
        lvl = alpha * x + (1 - alpha) * lvl
    return lvl


def scores(draws, maxnum):
    """Return {number: forecast score}. Higher = model expects it more often."""
    _load_timesfm()
    series = freq_series(draws, maxnum)
    if _backend == "timesfm":
        import numpy as np
        inputs = [np.array(series[n][-512:], dtype="float32") for n in range(1, maxnum + 1)]
        point, _ = _model.forecast(horizon=HORIZON, inputs=inputs)
        return {n: float(point[n - 1].mean()) for n in range(1, maxnum + 1)}
    return {n: _smooth(series[n]) for n in range(1, maxnum + 1)}


def suggest(draws, maxnum, pick):
    sc = scores(draws, maxnum)
    ranked = sorted(sc, key=sc.get, reverse=True)
    return {"numbers": sorted(ranked[:pick]), "scores": sc, "backend": _backend}


def backtest(draws, maxnum, pick, steps=30):
    """Walk forward: forecast each of the last `steps` draws from earlier data,
    compare hits of the model's top picks with random picks."""
    steps = min(steps, len(draws) - WINDOW - 5)
    if steps < 5:
        return None
    model_hits = rand_hits = 0
    rng = random.Random(1)
    for i in range(len(draws) - steps, len(draws)):
        sc = scores(draws[:i], maxnum)
        top = set(sorted(sc, key=sc.get, reverse=True)[:pick])
        model_hits += len(top & set(draws[i]))
        rand_hits += len(set(rng.sample(range(1, maxnum + 1), pick)) & set(draws[i]))
    return {
        "steps": steps,
        "model_avg": model_hits / steps,
        "random_avg": rand_hits / steps,
        "expected_by_chance": pick * len(draws[0]) / maxnum,
    }
