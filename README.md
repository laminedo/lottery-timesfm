---
title: Lottery TimesFM
emoji: 🎱
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# Lottery Forecast Lab

Draw analytics and experimental time-series forecasts for four lottery games: Powerball, Mega Millions,
Washington Lotto and Hit 5. It loads each game's official draw history, runs Google Research's TimesFM
over it alongside classical frequency and gap statistics, and produces candidate lines, probability
heatmaps and backtests.

**It cannot predict the lottery, and it says so.** Drawings are independent random events. Every backtest
is shown next to what pure chance scores, and on real data the strategies land on the chance baseline.
This is a tool for analysis and entertainment. If gambling is a problem for you or someone you know, call
or text 1-800-GAMBLER or visit the [National Council on Problem Gambling](https://www.ncpgambling.org/help-treatment/).

This repository holds two things:

| Path | What it is |
| --- | --- |
| `backend/`, `web/` | The full-stack app described here: FastAPI + PostgreSQL + TimesFM, and a Next.js PWA. |
| `scripts/publish-pages.sh`, `.github/workflows/` | Rebuild the hosted site on a schedule: new draws, TimesFM forecasts, static build, publish to GitHub Pages. |
| `server.py`, `forecast.py`, `public/`, `Dockerfile` | The original single-file prototype (GitHub Pages demo and Hugging Face Space). See [the last section](#original-prototype). |

## Hosted site

The app runs on GitHub alone: **https://laminedo.github.io/lottery-timesfm/app/**

GitHub Pages can only serve files, so nothing is computed when you open the page. Instead a scheduled
GitHub Actions job ([`.github/workflows/update-site.yml`](.github/workflows/update-site.yml)) does the
server's work three times a day, after the evening draws:

1. fetches new draws and jackpot estimates from the official sources;
2. runs TimesFM on GitHub's machine for every draw not yet forecast, and recomputes the backtests over
   the last 25, 50, 100 and 200 draws;
3. rebuilds the web app as static files with that data and publishes it to the `gh-pages` branch.

What that means when you use it:

- forecasts, heatmaps and backtests are real TimesFM output, at most a few hours behind the latest draw;
  the page shows when it was last updated;
- candidate lines are sampled in your browser from the model's distribution, saved in your browser, and
  scored there once their draw is in;
- you cannot run a backtest of an arbitrary size or change the model's settings: that needs the full
  app below.

Model output from earlier runs is carried forward in a small state file published with the site
(`/_state/state.json.gz`), so each run only forecasts the new draws and takes a few minutes. If that
file is ever lost the job recomputes everything, which takes a few hours once.

To publish by hand from a machine with the app set up, run `make publish` (same script,
`scripts/publish-pages.sh`). `make demo` builds the site into `.pages-build/site` without publishing.
The original prototype stays at the site root; the app is under `/app/`.

## Run it

You need [uv](https://docs.astral.sh/uv/) and Node.js 22 or newer. (A Node 24 build may already be
unpacked in `.tools/node/`; the Makefile uses it when present.)

```bash
make install   # backend (Python 3.11, TimesFM, embedded Postgres) and web dependencies
make api       # terminal 1: http://localhost:8000  (docs at /docs)
make web       # terminal 2: http://localhost:3000
```

The first start creates a local Postgres under `backend/data/pgdata`, loads the bundled draw history
(`backend/data/seed/`, about 8,100 draws), then checks the official sources for newer draws. TimesFM's
weights (about 900 MB) download from Hugging Face the first time a forecast is computed.

Without `make`:

```bash
cd backend && uv sync --all-extras && uv run --all-extras uvicorn app.main:app --port 8000
cd web && npm install && npm run dev
```

## What it does

- **Game dashboard.** Tabs for the four games with the latest draw, a countdown to the next one, the
  advertised jackpot, and an accuracy tracker fed by the latest backtest.
- **Forecast generator.** One click produces 1, 3 or 5 candidate lines. Four presets (Balanced, Hot
  numbers, Contrarian / cold, High entropy) set how much each model contributes; sliders adjust the mix
  and the risk (temperature). A heatmap shows each number's probability under the chosen model against
  the chance baseline, and a positional chart shows TimesFM's quantile bands.
- **Backtesting.** Walk-forward over the last 25 to 200 draws: each draw is forecast from earlier draws
  only, then scored. Results come with the exact chance baseline, a confidence interval, a p-value and a
  plain-language verdict that accounts for testing several strategies at once.
- **Trends and history.** Number frequency, hot and cold numbers, odd/even and high/low splits,
  consecutive numbers and sum ranges, each beside what chance predicts; the full draw history; and every
  line you generated, scored once its draw has happened.
- **Installable.** A web app manifest and service worker make it a PWA that keeps the last-seen data
  available offline.

## How the forecast works

Lottery numbers are labels, not magnitudes, so the raw balls are never fed to the model as one line.
Two representations are built instead (`backend/app/analytics/features.py`):

- **A, per ball.** For every ball: its share of the last 10, 30 and 50 draws, exponentially weighted hit
  rates over the same spans, and the number of draws since it last appeared.
- **B, per sorted position.** The lowest, second-lowest, ... highest number of each draw, plus the draw
  sum and its moving average.

One model call forecasts all of these series (about 670 for Powerball). The quantile output is mapped
back to the pool (`backend/app/forecast/distribution.py`): each channel of A becomes an estimated hit
rate per ball; each position's nine quantiles become a discrete distribution over ball numbers, which is
summed across positions and divided by the same construction for a fair draw, so an uninformative
forecast comes out flat. The two are blended into a "TimesFM core" distribution. Lines are then sampled
without replacement from a weighted mix of that core, a recency model, an overdue model and pure chance,
with game rules enforced (`backend/app/forecast/sampler.py`).

Model output is cached in Postgres per draw, so a forecast or backtest step is only ever computed once.

## Data

| Game | Format stored | Source |
| --- | --- | --- |
| Powerball | 5 of 69 + 1 of 26, since 2015-10-07 | New York State open data (data.ny.gov) |
| Mega Millions | 5 of 70 since 2017-10-31; Mega Ball 1 of 25, then 1 of 24 from 2025-04-08 | data.ny.gov, megamillions.com |
| Lotto (WA) | 6 of 49, since 2003-10-08 | walottery.com |
| Hit 5 (WA) | 5 of 42, since 2020-08-30 | walottery.com |

Only draws under each game's current number matrix are kept, because earlier formats are not
comparable. Mega Ball statistics use only draws since the pool became 24 balls. Jackpot amounts are
stored where the source publishes them (the Washington games); for Powerball and Mega Millions the
upcoming estimate is recorded before each draw, so history fills in from now on. A missing amount is
shown as missing, never estimated.

`make refresh` pulls new draws on demand (the API also does so on startup and every six hours);
`make snapshot` rebuilds the seed files from the sources.

## Database

Set `DATABASE_URL` in `backend/.env` to use Supabase, Neon or any Postgres 14+. The schema is plain SQL
in `backend/migrations/` and is applied automatically on startup (`uv run --all-extras python -m app.cli migrate`
applies it on its own). Row level security is enabled on every table with no policies, so on Supabase the
tables are not readable through the public REST API.

With `DATABASE_URL` unset, the API starts a self-contained Postgres from `backend/data/pgdata`. That is
meant for local development and tests.

## Configuration

Everything is optional; see `backend/.env.example`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | unset | Postgres connection string. Unset uses the embedded dev server. |
| `FORECAST_BACKEND` | `auto` | `timesfm`, `smoothing`, or `auto` (TimesFM when installed). |
| `TIMESFM_DEVICE` | `auto` | `cuda`, `mps` (Apple GPU) or `cpu`. |
| `INFERENCE_URL` | unset | Run TimesFM in a separate service (below) and call it over HTTP. |
| `AUTO_REFRESH` / `REFRESH_HOURS` | `true` / `6` | Background refresh from the official sources. |
| `API_URL` (web) | `http://127.0.0.1:8000` | Where the web app proxies `/api`. |

If TimesFM is not installed the API falls back to exponential smoothing and the app labels it as such.

**Separate inference service.** `uvicorn app.inference_service:app --port 8100` exposes
`POST /predict_batch` (series in, quantiles out) and nothing else, for running the model on a GPU host or
a Cloud Run container apart from the API. `backend/Dockerfile` builds the API image with the weights
baked in; it has not been built or deployed from this repository yet.

## Tests

```bash
make test
```

- `backend/tests/` (pytest, 139 tests): draw rule validation (ranges, duplicates, bonus pools, format
  eras), feed parsers, feature engineering with a no-look-ahead check, the quantile-to-probability
  mapping, sampling, backtest arithmetic against the hypergeometric baseline, the HTTP API against a
  real Postgres, the hosted site's data against the live API, and the state carried between scheduled runs. Four tests run the real TimesFM model; skip them with `-m "not timesfm"`.
- `web/tests/` (node:test, 30 tests): the service worker's caching rules, the shared formatting and
  blend logic, and the hosted site's browser-side work: draw schedule, line sampling, saved lines and
  their scoring.

## API

Interactive docs are at `http://localhost:8000/docs`. The main routes:

| Route | Returns |
| --- | --- |
| `GET /api/games`, `/api/games/{game}` | Rules, latest draw, next draw time, jackpot estimate |
| `GET /api/games/{game}/draws` | Paginated draw history |
| `GET /api/games/{game}/metrics`, `/trends` | Frequency, gaps, hot/cold; odd/even, high/low, consecutive, sums |
| `GET /api/games/{game}/forecast` | Per-number probabilities from each model, with quantile bands |
| `POST /api/games/{game}/forecast/generate` | Candidate lines (stored and scored later) |
| `POST /api/games/{game}/backtests`, `GET /api/backtests/{id}` | Start a backtest; poll its progress and result |
| `GET /api/games/{game}/accuracy` | How stored lines and the latest backtest scored against chance |

`{game}` is one of `powerball`, `megamillions`, `wa-lotto`, `wa-hit5`.

## Original prototype

The files at the repository root are the first version: a standard-library Python server with optional
TimesFM and a single HTML page.

Live demo (browser-only, smoothing model, no TimesFM): https://laminedo.github.io/lottery-timesfm/

    .venv/bin/python server.py   # http://127.0.0.1:8044 (or python3 server.py for the fallback)

The browser-only demo reads a saved snapshot in `public/data/`. Refresh it with
`.venv/bin/python server.py snapshot` and commit: GitHub Pages serves the `gh-pages` branch, which the
scheduled job (or `make publish`) rebuilds from the repository, prototype included. The root `Dockerfile` and the front matter
at the top of this file configure the Hugging Face Space for this prototype.
