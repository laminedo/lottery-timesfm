"""Maintenance commands: python -m app.cli <command>.

  migrate              apply SQL migrations
  seed                 load the bundled seed files into the database
  snapshot             rebuild the seed files from the official sources (full history)
  refresh [--full]     pull new draws (or all draws) from the official sources
  warm [--draws N]     precompute model output for the last N draws of every game
  backtest GAME        run a walk-forward backtest and print the summary
  export-static DIR    write the JSON snapshot the hosted site (GitHub Pages) is built from
  export-state FILE    save computed model output and jackpot estimates for the next run
  import-state FILE    load them back into a fresh database (a missing file is not an error)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import get_settings
from .db import Database
from .forecast.backends import make_backend
from .forecast.service import ForecastService
from .games import GAMES
from .ingest import pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    sub.add_parser("seed")
    sub.add_parser("snapshot")
    sub.add_parser("refresh").add_argument("--full", action="store_true")
    sub.add_parser("warm").add_argument("--draws", type=int, default=100)
    bt = sub.add_parser("backtest")
    bt.add_argument("game", choices=list(GAMES))
    bt.add_argument("--draws", type=int, default=100)
    bt.add_argument("--samples", type=int, default=20)
    bt.add_argument("--seed", type=int, default=0)
    sub.add_parser("export-static").add_argument("out_dir", type=Path)
    sub.add_parser("export-state").add_argument("file", type=Path)
    sub.add_parser("import-state").add_argument("file", type=Path)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = get_settings()

    if args.command == "snapshot":  # needs the network, not the database
        for game in GAMES.values():
            draws, rejected = pipeline.normalize(game, pipeline.fetch_history(game, game.main_since))
            path = pipeline.write_seed(settings.seed_dir, game, draws)
            print(f"{game.key}: {len(draws)} draws {draws[0].draw_date}..{draws[-1].draw_date} -> {path}")
            for reason in rejected:
                print(f"  rejected {reason}", file=sys.stderr)
        return 0

    db = Database.from_settings(settings)
    try:
        applied = db.migrate()
        if args.command == "migrate":
            print("Applied:", ", ".join(applied) or "nothing new")
        elif args.command == "seed":
            for game in GAMES.values():
                print(f"{game.key}: {pipeline.seed_game(db, settings.seed_dir, game)} new draws")
        elif args.command == "refresh":
            # Start from the bundled history, so a fresh database only has to fetch what is newer.
            pipeline.seed_if_empty(db, settings.seed_dir)
            for game in GAMES.values():
                print(pipeline.refresh_game(db, game, full=args.full))
            print("jackpot estimates stored:", pipeline.refresh_jackpots(db))
        else:
            pipeline.seed_if_empty(db, settings.seed_dir)
            service = ForecastService(db, make_backend(settings), settings)
            if args.command in ("export-state", "import-state"):
                from . import state

                run = state.export_state if args.command == "export-state" else state.import_state
                print(f"{args.command} {args.file}: {run(db, service, args.file)}")
            elif args.command == "export-static":
                from .export import export_static

                summary = export_static(db, service, args.out_dir)
                print(f"Wrote {summary['files']} files to {summary['out_dir']} (draws up to {summary['latest_draws']})")
            elif args.command == "warm":
                for game in GAMES.values():
                    service.backtest(game, draws=args.draws, samples=0, progress=lambda f, m: print(f"\r{game.key}: {m}   ", end=""))
                    gf = service.features(game)
                    service.core(gf, len(gf.history))
                    print(f"\r{game.key}: cached {args.draws} draws and the next-draw forecast" + " " * 20)
            else:
                result = service.backtest(
                    GAMES[args.game], draws=args.draws, samples=args.samples, seed=args.seed,
                    progress=lambda f, m: print(f"\r{m}   ", end="", file=sys.stderr),
                )
                print(file=sys.stderr)
                result.pop("timeline")
                print(json.dumps(result, indent=2))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
