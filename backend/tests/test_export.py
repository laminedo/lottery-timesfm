"""The static snapshot must say exactly what the live API says."""
import json

import pytest
from fastapi.testclient import TestClient

from app.export import export_static
from app.forecast.backends import SmoothingBackend
from app.games import GAMES
from app.ingest import pipeline
from app.main import State, create_app

from .conftest import synthetic_draws


@pytest.fixture
def exported(db, settings, tmp_path):
    for i, game in enumerate(GAMES.values()):
        pipeline.upsert_draws(db, synthetic_draws(game, 70, seed=i))
    state = State(settings, db=db, backend=SmoothingBackend())
    out = tmp_path / "data"
    (out / "stale").mkdir(parents=True)
    (out / "stale" / "old.json").write_text("{}")
    summary = export_static(db, state.service, out, backtest_draws=(10, 20), featured=20, log=lambda _: None)
    with TestClient(create_app(settings, state)) as client:
        yield out, summary, client
    state.backtests.shutdown()


def load(path):
    return json.loads(path.read_text())


def test_export_replaces_the_directory_and_writes_every_file(exported):
    out, summary, _ = exported
    assert not (out / "stale").exists()
    per_game = {"game.json", "draws.json", "metrics.json", "trends.json", "forecast.json", "backtests.json", "accuracy.json"}
    for key in GAMES:
        assert {p.name for p in (out / key).iterdir()} == per_game
    assert len(list((out / "backtests").iterdir())) == 8  # two sizes for each of four games
    assert summary["files"] == len(list(out.rglob("*.json")))
    health = load(out / "health.json")
    assert health["static"] is True and health["backend"]["name"] == "smoothing"
    assert health["draws"] == {key: 70 for key in GAMES}


@pytest.mark.parametrize("key", list(GAMES))
def test_snapshot_matches_the_live_api(exported, key):
    out, _, client = exported
    api = lambda path: client.get(f"/api/games/{key}{path}").json()  # noqa: E731
    assert load(out / key / "game.json") == api("")
    assert load(out / key / "metrics.json") == api("/metrics")
    assert load(out / key / "trends.json") == api("/trends?window=500")
    snapshot, live = load(out / key / "forecast.json"), api("/forecast")
    assert snapshot["main"] == live["main"] and snapshot["bonus"] == live["bonus"]
    draws = load(out / key / "draws.json")
    assert draws["total"] == 70 and draws["draws"][:10] == api("/draws?limit=10")["draws"]


def test_backtests_are_precomputed_with_the_featured_size_first(exported):
    out, _, client = exported
    runs = load(out / "powerball" / "backtests.json")
    assert [r["params"]["draws"] for r in runs] == [20, 10]
    assert all(r["status"] == "done" and "result" not in r and r["summary"]["draws"] == r["params"]["draws"] for r in runs)
    full = load(out / "backtests" / f"{runs[0]['run_id']}.json")
    assert full["result"]["draws"] == 20 and len(full["result"]["timeline"]) == 20
    # Same numbers as a live run with the same settings.
    live_id = client.post("/api/games/powerball/backtests", json={"draws": 20}).json()["run_id"]
    while (live := client.get(f"/api/backtests/{live_id}").json())["status"] not in ("done", "failed"):
        pass
    assert live["result"]["strategies"] == full["result"]["strategies"]
    ids = [load(out / key / "backtests.json")[0]["run_id"] for key in GAMES]
    assert len(set(ids)) == 4  # run ids are unique across games


def test_accuracy_reports_the_featured_backtest_and_no_saved_lines(exported):
    out, _, _ = exported
    acc = load(out / "wa-hit5" / "accuracy.json")
    assert acc["backtest"]["draws"] == 20 and acc["live"]["scored_lines"] == 0
    assert acc["expected_matches"] == pytest.approx(25 / 42)
    assert acc["backtest"]["run_id"] == load(out / "wa-hit5" / "backtests.json")[0]["run_id"]


def test_featured_size_must_be_exported(db, settings, tmp_path):
    state = State(settings, db=db, backend=SmoothingBackend())
    with pytest.raises(ValueError, match="must be one of"):
        export_static(db, state.service, tmp_path / "x", backtest_draws=(10,), featured=100)
    state.backtests.shutdown()
