"""Load draws into Postgres: from the bundled seed files, and incrementally from the official feeds."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ..db import Database
from ..games import GAMES, DrawValidationError, Game, next_draw_at, validate_draw
from . import sources
from .sources import JackpotEstimate, RawDraw

log = logging.getLogger(__name__)


def normalize(game: Game, raw: list[RawDraw]) -> tuple[list[RawDraw], list[str]]:
    """Keep draws that belong to the game's current main matrix and pass its rules, oldest first.

    Returns (valid draws with sorted numbers, reasons for each rejected draw). Draws before the
    current format are dropped silently: they are expected, not errors.
    """
    by_date: dict[date, RawDraw] = {}
    rejected: list[str] = []
    for r in raw:
        if r.draw_date < game.main_since:
            continue
        try:
            primary, bonus = validate_draw(game, r.primary_numbers, r.bonus_number, r.draw_date)
        except DrawValidationError as e:
            rejected.append(f"{r.draw_date}: {e}")
            continue
        by_date[r.draw_date] = RawDraw(
            game.key, r.draw_date, tuple(primary), bonus, r.multiplier, r.jackpot_usd, r.source
        )
    return [by_date[d] for d in sorted(by_date)], rejected


def upsert_draws(db: Database, draws: list[RawDraw]) -> int:
    """Insert draws, or fill in fields a later fetch learned. Returns how many rows were new."""
    if not draws:
        return 0
    new = 0
    with db.connect() as conn:
        for d in draws:
            row = conn.execute(
                """
                insert into draws (game_key, draw_date, primary_numbers, bonus_number, multiplier, jackpot_usd, source)
                values (%s, %s, %s, %s, %s, %s, %s)
                on conflict (game_key, draw_date) do update set
                    primary_numbers = excluded.primary_numbers,
                    bonus_number = excluded.bonus_number,
                    multiplier = coalesce(excluded.multiplier, draws.multiplier),
                    jackpot_usd = coalesce(excluded.jackpot_usd, draws.jackpot_usd)
                returning (xmax = 0) as inserted
                """,
                (d.game_key, d.draw_date, list(d.primary_numbers), d.bonus_number, d.multiplier, d.jackpot_usd, d.source),
            ).fetchone()
            new += bool(row["inserted"])
    return new


# ---- seed files ----

def seed_path(seed_dir: Path, game: Game) -> Path:
    return seed_dir / f"{game.key}.json"


def write_seed(seed_dir: Path, game: Game, draws: list[RawDraw]) -> Path:
    """One compact JSON file per game: d=date, n=main numbers, b=bonus, m=multiplier, j=jackpot."""
    seed_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for d in draws:
        row: dict = {"d": d.draw_date.isoformat(), "n": list(d.primary_numbers)}
        if d.bonus_number is not None:
            row["b"] = d.bonus_number
        if d.multiplier is not None:
            row["m"] = d.multiplier
        if d.jackpot_usd is not None:
            row["j"] = d.jackpot_usd
        rows.append(row)
    sources_used = sorted({d.source for d in draws})
    doc = {
        "game_key": game.key,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": sources_used,
        "draws": rows,
    }
    path = seed_path(seed_dir, game)
    path.write_text(json.dumps(doc, separators=(",", ":")))
    return path


def read_seed(seed_dir: Path, game: Game) -> list[RawDraw]:
    path = seed_path(seed_dir, game)
    if not path.exists():
        return []
    doc = json.loads(path.read_text())
    source = "+".join(doc.get("sources", [])) or "seed"
    return [
        RawDraw(game.key, date.fromisoformat(r["d"]), tuple(r["n"]), r.get("b"), r.get("m"), r.get("j"), source)
        for r in doc["draws"]
    ]


def seed_game(db: Database, seed_dir: Path, game: Game) -> int:
    draws, rejected = normalize(game, read_seed(seed_dir, game))
    for reason in rejected:
        log.warning("Seed draw rejected for %s: %s", game.key, reason)
    return upsert_draws(db, draws)


def seed_if_empty(db: Database, seed_dir: Path) -> dict[str, int]:
    """Load the seed file for every game that has no draws yet."""
    counts = {r["game_key"]: r["n"] for r in db.fetch_all("select game_key, count(*) as n from draws group by 1")}
    loaded = {}
    for game in GAMES.values():
        if not counts.get(game.key):
            loaded[game.key] = seed_game(db, seed_dir, game)
            log.info("Seeded %s with %d draws", game.key, loaded[game.key])
    return loaded


# ---- official feeds ----

def fetch_history(game: Game, since: date) -> list[RawDraw]:
    """All published draws on or after `since` (WA pages are per year, so it returns whole years)."""
    if game.key in sources.NY_DATASETS:
        raw = sources.fetch_ny(game, since)
        if game.key == "megamillions":
            try:  # the official site posts results hours before the open-data feed does
                latest, _ = sources.fetch_megamillions_latest(game)
                if latest:
                    raw.append(latest)
            except Exception as e:
                log.warning("megamillions.com latest draw unavailable: %r", e)
        return raw
    years = range(since.year, date.today().year + 1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        pages = pool.map(lambda y: sources.fetch_wa_year(game, y), years)
        return [d for page in pages for d in page]


def refresh_game(db: Database, game: Game, full: bool = False) -> dict:
    """Fetch draws newer than what is stored (or everything when `full`) and upsert them."""
    latest = db.fetch_one("select max(draw_date) as d from draws where game_key = %s", (game.key,))["d"]
    # Re-read the last two weeks so late corrections and newly posted jackpots are picked up.
    since = game.main_since if full or latest is None else max(game.main_since, latest - timedelta(days=14))
    draws, rejected = normalize(game, fetch_history(game, since))
    for reason in rejected:
        log.warning("Draw rejected for %s: %s", game.key, reason)
    new = upsert_draws(db, draws)
    return {"game": game.key, "fetched": len(draws), "new": new, "rejected": len(rejected)}


def store_jackpot_estimates(db: Database, estimates: list[JackpotEstimate]) -> int:
    """Record each estimate against the next scheduled draw, and copy it onto that draw once it exists."""
    stored = 0
    with db.connect() as conn:
        for est in estimates:
            game = GAMES.get(est.game_key)
            if game is None:
                continue
            target = est.draw_date or next_draw_at(game).date()
            conn.execute(
                """
                insert into jackpot_estimates (game_key, draw_date, jackpot_usd, cash_value_usd, source)
                values (%s, %s, %s, %s, %s)
                on conflict (game_key, draw_date) do update set
                    jackpot_usd = excluded.jackpot_usd, cash_value_usd = excluded.cash_value_usd,
                    source = excluded.source, fetched_at = now()
                """,
                (game.key, target, est.jackpot_usd, est.cash_value_usd, est.source),
            )
            stored += 1
        conn.execute(
            """
            update draws d set jackpot_usd = e.jackpot_usd
            from jackpot_estimates e
            where d.game_key = e.game_key and d.draw_date = e.draw_date and d.jackpot_usd is null
            """
        )
    return stored


def refresh_jackpots(db: Database) -> int:
    estimates: dict[str, JackpotEstimate] = {}
    try:
        for est in sources.fetch_wa_jackpots():
            estimates[est.game_key] = est
    except Exception as e:
        log.warning("walottery.com jackpots unavailable: %r", e)
    try:
        _, est = sources.fetch_megamillions_latest(GAMES["megamillions"])
        if est:
            estimates[est.game_key] = est
    except Exception as e:
        log.warning("megamillions.com jackpot unavailable: %r", e)
    return store_jackpot_estimates(db, list(estimates.values()))


def refresh_all(db: Database, full: bool = False) -> list[dict]:
    """Refresh every game. A feed that is down is reported, not raised, so the others still update."""
    results = []
    for game in GAMES.values():
        try:
            results.append(refresh_game(db, game, full=full))
        except Exception as e:
            log.warning("Refresh failed for %s: %r", game.key, e)
            results.append({"game": game.key, "error": str(e)})
    try:
        refresh_jackpots(db)
    except Exception as e:
        log.warning("Jackpot refresh failed: %r", e)
    return results
