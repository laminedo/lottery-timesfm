"""Forecast backends. Each turns a batch of series into quantile forecasts of the same shape.

`predict_batch(series, horizon)` returns an array of shape (len(series), horizon, 10): the mean
followed by the 10%..90% quantiles, which is TimesFM's native output layout.

- TimesFMBackend:   google/timesfm-2.5-200m-pytorch, in process.
- RemoteBackend:    the same model behind app/inference_service.py, for running it on a GPU host.
- SmoothingBackend: exponential smoothing. Used when TimesFM is not installed, and in fast tests.
"""
from __future__ import annotations

import logging
import threading
from typing import Protocol, Sequence

import numpy as np
from scipy.signal import lfilter

from ..config import Settings

log = logging.getLogger(__name__)

QUANTILE_LEVELS = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
MEAN, Q10, Q50, Q90 = 0, 1, 5, 9  # indices into the last axis of a forecast
MAX_HORIZON = 128  # one TimesFM output patch; every horizon up to this costs the same


class ForecastBackend(Protocol):
    name: str

    def predict_batch(self, series: Sequence[np.ndarray], horizon: int) -> np.ndarray: ...

    def describe(self) -> dict: ...


class SmoothingBackend:
    """Flat forecast at the exponentially smoothed level; quantiles from in-sample one-step errors."""

    name = "smoothing"

    def __init__(self, alpha: float = 0.15):
        self.alpha = alpha

    def predict_batch(self, series: Sequence[np.ndarray], horizon: int) -> np.ndarray:
        out = np.zeros((len(series), horizon, 10))
        a = self.alpha
        for i, s in enumerate(series):
            s = np.asarray(s, dtype=np.float64)
            if len(s) == 0:
                continue
            level, _ = lfilter([a], [1.0, -(1 - a)], s, zi=[(1 - a) * s[0]])
            errors = s[1:] - level[:-1] if len(s) > 1 else np.zeros(1)
            q = level[-1] + np.quantile(errors, QUANTILE_LEVELS)
            row = np.concatenate([[level[-1]], q])
            if s.min() >= 0:
                row = np.maximum(row, 0.0)
            out[i] = row
        return out

    def describe(self) -> dict:
        return {"name": self.name, "label": "Exponential smoothing (TimesFM not installed)", "ready": True}


class TimesFMBackend:
    """TimesFM 2.5 (200M, PyTorch). Loads on first use; one forward pass at a time."""

    name = "timesfm"

    def __init__(self, settings: Settings):
        self.model_id = settings.timesfm_model
        self.batch_size = settings.timesfm_batch_size
        self.context = settings.timesfm_context
        self.flip = settings.timesfm_flip_invariance
        self.device_pref = settings.timesfm_device
        self.device: str | None = None
        self._model = None
        self._lock = threading.Lock()

    @staticmethod
    def available() -> bool:
        try:
            import timesfm  # noqa: F401
            import torch  # noqa: F401
        except ImportError:
            return False
        return True

    def _pick_device(self) -> str:
        import torch

        if self.device_pref != "auto":
            return self.device_pref
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    def _load(self, device: str):
        import timesfm
        import torch

        model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(self.model_id, torch_compile=False)
        if device != "cuda":  # the library only chooses between cuda and cpu itself
            model.model.to(device)
            model.model.device = torch.device(device)
        model.compile(
            timesfm.ForecastConfig(
                max_context=self.context,
                max_horizon=MAX_HORIZON,
                normalize_inputs=True,
                per_core_batch_size=self.batch_size,
                use_continuous_quantile_head=True,
                force_flip_invariance=self.flip,
                infer_is_positive=True,
                fix_quantile_crossing=True,
            )
        )
        # Fail here, not mid-request, if the device cannot run the model.
        probe = model.forecast(horizon=1, inputs=[np.linspace(0, 1, 64, dtype=np.float32)] * self.batch_size)[1]
        if not np.isfinite(probe).all():
            raise RuntimeError(f"TimesFM produced non-finite output on {device}")
        return model

    def ensure_loaded(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            device = self._pick_device()
            try:
                self._model = self._load(device)
            except Exception:
                if device == "cpu":
                    raise
                log.warning("TimesFM failed on %s, falling back to CPU", device, exc_info=True)
                device = "cpu"
                self._model = self._load(device)
            self.device = device
            log.info("TimesFM %s ready on %s", self.model_id, device)

    def predict_batch(self, series: Sequence[np.ndarray], horizon: int) -> np.ndarray:
        if horizon > MAX_HORIZON:
            raise ValueError(f"horizon {horizon} exceeds {MAX_HORIZON}")
        if not len(series):
            return np.zeros((0, horizon, 10))
        self.ensure_loaded()
        inputs = [np.asarray(s, dtype=np.float32)[-self.context :] for s in series]
        n = len(inputs)
        # The library pads short batches with float64 arrays, which the MPS device rejects; pad here instead.
        inputs += [np.zeros(8, dtype=np.float32)] * (-n % self.batch_size)
        with self._lock:
            _, quantiles = self._model.forecast(horizon=horizon, inputs=inputs)
        return np.asarray(quantiles[:n], dtype=np.float64)

    def describe(self) -> dict:
        return {
            "name": self.name,
            "label": "TimesFM 2.5 (200M)",
            "model": self.model_id,
            "device": self.device,
            "context": self.context,
            "ready": self._model is not None,
        }


class RemoteBackend:
    """Calls a separate inference service: POST {url}/predict_batch."""

    name = "timesfm"

    def __init__(self, url: str, timeout: float = 300.0):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self._info: dict | None = None

    def predict_batch(self, series: Sequence[np.ndarray], horizon: int) -> np.ndarray:
        import httpx

        if not len(series):
            return np.zeros((0, horizon, 10))
        body = {"horizon": horizon, "series": [np.asarray(s, dtype=np.float32).tolist() for s in series]}
        r = httpx.post(f"{self.url}/predict_batch", json=body, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        self._info = data.get("backend")
        return np.asarray(data["quantiles"], dtype=np.float64)

    def describe(self) -> dict:
        info = dict(self._info or {"name": self.name, "label": "TimesFM (remote)", "ready": False})
        info["remote"] = self.url
        return info


def make_backend(settings: Settings) -> ForecastBackend:
    """Choose the backend from settings. 'auto' prefers TimesFM and falls back to smoothing."""
    choice = settings.forecast_backend
    if choice not in ("auto", "timesfm", "smoothing"):
        raise ValueError(f"FORECAST_BACKEND must be auto, timesfm or smoothing, got '{choice}'")
    if choice == "smoothing":
        return SmoothingBackend()
    if settings.inference_url:
        return RemoteBackend(settings.inference_url)
    if TimesFMBackend.available():
        return TimesFMBackend(settings)
    if choice == "timesfm":
        raise RuntimeError("FORECAST_BACKEND=timesfm but the timesfm package is not installed (uv sync --extra timesfm)")
    log.warning("TimesFM is not installed; using exponential smoothing")
    return SmoothingBackend()
