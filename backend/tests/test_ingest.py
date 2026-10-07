"""Feed parsers (on markup copied from the live sites) and loading draws into Postgres."""
from datetime import date

from app.games import GAMES, next_draw_at
from app.ingest import pipeline, sources
from app.ingest.sources import JackpotEstimate, RawDraw

from .conftest import synthetic_draws

PB, MM, LOTTO, HIT5 = (GAMES[k] for k in ("powerball", "megamillions", "wa-lotto", "wa-hit5"))

WA_PAST_DRAWINGS = """
<table class="table-viewport-small"><thead><tr><th><p class="h2-like">Tue, Oct 06, 2026</p></th></tr></thead>
  <tbody><tr><td class="game-balls"><ul><li>11</li><li>15</li><li>21</li><li>37</li><li>38</li></ul></td></tr></tbody></table>
<table class="table-viewport-large">
  <thead><tr><th scope="col"><p class="h2-like">Tue, Oct 06, 2026</p></th>
    <th scope="col">Prize Level</th><th scope="col">Prize Amount</th></tr></thead>
  <tbody><tr>
    <td class="game-balls" rowspan="5"><ul>
      <li>11</li> <li>15</li> <li>21</li> <li>37</li> <li>38</li></ul></td>
        <td>5 of 5</td>
            <td>$480,000</td>
    <td>0</td><td>$0</td></tr>
    <tr><td>4 of 5</td><td>$150</td><td>50</td><td>$7,500</td></tr></tbody></table>
<table class="table-viewport-large">
  <thead><tr><th scope="col"><p class="h2-like">Mon, Oct 05, 2026</p></th></tr></thead>
  <tbody><tr><td class="game-balls" rowspan="5"><ul><li>20</li><li>26</li><li>27</li><li>38</li><li>40</li></ul></td>
    <td>5 of 5</td><td>$455,000</td></tr></tbody></table>
"""

WA_WINNING_NUMBERS = """
<div class="game-bucket game-bucket-powerball"><footer>
  <p class="powerball-jackpot-title h4-like">Jackpot</p>
  <p class="powerball-amount h2-like">$485.00 Million*</p>
  <p class="powerball-cash-option">Cash Option <strong>$199.80 Million*</strong></p>
  <p class="powerball-doubleplay-amount h2-like">$10.0 Million</p>
  <p class="powerball-next-draw h4-like">Next Draw: <strong>WED/OCT 7</strong></p></footer></div>
<div class="game-bucket game-bucket-megamillions"><footer>
  <p class="h4-like">Jackpot</p>
  <p class="h2-like">$1.25 Billion*</p>
  <p>Cash Option <strong>$147.30 Million*</strong></p>
  <p class="h4-like">Next Draw: <strong>FRI/OCT 9</strong></p></footer></div>
<div class="game-bucket game-bucket-hit5"><footer>
  <p class="h4-like">Cashpot</p>
  <p class="h2-like">$550,000</p>
  <p class="h4-like">Next Draw: <strong>WED/OCT 7</strong></p></footer></div>
<div class="game-bucket game-bucket-match4"><footer><p class="h4-like">Top Prize</p><p class="h2-like">$10,000</p></footer></div>
"""

MM_LATEST = (
    '<?xml version="1.0" encoding="utf-8"?><string xmlns="http://tempuri.org/">'
    '{"Drawing":{"PlayDate":"2026-10-06T00:00:00","N1":26,"N2":32,"N3":42,"N4":51,"N5":54,"MBall":22,"Megaplier":-1},'
    '"Jackpot":{"PlayDate":"2026-10-06T00:00:00","CurrentPrizePool":345000000.0,"NextPrizePool":364000000.0,'
    '"NextCashValue":147300000.0}}</string>'
)


def test_parse_money():
    assert sources.parse_money("$485.00 Million*") == 485_000_000
    assert sources.parse_money("$1.25 Billion*") == 1_250_000_000
    assert sources.parse_money("$550,000") == 550_000
    assert sources.parse_money("Free Hit5 Ticket") is None


def test_ny_powerball_row_carries_the_powerball_as_sixth_number():
    rows = [{"draw_date": "2026-10-05T00:00:00.000", "winning_numbers": "16 23 32 36 54 09", "multiplier": "2"}]
    assert sources.parse_ny_rows(PB, rows) == [
        RawDraw("powerball", date(2026, 10, 5), (16, 23, 32, 36, 54), 9, 2, None, "data.ny.gov")
    ]


def test_ny_megamillions_row_has_a_separate_mega_ball():
    rows = [{"draw_date": "2026-10-02T00:00:00.000", "winning_numbers": "06 37 40 41 55", "mega_ball": "10"}]
    (draw,) = sources.parse_ny_rows(MM, rows)
    assert (draw.primary_numbers, draw.bonus_number, draw.multiplier) == ((6, 37, 40, 41, 55), 10, None)


def test_megamillions_latest_draw_and_next_jackpot():
    draw, est = sources.parse_megamillions_latest(MM, MM_LATEST)
    assert draw == RawDraw("megamillions", date(2026, 10, 6), (26, 32, 42, 51, 54), 22, None, None, "megamillions.com")
    # The "next" jackpot belongs to the draw after the one just played: Friday the 9th.
    assert est == JackpotEstimate("megamillions", 364_000_000, 147_300_000, "megamillions.com", date(2026, 10, 9))


