#!/usr/bin/env python3
"""Lottery x TimesFM web app. Standard library only; TimesFM is optional."""
import argparse, json, mimetypes, random
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import forecast

PUBLIC = Path(__file__).parent / "public"


# Current formats. `src`: public open-data feed (data.ny.gov) + first date of the current format.
GAMES = {
    "powerball": {"name": "Powerball", "max": 69, "pick": 5, "bonus": 26, "bonus_name": "Powerball",
                  "src": ("d6yy-54nr", "2015-10-07", None)},
    "megamillions": {"name": "Mega Millions", "max": 70, "pick": 5, "bonus": 24, "bonus_name": "Mega Ball",
                     "src": ("5xaw-6ayf", "2025-04-08", "mega_ball")},
    "wa-hit5": {"name": "WA Hit 5", "max": 35, "pick": 5, "bonus": 0},
    "wa-lotto": {"name": "WA Lotto", "max": 49, "pick": 6, "bonus": 0},
}


def parse_draws(text, g):
    """Each line: `pick` main numbers, then the bonus number if the game has one."""
    need = g["pick"] + (1 if g["bonus"] else 0)
    mains, bonuses = [], []
    for line in text.splitlines():
        nums = [int(x) for x in line.replace(",", " ").replace(";", " ").split() if x.isdigit()]
        if len(nums) < need:
            continue
        main = nums[:g["pick"]]
        if not all(1 <= n <= g["max"] for n in main):
            continue
        if g["bonus"]:
            if not 1 <= nums[g["pick"]] <= g["bonus"]:
                continue
            bonuses.append([nums[g["pick"]]])
        mains.append(main)
    return mains, bonuses


def fetch_history(key):
    import urllib.request
    res, since, ball = GAMES[key]["src"]
    url = f"https://data.ny.gov/resource/{res}.json?$limit=5000&$order=draw_date&$where=draw_date>='{since}'"
    with urllib.request.urlopen(url, timeout=20) as r:
        rows = json.load(r)
    return [(row["winning_numbers"] + (" " + row[ball] if ball else "")).replace("  ", " ") for row in rows]


class H(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/status"):
            return self._json({"backend": forecast.backend()})
        if self.path.startswith("/api/games"):
            return self._json({k: {a: b for a, b in v.items() if a != "src"} | {"history": "src" in v}
                               for k, v in GAMES.items()})
        if self.path.startswith("/api/history/"):
            key = self.path.split("/")[-1].split("?")[0]
            if key not in GAMES or "src" not in GAMES[key]:
                return self._json({"error": "No official feed for this game; paste results instead."}, 404)
            try:
                return self._json({"lines": fetch_history(key)})
            except Exception as e:
                return self._json({"error": f"Could not fetch history: {e}"}, 502)
        if self.path.startswith("/api/sample/"):
            g = GAMES.get(self.path.split("/")[-1].split("?")[0])
            if not g:
                return self.send_error(404)
            rows = [sorted(r.sample(range(1, g["max"] + 1), g["pick"])) for r in [random.Random()] for _ in range(200)]
            return self._json({"lines": [" ".join(map(str, d)) + (f" {random.randint(1, g['bonus'])}" if g["bonus"] else "") for d in rows]})
        p = "index.html" if self.path in ("/", "") else self.path.lstrip("/").split("?")[0]
        f = (PUBLIC / p).resolve()
        if PUBLIC.resolve() not in f.parents or not f.is_file():
            self.send_error(404)
            return
        data = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(f.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/api/forecast":
            return self.send_error(404)
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            g = GAMES[req["game"]]
            maxnum, pick = g["max"], g["pick"]
            draws, bonuses = parse_draws(req["draws"], g)
            if len(draws) < forecast.WINDOW + 10:
                raise ValueError(f"Need at least {forecast.WINDOW + 10} valid draws, got {len(draws)}. "
                                 f"Each line needs {pick} numbers" + (" plus the bonus ball." if g["bonus"] else "."))
            res = forecast.suggest(draws, maxnum, pick)
            if g["bonus"]:
                b = forecast.suggest(bonuses, g["bonus"], 1)
                res["bonus"] = {"name": g["bonus_name"], "number": b["numbers"][0], "scores": b["scores"]}
            res["backtest"] = forecast.backtest(draws, maxnum, pick) if req.get("backtest") else None
            res["draw_count"] = len(draws)
            self._json(res)
        except Exception as e:
            self._json({"error": str(e)}, 400)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8044)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    print(f"Forecast backend: {forecast.backend()}")
    print(f"http://{a.host}:{a.port}")
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()
