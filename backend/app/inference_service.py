"""Standalone TimesFM inference service, for running the model apart from the API (GPU host, Cloud Run).

    uvicorn app.inference_service:app --port 8100

Point the API at it with INFERENCE_URL=http://host:8100. It holds no data: series in, quantiles out.
"""
from __future__ import annotations

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import get_settings
from .forecast.backends import MAX_HORIZON, SmoothingBackend, TimesFMBackend

MAX_SERIES = 4096


class PredictRequest(BaseModel):
    series: list[list[float]] = Field(..., description="One list of observations per series, oldest first")
    horizon: int = Field(..., ge=1, le=MAX_HORIZON)


def create_app(backend=None) -> FastAPI:
    settings = get_settings()
    if backend is None:
        use_timesfm = settings.forecast_backend != "smoothing" and TimesFMBackend.available()
        backend = TimesFMBackend(settings) if use_timesfm else SmoothingBackend()
    app = FastAPI(title="TimesFM inference", version="0.1.0")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "backend": backend.describe()}

    @app.post("/predict_batch")
    def predict_batch(body: PredictRequest) -> dict:
        """Quantile forecasts, shape (series, horizon, 10): mean, then the 10%..90% quantiles."""
        if len(body.series) > MAX_SERIES:
            raise HTTPException(413, f"At most {MAX_SERIES} series per request")
        if any(len(s) == 0 for s in body.series):
            raise HTTPException(422, "Every series needs at least one observation")
        out = backend.predict_batch([np.asarray(s, dtype=np.float32) for s in body.series], body.horizon)
        return {"quantiles": np.round(out, 6).tolist(), "backend": backend.describe()}

    return app


app = create_app()
