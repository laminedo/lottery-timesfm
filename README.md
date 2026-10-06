---
title: Powerball TimesFM
emoji: 🎱
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# Powerball × TimesFM

Live demo (browser-only, smoothing model, no TimesFM): https://laminedo.github.io/lottery-timesfm/

Run locally for real TimesFM forecasts:

    .venv/bin/python server.py   # http://127.0.0.1:8044 (or python3 server.py for the fallback)

The app loads every official Powerball draw since Oct 2015 (data.ny.gov), forecasts each number's
rolling frequency with TimesFM and suggests 5 numbers plus the Powerball. An optional walk-forward
backtest compares the picks with random picks.

TimesFM is optional (Python 3.10+): `pip install torch numpy timesfm` (weights download from Hugging Face on first run).
Without it the app uses an exponential-smoothing fallback and says so in the header.
Lottery draws are random; this is for entertainment only.
