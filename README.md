---
title: Lottery TimesFM
emoji: 🎱
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# Lottery × TimesFM

Live demo (browser-only, smoothing model, no TimesFM): https://laminedo.github.io/lottery-timesfm/

Run locally for real TimesFM forecasts:

    .venv/bin/python server.py   # http://127.0.0.1:8044 (or python3 server.py for the fallback)

Games: Powerball, Mega Millions, WA Hit 5 (5 of 42) and WA Lotto (6 of 49). The app loads each game's
official past draws (data.ny.gov for Powerball and Mega Millions, walottery.com for the Washington games),
forecasts each number's rolling frequency with TimesFM and suggests a line. An optional walk-forward
backtest compares the picks with random picks.

The browser-only demo reads a saved snapshot in `public/data/`. Refresh it with
`.venv/bin/python server.py snapshot`, then commit and push.

TimesFM is optional (Python 3.10+): `pip install torch numpy timesfm` (weights download from Hugging Face on first run).
Without it the app uses an exponential-smoothing fallback and says so in the header.
Lottery draws are random; this is for entertainment only.
