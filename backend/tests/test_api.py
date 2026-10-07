"""Integration tests: the HTTP API against a real Postgres, with the fast smoothing backend."""
import time
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.forecast.backends import SmoothingBackend
from app.forecast.backtest import match_moments
from app.games import GAMES, next_draw_at, validate_line
from app.ingest import pipeline
from app.ingest.sources import JackpotEstimate, RawDraw
from app.main import State, create_app

from .conftest import synthetic_draws

DRAWS_PER_GAME = 90


@pytest.fixture
def client(db, settings):
    for i, game in enumerate(GAMES.values()):
        pipeline.upsert_draws(db, synthetic_draws(game, DRAWS_PER_GAME, seed=i))
    state = State(settings, db=db, backend=SmoothingBackend())
    with TestClient(create_app(settings, state)) as c:
        c.state = state
        yield c
    state.backtests.shutdown()


def wait_for_run(client, run_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/backtests/{run_id}").json()
        if run["status"] in ("done", "failed"):
            return run
        time.sleep(0.1)
    raise AssertionError(f"backtest {run_id} did not finish: {run}")


def test_health_reports_backend_data_and_the_disclaimer(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["backend"]["name"] == "smoothing"
    assert body["draws"] == {key: DRAWS_PER_GAME for key in sorted(GAMES)}
    assert "independent random events" in body["disclaimer"]
    assert body["help"]["phone"] == "1-800-GAMBLER"


def test_games_list_has_rules_latest_draw_and_a_future_next_draw(client):
    games = client.get("/api/games").json()
    assert [g["key"] for g in games] == ["powerball", "megamillions", "wa-lotto", "wa-hit5"]
    pb = games[0]
    assert (pb["pick"], pb["pool"], pb["bonus_pool"], pb["jackpot_odds"]) == (5, 69, 26, 292_201_338)
    assert pb["draw_count"] == DRAWS_PER_GAME and len(pb["latest_draw"]["primary_numbers"]) == 5
    assert pb["next_jackpot"] is None  # none stored yet: reported as unknown, not invented
    for g in games:
        assert datetime.fromisoformat(g["next_draw_at"]) > datetime.now().astimezone()


def test_next_jackpot_appears_once_an_estimate_is_stored(client, db):
    target = next_draw_at(GAMES["powerball"]).date()
    pipeline.store_jackpot_estimates(db, [JackpotEstimate("powerball", 485_000_000, 199_800_000, "walottery.com", target)])
    jackpot = client.get("/api/games/powerball").json()["next_jackpot"]
    assert (jackpot["jackpot_usd"], jackpot["cash_value_usd"], jackpot["draw_date"]) == (485_000_000, 199_800_000, target.isoformat())


def test_unknown_game_is_404(client):
    for path in ("/api/games/keno", "/api/games/keno/draws", "/api/games/keno/forecast"):
        r = client.get(path)
        assert r.status_code == 404 and "Unknown game" in r.json()["detail"]


def test_draws_are_paginated_newest_first(client):
    page1 = client.get("/api/games/wa-hit5/draws", params={"limit": 10}).json()
    page2 = client.get("/api/games/wa-hit5/draws", params={"limit": 10, "offset": 10}).json()
    assert page1["total"] == DRAWS_PER_GAME and len(page1["draws"]) == len(page2["draws"]) == 10
    dates = [d["draw_date"] for d in page1["draws"] + page2["draws"]]
    assert dates == sorted(dates, reverse=True) and len(set(dates)) == 20
    assert client.get("/api/games/wa-hit5/draws", params={"limit": 0}).status_code == 422


def test_metrics_and_trends(client):
    m = client.get("/api/games/megamillions/metrics").json()
    assert m["main"]["draws"] == DRAWS_PER_GAME and len(m["main"]["numbers"]) == 70
    assert sum(n["count"] for n in m["main"]["numbers"]) == DRAWS_PER_GAME * 5
    assert len(m["bonus"]["numbers"]) == 24 and len(m["main"]["hot"]) == 10
    t = client.get("/api/games/wa-lotto/trends", params={"window": 30}).json()
    assert len(t["series"]) == 30 and t["sums"]["expected_mean"] == 150
    assert len(t["odd_even"]["distribution"]) == 7  # 0..6 odd numbers
    assert client.get("/api/games/wa-lotto/metrics").json()["bonus"] is None


def test_forecast_distribution_shape(client):
    f = client.get("/api/games/powerball/forecast").json()
    assert f["backend"]["name"] == "smoothing" and "disclaimer" in f
    assert f["main"]["baseline"] == pytest.approx(5 / 69)
    for model in ("timesfm", "hot", "cold"):
        assert sum(n[model] for n in f["main"]["numbers"]) == pytest.approx(5, abs=1e-3)
        assert sum(n[model] for n in f["bonus"]["numbers"]) == pytest.approx(1, abs=1e-3)
    assert [p["position"] for p in f["main"]["positions"]] == [1, 2, 3, 4, 5]
    assert f["main"]["positions"][0]["expected"] == pytest.approx(70 / 6)
    assert set(f["strategies"]) == {"balanced", "hot", "cold", "entropy"}
    assert f["as_of"]["draw_date"] < f["target_draw_at"][:10]


def test_model_output_is_cached_per_draw(client, db):
    client.get("/api/games/wa-hit5/forecast")
    client.get("/api/games/wa-hit5/forecast")
    assert db.fetch_one("select count(*) as n from model_outputs where game_key = 'wa-hit5'")["n"] == 1


@pytest.mark.parametrize("key", list(GAMES))
def test_generate_returns_valid_lines_and_stores_them(client, db, key):
    game = GAMES[key]
    r = client.post(f"/api/games/{key}/forecast/generate", json={"lines": 5, "strategy": "hot", "seed": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["lines"]) == 5 and body["strategy"] == "hot" and body["jackpot_odds"] == game.jackpot_odds
    for line in body["lines"]:
        assert validate_line(game, line["primary_numbers"], line["bonus_number"]) == (line["primary_numbers"], line["bonus_number"])
        assert line["sum"] == sum(line["primary_numbers"])
    stored = db.fetch_all("select primary_numbers, bonus_number from forecast_lines where forecast_id = %s order by line_no", (body["forecast_id"],))
    assert [(s["primary_numbers"], s["bonus_number"]) for s in stored] == [(ln["primary_numbers"], ln["bonus_number"]) for ln in body["lines"]]
    assert body["target_draw_at"][:10] == next_draw_at(game).date().isoformat()


def test_generate_is_reproducible_by_seed_and_accepts_custom_weights(client):
    post = lambda body: client.post("/api/games/powerball/forecast/generate", json=body).json()  # noqa: E731
    a, b, c = post({"lines": 3, "seed": 5}), post({"lines": 3, "seed": 5}), post({"lines": 3, "seed": 6})
    assert a["lines"] == b["lines"] != c["lines"]
    custom = post({"lines": 1, "weights": {"hot": 3, "cold": 1}, "temperature": 2.0})
    assert custom["strategy"] == "custom" and custom["weights"] == {"timesfm": 0, "hot": 0.75, "cold": 0.25, "uniform": 0}
    assert isinstance(custom["seed"], int)


@pytest.mark.parametrize(
    "body",
    [{"lines": 0}, {"lines": 11}, {"strategy": "lucky"}, {"temperature": 0}, {"weights": {"lucky": 1}}, {"weights": {"hot": 0}}],
)
def test_generate_rejects_bad_requests(client, body):
    assert client.post("/api/games/powerball/forecast/generate", json=body).status_code == 422


def test_stored_lines_are_scored_when_their_draw_arrives(client, db):
    game = GAMES["wa-hit5"]
    body = client.post("/api/games/wa-hit5/forecast/generate", json={"lines": 3, "seed": 2}).json()
    before = client.get("/api/games/wa-hit5/accuracy").json()
    assert before["live"] == {"scored_lines": 0, "pending_lines": 3, "mean_matches": None, "by_strategy": before["live"]["by_strategy"]}
    assert client.state.service.evaluate_pending() == 0  # the target draw has not happened

    # The draw comes in sharing exactly three numbers with the first line.
    first = body["lines"][0]["primary_numbers"]
    others = [n for n in range(1, 43) if n not in first]
    actual = tuple(sorted(first[:3] + others[:2]))
    target = next_draw_at(game).date()
    pipeline.upsert_draws(db, [RawDraw(game.key, target, actual, source="test")])
    assert client.state.service.evaluate_pending() == 3
    assert client.state.service.evaluate_pending() == 0  # scored once only

    history = client.get("/api/games/wa-hit5/forecasts").json()
    assert history[0]["forecast_id"] == body["forecast_id"] and history[0]["draw"]["primary_numbers"] == list(actual)
    lines = history[0]["lines"]
    assert lines[0]["main_matches"] == 3 and all(ln["scored"] for ln in lines)
    for stored, generated in zip(lines, body["lines"]):
        assert stored["main_matches"] == len(set(generated["primary_numbers"]) & set(actual))
    after = client.get("/api/games/wa-hit5/accuracy").json()
    assert after["live"]["scored_lines"] == 3 and after["live"]["pending_lines"] == 0
    assert after["live"]["mean_matches"] == pytest.approx(sum(ln["main_matches"] for ln in lines) / 3)
    assert after["expected_matches"] == pytest.approx(25 / 42)


def test_backtest_runs_in_the_background_and_reports_against_chance(client, db):
    r = client.post("/api/games/powerball/backtests", json={"draws": 30, "samples": 5, "seed": 3})
    assert r.status_code == 202 and r.json()["status"] in ("queued", "running", "done")
    run = wait_for_run(client, r.json()["run_id"])
    assert run["status"] == "done", run["error"]
    result = run["result"]
    mu, _ = match_moments(69, 5)
    assert result["draws"] == 30 and result["baseline"]["expected_matches"] == pytest.approx(mu)
    assert [s["key"] for s in result["strategies"]] == ["balanced", "hot", "cold", "entropy"]
    for s in result["strategies"]:
        assert sum(s["top_pick"]["histogram"]) == 30 and 0 <= s["top_pick"]["mean_matches"] <= 5
        assert s["bonus"]["scored_draws"] == 30
    assert len(result["timeline"]) == 30

    # The tested draws are the last 30, each forecast from the draws before it.
    dates = [d["draw_date"] for d in client.get("/api/games/powerball/draws", params={"limit": 30}).json()["draws"]]
    assert [row["date"] for row in result["timeline"]] == dates[::-1]
    assert db.fetch_one("select count(*) as n from model_outputs where game_key = 'powerball'")["n"] == 30

    listed = client.get("/api/games/powerball/backtests").json()
    assert listed[0]["run_id"] == run["run_id"] and "result" not in listed[0]
    assert listed[0]["summary"]["draws"] == 30
    assert client.get("/api/games/powerball/accuracy").json()["backtest"]["run_id"] == run["run_id"]


def test_backtest_reuses_cached_model_output(client):
    first = wait_for_run(client, client.post("/api/games/wa-hit5/backtests", json={"draws": 20, "samples": 0}).json()["run_id"])
    second = wait_for_run(client, client.post("/api/games/wa-hit5/backtests", json={"draws": 20, "samples": 0}).json()["run_id"])
    assert first["result"]["cached_steps"] == 0 and second["result"]["cached_steps"] == 20
    assert first["result"]["strategies"] == second["result"]["strategies"]


def test_backtest_validation_and_missing_run(client):
    assert client.post("/api/games/powerball/backtests", json={"draws": 5}).status_code == 422
    assert client.post("/api/games/powerball/backtests", json={"strategies": []}).status_code == 422
    assert client.post("/api/games/powerball/backtests", json={"strategies": ["lucky"]}).status_code == 422
    assert client.get("/api/backtests/999999").status_code == 404


def test_game_without_enough_history_reports_a_conflict(client, db):
    db.execute("delete from draws where game_key = 'wa-lotto' and draw_date > (select min(draw_date) + 14 from draws where game_key = 'wa-lotto')")
    r = client.get("/api/games/wa-lotto/forecast")
    assert r.status_code == 409 and "needs at least" in r.json()["detail"]
    assert client.post("/api/games/wa-lotto/forecast/generate", json={}).status_code == 409


def test_inference_service_round_trip():
    from app.inference_service import create_app as create_inference_app

    with TestClient(create_inference_app(SmoothingBackend())) as c:
        assert c.get("/health").json()["backend"]["name"] == "smoothing"
        r = c.post("/predict_batch", json={"series": [[1, 2, 3, 4, 5], [0.1] * 40], "horizon": 3})
        q = r.json()["quantiles"]
        assert len(q) == 2 and len(q[0]) == 3 and len(q[0][0]) == 10
        assert c.post("/predict_batch", json={"series": [[]], "horizon": 3}).status_code == 422
        assert c.post("/predict_batch", json={"series": [[1.0]], "horizon": 1000}).status_code == 422
