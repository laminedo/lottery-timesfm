"""Official result feeds, and pure parsers that turn their payloads into draw records.

- Powerball, Mega Millions: New York State open data (data.ny.gov), one JSON row per drawing.
- Mega Millions latest draw and next jackpot: megamillions.com.
- WA Lotto, Hit 5: walottery.com past-drawings pages, one HTML page per year.
- Next-draw jackpots for all four games: walottery.com winning-numbers page.
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import httpx

from ..games import Game, next_draw_date_after

USER_AGENT = "Mozilla/5.0 (compatible; lottery-analytics/0.1)"
NY_DATASETS = {"powerball": "d6yy-54nr", "megamillions": "5xaw-6ayf"}
WA_GAME_NAMES = {"wa-lotto": "lotto", "wa-hit5": "hit5"}
# Class suffix of each game's block on the WA winning-numbers page.
WA_BUCKETS = {"powerball": "powerball", "megamillions": "megamillions", "wa-lotto": "lotto", "wa-hit5": "hit5"}


@dataclass(frozen=True)
class RawDraw:
    """A result as published, before rule validation."""

    game_key: str
    draw_date: date
    primary_numbers: tuple[int, ...]
    bonus_number: int | None = None
    multiplier: int | None = None
    jackpot_usd: int | None = None
    source: str = ""


@dataclass(frozen=True)
class JackpotEstimate:
    game_key: str
    jackpot_usd: int
    cash_value_usd: int | None
    source: str
    draw_date: date | None = None  # the upcoming draw it applies to, when the source says


def _get(url: str, timeout: float = 60.0) -> str:
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True) as client:
        r = client.get(url)
        r.raise_for_status()
        return r.text


def parse_money(text: str) -> int | None:
    """'$485.00 Million*' -> 485000000, '$550,000' -> 550000. None when there is no dollar amount."""
    m = re.search(r"\$\s*([\d,]+(?:\.\d+)?)\s*(billion|million)?", text, re.I)
    if not m:
        return None
    value = float(m.group(1).replace(",", ""))
    scale = {"billion": 1e9, "million": 1e6}.get((m.group(2) or "").lower(), 1)
    return int(round(value * scale))


def _int_or_none(value) -> int | None:
    try:
        return int(str(value).strip().lower().removesuffix("x"))
    except (TypeError, ValueError):
        return None


# ---- New York open data (Powerball, Mega Millions) ----

def parse_ny_rows(game: Game, rows: list[dict]) -> list[RawDraw]:
    """Powerball rows carry the Powerball as the sixth winning number; Mega Millions has a mega_ball field."""
    out = []
    for row in rows:
        nums = [int(x) for x in row["winning_numbers"].split()]
        if "mega_ball" in row:
            bonus = int(row["mega_ball"])
        elif len(nums) == game.pick + 1:
            bonus = nums.pop()
        else:
            bonus = None
        out.append(
            RawDraw(
                game_key=game.key,
                draw_date=date.fromisoformat(row["draw_date"][:10]),
                primary_numbers=tuple(nums),
                bonus_number=bonus,
                multiplier=_int_or_none(row.get("multiplier")),
                source="data.ny.gov",
            )
        )
    return out


def fetch_ny(game: Game, since: date) -> list[RawDraw]:
    dataset = NY_DATASETS[game.key]
    url = (
        f"https://data.ny.gov/resource/{dataset}.json?$limit=50000&$order=draw_date"
        f"&$where=draw_date%20%3E=%20%27{since.isoformat()}%27"
    )
    return parse_ny_rows(game, json.loads(_get(url)))


# ---- megamillions.com ----

def parse_megamillions_latest(game: Game, payload: str) -> tuple[RawDraw | None, JackpotEstimate | None]:
    """The endpoint wraps a JSON document in an XML <string> element."""
    m = re.search(r"\{.*\}", payload, re.S)
    if not m:
        return None, None
    data = json.loads(html.unescape(m.group(0)))
    draw = est = None
    d = data.get("Drawing") or {}
    if d.get("PlayDate"):
        megaplier = d.get("Megaplier")
        draw = RawDraw(
            game_key=game.key,
            draw_date=date.fromisoformat(d["PlayDate"][:10]),
            primary_numbers=tuple(int(d[f"N{i}"]) for i in range(1, game.pick + 1)),
            bonus_number=int(d["MBall"]),
            multiplier=megaplier if isinstance(megaplier, int) and megaplier > 0 else None,
            source="megamillions.com",
        )
    j = data.get("Jackpot") or {}
    if j.get("NextPrizePool"):
        cash = j.get("NextCashValue")
        played = date.fromisoformat(j["PlayDate"][:10]) if j.get("PlayDate") else None
        est = JackpotEstimate(
            game.key,
            int(j["NextPrizePool"]),
            int(cash) if cash else None,
            "megamillions.com",
            draw_date=next_draw_date_after(game, played) if played else None,
        )
    return draw, est


def fetch_megamillions_latest(game: Game) -> tuple[RawDraw | None, JackpotEstimate | None]:
    return parse_megamillions_latest(
        game, _get("https://www.megamillions.com/cmspages/utilservice.asmx/GetLatestDrawData")
    )


# ---- walottery.com ----

_WA_DRAW_BLOCK = re.compile(r'<table class="table-viewport-large">(.*?)</table>', re.S)
_WA_DATE = re.compile(r'h2-like">\s*([^<]+?)\s*<')
_WA_BALLS = re.compile(r'class="game-balls"[^>]*>(.*?)</ul>', re.S)
_WA_BALL = re.compile(r"<li[^>]*>\s*(\d+)\s*</li>")
_WA_TOP_PRIZE = re.compile(r"<td>\s*\d+ of \d+\s*</td>\s*<td>\s*([^<]*?)\s*</td>")


def parse_wa_past_drawings(game: Game, page: str) -> list[RawDraw]:
    """Each drawing is a table: date heading, the balls, then prize rows whose first is the top prize."""
    out = []
    for block in _WA_DRAW_BLOCK.finditer(page):
        body = block.group(1)
        when, balls = _WA_DATE.search(body), _WA_BALLS.search(body)
        if not when or not balls:
            continue
        top = _WA_TOP_PRIZE.search(body)
        out.append(
            RawDraw(
                game_key=game.key,
                draw_date=datetime.strptime(when.group(1), "%a, %b %d, %Y").date(),
                primary_numbers=tuple(int(n) for n in _WA_BALL.findall(balls.group(1))),
                jackpot_usd=parse_money(top.group(1)) if top else None,
                source="walottery.com",
            )
        )
    return out


def fetch_wa_year(game: Game, year: int) -> list[RawDraw]:
    name = WA_GAME_NAMES[game.key]
    return parse_wa_past_drawings(
        game,
        _get(
            "https://www.walottery.com/WinningNumbers/PastDrawings.aspx"
            f"?gamename={name}&unittype=year&unitcount={year}",
            timeout=120.0,
        ),
    )


def _upcoming_date(label: str, today: date) -> date | None:
    """'WED/OCT 7' -> the next October 7 on or after `today` (the page omits the year)."""
    m = re.search(r"([A-Za-z]{3})\s+(\d{1,2})\s*$", label.strip())
    if not m:
        return None
    for year in (today.year, today.year + 1):
        try:
            day = datetime.strptime(f"{m.group(1).title()} {m.group(2)} {year}", "%b %d %Y").date()
        except ValueError:
            return None
        if day >= today - timedelta(days=1):
            return day
    return None


def parse_wa_jackpots(page: str, today: date | None = None) -> list[JackpotEstimate]:
    """Each game's block on the winning-numbers page shows the next jackpot and, for some, a cash option."""
    today = today or date.today()
    marker = 'class="game-bucket game-bucket-'
    out = []
    for key, bucket in WA_BUCKETS.items():
        start = page.find(f'{marker}{bucket}"')
        if start < 0:
            continue
        end = page.find(marker, start + 1)
        block = page[start : end if end > 0 else len(page)]
        amount = re.search(r">\s*(?:Jackpot|Cashpot)\s*</p>\s*<p[^>]*>([^<]+)<", block)
        jackpot = parse_money(amount.group(1)) if amount else None
        if not jackpot:
            continue
        cash = re.search(r"Cash Option\s*<strong>([^<]+)</strong>", block)
        next_draw = re.search(r"Next Draw:\s*<strong>([^<]+)</strong>", block)
        out.append(
            JackpotEstimate(
                key,
                jackpot,
                parse_money(cash.group(1)) if cash else None,
                "walottery.com",
                draw_date=_upcoming_date(next_draw.group(1), today) if next_draw else None,
            )
        )
    return out


def fetch_wa_jackpots() -> list[JackpotEstimate]:
    return parse_wa_jackpots(_get("https://www.walottery.com/WinningNumbers/Default.aspx"))
