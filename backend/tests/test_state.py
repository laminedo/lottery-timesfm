"""State that survives between runs of the scheduled job: model output and jackpot estimates."""
import gzip
import json

import pytest

from app import state
from app.forecast.backends import SmoothingBackend
from app.forecast.service import ForecastService
from app.games import GAMES, next_draw_at
from app.ingest import pipeline
from app.ingest.sources import JackpotEstimate

from .conftest import synthetic_draws

HIT5, PB = GAMES["wa-hit5"], GAMES["powerball"]


@pytest.fixture
def service(db, settings):
    for i, game in enumerate((HIT5, PB)):
        pipeline.upsert_draws(db, synthetic_draws(game, 60, seed=i))
    return ForecastService(db, SmoothingBackend(), settings)


def wipe_computed(db):
    db.execute("truncate model_outputs, jackpot_estimates")


def test_round_trip_restores_model_output_so_nothing_is_recomputed(db, service, tmp_path):
    first = service.backtest(HIT5, draws=20, samples=0)
    service.backtest(PB, draws=10, samples=0)
    path = tmp_path / "nested" / "state.json.gz"
    exported = state.export_state(db, service, path)
    assert exported["model_outputs"] == 30 and exported["bytes"] == path.stat().st_size

    wipe_computed(db)
    assert state.import_state(db, service, path) == {"model_outputs": 30, "model_outputs_skipped": 0, "jackpot_estimates": 0}
    again = service.backtest(HIT5, draws=20, samples=0)
    assert again["cached_steps"] == 20 and again["strategies"] == first["strategies"]
    # Importing twice changes nothing.
    assert state.import_state(db, service, path)["model_outputs"] == 0


def test_export_keeps_only_the_most_recent_outputs_per_game(db, service, tmp_path):
    service.backtest(HIT5, draws=20, samples=0)
    path = tmp_path / "state.json.gz"
    assert state.export_state(db, service, path, keep=5)["model_outputs"] == 5
    with gzip.open(path, "rt") as f:
        doc = json.load(f)
    assert [o["n"] for o in doc["model_outputs"]] == [55, 56, 57, 58, 59]  # forecasts for the last five draws


def test_outputs_from_other_settings_are_not_reused(db, service, tmp_path, settings):
    service.backtest(HIT5, draws=10, samples=0)
    path = tmp_path / "state.json.gz"
    state.export_state(db, service, path)
    wipe_computed(db)
    other = ForecastService(db, SmoothingBackend(), settings.model_copy(update={"timesfm_context": 256}))
    assert other.pipeline_key() != service.pipeline_key()
    assert state.import_state(db, other, path)["model_outputs_skipped"] == 10
    assert db.fetch_one("select count(*) as n from model_outputs")["n"] == 0


def test_outputs_are_skipped_when_the_history_before_them_changed(db, service, tmp_path):
    service.backtest(HIT5, draws=10, samples=0)
    path = tmp_path / "state.json.gz"
    state.export_state(db, service, path)
    wipe_computed(db)
    # An early draw disappears: every stored output now describes a different history.
    db.execute("delete from draws where game_key = 'wa-hit5' and draw_date = (select min(draw_date) from draws where game_key = 'wa-hit5')")
    counts = state.import_state(db, service, path)
    assert counts["model_outputs"] == 0 and counts["model_outputs_skipped"] == 10


def test_jackpot_estimates_survive_and_fill_in_the_draw(db, service, tmp_path):
    target = next_draw_at(PB).date()
    pipeline.store_jackpot_estimates(db, [JackpotEstimate("powerball", 485_000_000, 199_800_000, "walottery.com", target)])
    path = tmp_path / "state.json.gz"
    assert state.export_state(db, service, path)["jackpot_estimates"] == 1
    wipe_computed(db)
    # Next run: the draw has happened and been ingested, but the feed carries no jackpot for it.
    pipeline.upsert_draws(db, synthetic_draws(PB, 1, seed=9, end=target))
    assert state.import_state(db, service, path)["jackpot_estimates"] == 1
    assert db.fetch_one("select jackpot_usd from draws where game_key = 'powerball' and draw_date = %s", (target,))["jackpot_usd"] == 485_000_000


def test_missing_or_foreign_files_are_ignored(db, service, tmp_path):
    empty = {"model_outputs": 0, "model_outputs_skipped": 0, "jackpot_estimates": 0}
    assert state.import_state(db, service, tmp_path / "absent.json.gz") == empty
    odd = tmp_path / "odd.json.gz"
    with gzip.open(odd, "wt") as f:
        json.dump({"version": 99, "model_outputs": [{"game": "wa-hit5"}]}, f)
    assert state.import_state(db, service, odd) == empty
