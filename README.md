# Lottery × TimesFM

Live demo (browser-only, smoothing model, no TimesFM): https://laminedo.github.io/lottery-timesfm/

Run locally for real TimesFM forecasts:

    .venv/bin/python server.py   # http://127.0.0.1:8044 (or python3 server.py for the fallback)

Paste past draws (one per line) or load a random sample; the app forecasts each number's
rolling frequency and suggests the top-N. A walk-forward backtest compares the picks with random picks.

TimesFM is optional (Python 3.10+): `pip install torch numpy timesfm` (weights download from Hugging Face on first run).
Without it the app uses an exponential-smoothing fallback and says so in the header.
Lottery draws are random; this is for entertainment only.
