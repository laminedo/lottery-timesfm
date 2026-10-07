"""Carry computed state from one run to the next when the database itself does not persist.

The scheduled job that updates the hosted site starts from an empty database every time. Draws come
back from the seed files and the official feeds, but two things would be lost: the model output
already computed for past draws (minutes of inference each run), and the jackpot estimates captured
before each draw (which the feeds do not republish). Both are written to one gzipped JSON file after a
run and read back at the start of the next.
"""
from __future__ import annotations

import gzip
import json
from datetime import date, datetime, timezone
from pathlib import Path

from psycopg.types.json import Jsonb

from .db import Database
from .forecast.service import ForecastService

VERSION = 1
KEEP_PER_GAME = 260  # most recent model outputs kept per game: enough for the longest backtest, with room


def export_state(db: Database, service: ForecastService, path: Path, keep: int = KEEP_PER_GAME) -> dict:
    """Write model outputs for the current pipeline and all jackpot estimates. Returns counts."""
    prefix = service.pipeline_key()
    rows = db.fetch_all(
        """
        select game_key, draw_date, pipeline_key, payload from (
            select m.game_key, d.draw_date, m.pipeline_key, m.payload,
                   row_number() over (partition by m.game_key order by d.draw_date desc) as recency
            from model_outputs m join draws d on d.draw_id = m.as_of_draw_id
            where m.pipeline_key like %s
        ) ranked where recency <= %s order by game_key, draw_date
        """,
        (prefix + ":n%", keep),
    )
    outputs = [
        {"game": r["game_key"], "as_of": r["draw_date"].isoformat(), "n": int(r["pipeline_key"].rsplit(":n", 1)[1]), "payload": r["payload"]}
        for r in rows
    ]
    jackpots = [
        {"game": r["game_key"], "draw_date": r["draw_date"].isoformat(), "jackpot_usd": r["jackpot_usd"],
         "cash_value_usd": r["cash_value_usd"], "source": r["source"], "fetched_at": r["fetched_at"].isoformat()}
        for r in db.fetch_all("select * from jackpot_estimates order by game_key, draw_date")
    ]
    doc = {
        "version": VERSION,
        "pipeline_key": prefix,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_outputs": outputs,
        "jackpot_estimates": jackpots,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"))
    return {"model_outputs": len(outputs), "jackpot_estimates": len(jackpots), "bytes": path.stat().st_size}


def import_state(db: Database, service: ForecastService, path: Path) -> dict:
    """Load a state file into the database, keeping anything already there. Returns counts.

    A model output is only reused when it still describes this database: same pipeline settings, and
    the same number of draws up to its date as when it was computed. Anything else is skipped and will
    simply be recomputed.
    """
    path = Path(path)
    counts = {"model_outputs": 0, "model_outputs_skipped": 0, "jackpot_estimates": 0}
    if not path.exists():
        return counts
    with gzip.open(path, "rt", encoding="utf-8") as f:
        doc = json.load(f)
    if doc.get("version") != VERSION:
        return counts

    with db.connect() as conn:
        for j in doc.get("jackpot_estimates", []):
            cur = conn.execute(
                """
                insert into jackpot_estimates (game_key, draw_date, jackpot_usd, cash_value_usd, source, fetched_at)
                values (%s, %s, %s, %s, %s, %s) on conflict (game_key, draw_date) do nothing
                """,
                (j["game"], j["draw_date"], j["jackpot_usd"], j["cash_value_usd"], j["source"], j["fetched_at"]),
            )
            counts["jackpot_estimates"] += cur.rowcount
        conn.execute(
            """
            update draws d set jackpot_usd = e.jackpot_usd from jackpot_estimates e
            where d.game_key = e.game_key and d.draw_date = e.draw_date and d.jackpot_usd is null
            """
        )

    outputs = doc.get("model_outputs", [])
    prefix = service.pipeline_key()
    if doc.get("pipeline_key") != prefix:
        counts["model_outputs_skipped"] = len(outputs)
        return counts

    # For every stored draw: its id, and how many draws the game had up to and including it.
    position: dict[tuple[str, date], tuple[int, int]] = {}
    for r in db.fetch_all(
        """
        select d.game_key, d.draw_date, d.draw_id,
               row_number() over (partition by d.game_key order by d.draw_date) as n
        from draws d join games g using (game_key)
        """
    ):
        position[(r["game_key"], r["draw_date"])] = (r["draw_id"], r["n"])
    with db.connect() as conn:
        for o in outputs:
            found = position.get((o["game"], date.fromisoformat(o["as_of"])))
            if not found or found[1] != o["n"]:
                counts["model_outputs_skipped"] += 1
                continue
            cur = conn.execute(
                "insert into model_outputs (game_key, as_of_draw_id, pipeline_key, payload) values (%s, %s, %s, %s) "
                "on conflict (game_key, as_of_draw_id, pipeline_key) do nothing",
                (o["game"], found[0], f"{prefix}:n{o['n']}", Jsonb(o["payload"])),
            )
            counts["model_outputs"] += cur.rowcount
    return counts