def test_wa_past_drawings_reads_date_balls_and_top_prize_once_per_draw():
    draws = sources.parse_wa_past_drawings(HIT5, WA_PAST_DRAWINGS)
    assert draws == [
        RawDraw("wa-hit5", date(2026, 10, 6), (11, 15, 21, 37, 38), None, None, 480_000, "walottery.com"),
        RawDraw("wa-hit5", date(2026, 10, 5), (20, 26, 27, 38, 40), None, None, 455_000, "walottery.com"),
    ]


def test_wa_jackpots_per_game_block():
    got = {e.game_key: e for e in sources.parse_wa_jackpots(WA_WINNING_NUMBERS, today=date(2026, 10, 6))}
    assert set(got) == {"powerball", "megamillions", "wa-hit5"}  # no Lotto block in this page
    assert got["powerball"] == JackpotEstimate("powerball", 485_000_000, 199_800_000, "walottery.com", date(2026, 10, 7))
    assert got["megamillions"].jackpot_usd == 1_250_000_000
    assert got["wa-hit5"] == JackpotEstimate("wa-hit5", 550_000, None, "walottery.com", date(2026, 10, 7))


def test_wa_next_draw_label_rolls_into_next_year():
    page = WA_WINNING_NUMBERS.replace("WED/OCT 7", "FRI/JAN 1")
    got = {e.game_key: e for e in sources.parse_wa_jackpots(page, today=date(2026, 12, 31))}
    assert got["powerball"].draw_date == date(2027, 1, 1)


def test_normalize_sorts_validates_and_drops_old_formats():
    raw = [
        RawDraw("powerball", date(2024, 1, 3), (30, 10, 20, 50, 40), 7),
        RawDraw("powerball", date(2015, 10, 3), (1, 2, 3, 4, 5), 1),  # before 5-of-69: dropped, not an error
        RawDraw("powerball", date(2024, 1, 6), (1, 2, 3, 4, 70), 7),  # 70 is out of range
        RawDraw("powerball", date(2024, 1, 8), (1, 2, 3, 4, 4), 7),  # duplicate
        RawDraw("powerball", date(2024, 1, 1), (5, 4, 3, 2, 1), 26),
    ]
    draws, rejected = pipeline.normalize(PB, raw)
    assert [(d.draw_date, d.primary_numbers) for d in draws] == [
        (date(2024, 1, 1), (1, 2, 3, 4, 5)),
        (date(2024, 1, 3), (10, 20, 30, 40, 50)),
    ]
    assert len(rejected) == 2
    assert "must be 1-69" in rejected[0] and "duplicate" in rejected[1]


def test_upsert_is_idempotent_and_keeps_known_jackpots(db):
    draws = synthetic_draws(HIT5, 30)
    assert pipeline.upsert_draws(db, draws) == 30
    assert pipeline.upsert_draws(db, draws) == 0
    first = draws[0]
    with_prize = RawDraw(first.game_key, first.draw_date, first.primary_numbers, jackpot_usd=120_000, source="x")
    pipeline.upsert_draws(db, [with_prize])
    pipeline.upsert_draws(db, [first])  # a later fetch without the prize must not erase it
    row = db.fetch_one("select jackpot_usd from draws where game_key = %s and draw_date = %s", ("wa-hit5", first.draw_date))
    assert row["jackpot_usd"] == 120_000
    assert db.fetch_one("select count(*) as n from draws")["n"] == 30


def test_database_rejects_a_second_draw_on_the_same_date(db):
    d = synthetic_draws(HIT5, 1)[0]
    pipeline.upsert_draws(db, [d])
    other = RawDraw(d.game_key, d.draw_date, (1, 2, 3, 4, 5), source="x")
    pipeline.upsert_draws(db, [other])
    rows = db.fetch_all("select primary_numbers from draws where game_key = 'wa-hit5'")
    assert [r["primary_numbers"] for r in rows] == [[1, 2, 3, 4, 5]]  # corrected in place, not duplicated


def test_seed_file_round_trip(db, tmp_path):
    draws = synthetic_draws(MM, 40)
    draws[0] = RawDraw(MM.key, draws[0].draw_date, draws[0].primary_numbers, draws[0].bonus_number, 3, 90_000_000, "synthetic")
    pipeline.write_seed(tmp_path, MM, draws)
    assert pipeline.read_seed(tmp_path, MM) == draws
    assert pipeline.seed_if_empty(db, tmp_path) == {"powerball": 0, "megamillions": 40, "wa-lotto": 0, "wa-hit5": 0}
    assert "megamillions" not in pipeline.seed_if_empty(db, tmp_path)  # already has draws


def test_jackpot_estimate_is_copied_onto_its_draw_once_ingested(db):
    target = next_draw_at(PB).date()
    pipeline.store_jackpot_estimates(db, [JackpotEstimate("powerball", 485_000_000, 199_800_000, "walottery.com", target)])
    pipeline.upsert_draws(db, [RawDraw("powerball", target, (1, 2, 3, 4, 5), 6, source="data.ny.gov")])
    pipeline.store_jackpot_estimates(db, [])
    assert db.fetch_one("select jackpot_usd from draws where draw_date = %s", (target,))["jackpot_usd"] == 485_000_000
