"""Shapes database rows into the JSON the API returns. Shared by the HTTP routes and the static export."""
from __future__ import annotations

from .db import Database
from .games import Game, next_draw_at


def draw_row(r: dict) -> dict:
    return {
        "draw_id": r["draw_id"],
        "game_key": r["game_key"],
        "draw_date": r["draw_date"].isoformat(),
        "primary_numbers": r["primary_numbers"],
        "bonus_number": r["bonus_number"],
        "multiplier": r["multiplier"],
        "jackpot_usd": r["jackpot_usd"],
    }


def game_summary(db: Database, game: Game) -> dict:
    stats = db.fetch_one(
        "select count(*) as n, min(draw_date) as first, max(draw_date) as last from draws "
        "where game_key = %s and draw_date >= %s",
        (game.key, game.main_since),
    )
    latest = db.fetch_one(
        "select * from draws where game_key = %s order by draw_date desc limit 1", (game.key,)
    )
    upcoming = next_draw_at(game)
    jackpot = db.fetch_one(
        "select draw_date, jackpot_usd, cash_value_usd, source, fetched_at from jackpot_estimates "
        "where game_key = %s and draw_date >= %s order by draw_date limit 1",
        (game.key, upcoming.date()),
    )
    return {
        **game.to_dict(),
        "draw_count": stats["n"],
        "first_draw_date": stats["first"].isoformat() if stats["first"] else None,
        "latest_draw": draw_row(latest) if latest else None,
        "next_draw_at": upcoming.isoformat(),
        "next_jackpot": jackpot
        and {
            "draw_date": jackpot["draw_date"].isoformat(),
            "jackpot_usd": jackpot["jackpot_usd"],
            "cash_value_usd": jackpot["cash_value_usd"],
            "source": jackpot["source"],
            "fetched_at": jackpot["fetched_at"].isoformat(),
        },
    }


def run_row(r: dict, with_result: bool) -> dict:
    out = {
        "run_id": r["run_id"],
        "game": r["game_key"],
        "status": r["status"],
        "progress": r["progress"],
        "message": r["message"],
        "error": r["error"],
        "params": r["params"],
        "created_at": r["created_at"].isoformat(),
        "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
    }
    if with_result:
        out["result"] = r["result"]
    elif r["result"]:
        out["summary"] = {
            "draws": r["result"]["draws"],
            "from": r["result"]["from"],
            "to": r["result"]["to"],
            "expected_matches": r["result"]["baseline"]["expected_matches"],
            "strategies": [
                {"key": x["key"], "label": x["label"], "mean_matches": x["top_pick"]["mean_matches"], "p_value": x["top_pick"]["p_value"]}
                for x in r["result"]["strategies"]
            ],
        }
    return out
