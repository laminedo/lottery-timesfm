#!/usr/bin/env python3
"""Lottery x TimesFM web app. Standard library only; TimesFM is optional."""
import argparse, json, mimetypes, re, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import forecast

PUBLIC = Path(__file__).parent / "public"


# Current formats. `src`: where official results come from, limited to draws in the current format.
#   ("ny", dataset, first_date, bonus_field)  -> data.ny.gov open data
#   ("wa", gamename, first_year)              -> walottery.com past-drawings pages
GAMES = {
    "powerball": {"name": "Powerball", "max": 69, "pick": 5, "bonus": 26, "bonus_name": "Powerball",
                  "src": ("ny", "d6yy-54nr", "2015-10-07", None)},
    "megamillions": {"name": "Mega Millions", "max": 70, "pick": 5, "bonus": 24, "bonus_name": "Mega Ball",
                     "src": ("ny", "5xaw-6ayf", "2025-04-08", "mega_ball")},
    "wa-hit5": {"name": "WA Hit 5", "max": 42, "pick": 5, "bonus": 0, "src": ("wa", "hit5", 2022)},
    "wa-lotto": {"name": "WA Lotto", "max": 49, "pick": 6, "bonus": 0, "src": ("wa", "lotto", 2020)},
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


def _get(url):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "ignore")


def _wa_year(game, year):
    """One year of results from walottery.com, newest first, as lists of ints."""
    page = _get(f"https://www.walottery.com/WinningNumbers/PastDrawings.aspx?gamename={game}&unittype=year&unitcount={year}")
    out = []
    for t in re.finditer(r'<table class="table-viewport-small">(.*?)</table>', page, re.S):
        balls = re.search(r'game-balls">(.*?)</ul>', t.group(1), re.S)
        if balls:
            out.append(re.findall(r"<li[^>]*>\s*(\d+)\s*</li>", balls.group(1)))
    return out


_cache = {}  # game -> (fetched_at, lines)


def fetch_history(key):
    """Official draws, oldest first, one 'n n n ...' line per draw. Cached for an hour."""
    if key in _cache and time.time() - _cache[key][0] < 3600:
        return _cache[key][1]
    src = GAMES[key]["src"]
    if src[0] == "ny":
        _, res, since, ball = src
        rows = json.loads(_get(f"https://data.ny.gov/resource/{res}.json?$limit=5000&$order=draw_date"
                               f"&$where=draw_date%3E=%27{since}%27"))
        lines = [" ".join((row["winning_numbers"] + (" " + row[ball] if ball else "")).split()) for row in rows]
    else:
        _, game, first = src
        lines = []
        for y in range(first, time.gmtime().tm_year + 1):
            lines += [" ".join(d) for d in reversed(_wa_year(game, y))]
    if not lines:
        raise ValueError("no draws found")
    _cache[key] = (time.time(), lines)
    return lines


def snapshot():
    """Save draw history to public/data/ so the browser-only (GitHub Pages) version has it."""
    out = PUBLIC / "data"
    out.mkdir(exist_ok=True)
    for key in GAMES:
        lines = fetch_history(key)
        (out / f"{key}.json").write_text(json.dumps({"updated": time.strftime("%Y-%m-%d"), "lines": lines}))
        print(key, len(lines), "draws")


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
    ap.add_argument("command", nargs="?", choices=["snapshot"])
    a = ap.parse_args()
    if a.command == "snapshot":
        snapshot()
        raise SystemExit
    print(f"Forecast backend: {forecast.backend()}")
    print(f"http://{a.host}:{a.port}")
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()
