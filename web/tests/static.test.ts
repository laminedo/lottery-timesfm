// The read-only demo's browser-side logic: draw schedules, line sampling and the snapshot transport.
import assert from "node:assert/strict";
import { test } from "node:test";

import { generateLines, sampleOne, sampleWithoutReplacement } from "../src/lib/sampler.ts";
import { isoInZone, localDate, nextDrawAt } from "../src/lib/schedule.ts";
import { generateFrom, withLiveSchedule } from "../src/lib/static-api.ts";

const POWERBALL = { draw_days: [0, 2, 5], draw_time: "22:59", timezone: "America/New_York" };
const MEGA = { draw_days: [1, 4], draw_time: "23:00", timezone: "America/New_York" };
const LOTTO = { draw_days: [0, 2, 5], draw_time: "20:00", timezone: "America/Los_Angeles" };
const HIT5 = { draw_days: [0, 1, 2, 3, 4, 5, 6], draw_time: "20:00", timezone: "America/Los_Angeles" };

/** A repeatable stand-in for Math.random. */
function seeded(seed: number) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// The same cases as backend/tests/test_games.py, so browser and server agree on the schedule.
test("next draw is the same evening before draw time, in the game's own zone", () => {
  const wednesdayNoonET = new Date("2026-10-07T12:00:00-04:00");
  assert.equal(isoInZone(nextDrawAt(POWERBALL, wednesdayNoonET), POWERBALL.timezone), "2026-10-07T22:59:00-04:00");
});

test("after draw time it moves to the next draw day", () => {
  const wednesdayLateET = new Date("2026-10-07T23:30:00-04:00");
  assert.equal(isoInZone(nextDrawAt(POWERBALL, wednesdayLateET), POWERBALL.timezone), "2026-10-10T22:59:00-04:00");
  assert.equal(isoInZone(nextDrawAt(MEGA, wednesdayLateET), MEGA.timezone), "2026-10-09T23:00:00-04:00");
});

test("the viewer's own time zone does not matter", () => {
  // 03:30 UTC Thursday is 20:30 Wednesday in Seattle: Wednesday's 20:00 Lotto draw has passed.
  const now = new Date("2026-10-08T03:30:00Z");
  assert.equal(localDate(nextDrawAt(LOTTO, now), LOTTO.timezone), "2026-10-10");
  assert.equal(localDate(nextDrawAt(HIT5, now), HIT5.timezone), "2026-10-08");
});

test("draw times stay on the local clock across daylight-saving changes", () => {
  // US clocks go back on Sunday 1 November 2026: the offset changes from -04:00 to -05:00.
  const saturdayLate = new Date("2026-10-31T23:30:00-04:00");
  assert.equal(isoInZone(nextDrawAt(POWERBALL, saturdayLate), POWERBALL.timezone), "2026-11-02T22:59:00-05:00");
  // And forward on Sunday 14 March 2027.
  const beforeSpring = new Date("2027-03-13T23:30:00-05:00");
  assert.equal(isoInZone(nextDrawAt(POWERBALL, beforeSpring), POWERBALL.timezone), "2027-03-15T22:59:00-04:00");
});

test("sampling without replacement never repeats and follows the weights", () => {
  const random = seeded(1);
  const weights = [0.4, 0.3, 0.2, 0.1, 0];
  const seen = [0, 0, 0, 0, 0];
  for (let i = 0; i < 4000; i++) {
    const [a, b] = sampleWithoutReplacement(random, weights, 2);
    assert.notEqual(a, b);
    assert.ok(a < b, "indices come back sorted");
    seen[a]++;
    seen[b]++;
  }
  assert.ok(seen[0] > seen[1] && seen[1] > seen[2] && seen[2] > seen[3]);
  assert.equal(seen[4], 0);
  assert.throws(() => sampleWithoutReplacement(random, weights, 6), /Cannot draw 6/);
});

test("sampleOne follows the weights", () => {
  const random = seeded(2);
  const seen = [0, 0, 0];
  for (let i = 0; i < 6000; i++) seen[sampleOne(random, [1, 2, 3])]++;
  assert.ok(Math.abs(seen[0] / 6000 - 1 / 6) < 0.02 && Math.abs(seen[2] / 6000 - 1 / 2) < 0.02);
});

test("generated lines obey the game rules and do not repeat", () => {
  const main = Array.from({ length: 69 }, () => 1 / 69);
  const bonus = Array.from({ length: 26 }, () => 1 / 26);
  const lines = generateLines(seeded(3), main, 5, bonus, 5);
  assert.equal(lines.length, 5);
  for (const line of lines) {
    assert.equal(new Set(line.primary).size, 5);
    assert.ok(line.primary.every((n) => Number.isInteger(n) && n >= 1 && n <= 69));
    assert.deepEqual(line.primary, [...line.primary].sort((a, b) => a - b));
    assert.ok(line.bonus !== null && line.bonus >= 1 && line.bonus <= 26);
    assert.ok(Math.abs(line.lift - 1) < 1e-9, "a flat distribution favours nothing");
  }
  assert.equal(new Set(lines.map((l) => `${l.primary}|${l.bonus}`)).size, 5);
  // Six numbers carry all the weight: only C(6,5) = 6 distinct lines exist.
  const narrow = Array.from({ length: 42 }, (_, i) => (i < 6 ? 1 / 6 : 0));
  assert.equal(new Set(generateLines(seeded(4), narrow, 5, null, 6).map((l) => `${l.primary}`)).size, 6);
});

function snapshot() {
  const pool = (size: number, pick: number) => ({
    pool: size,
    pick,
    baseline: pick / size,
    informative: true,
    context_draws: 500,
    channels: {},
    numbers: Array.from({ length: size }, (_, i) => {
      const p = pick / size;
      return { number: i + 1, timesfm: p, hot: p, cold: p, representation_a: p, representation_b: p, rate: p, rate_low: p, rate_high: p };
    }),
  });
  const weights = { timesfm: 1, hot: 0, cold: 0, uniform: 0 };
  const forecast = {
    game: "powerball" as const,
    backend: { name: "timesfm" as const, label: "TimesFM 2.5 (200M)", ready: true },
    target_draw_at: "2026-10-07T22:59:00-04:00",
    as_of: { draw_id: 1, draw_date: "2026-10-05", primary_numbers: [16, 23, 32, 36, 54], bonus_number: 9 },
    main: { ...pool(69, 5), positions: [], sum: { mean: 175, quantiles: [124, 142, 155, 165, 176, 186, 196, 209, 227], expected_mean: 175, expected_sd: 43 }, moving_sum: null },
    bonus: pool(26, 1),
    strategies: {
      balanced: { label: "Balanced", description: "", weights },
      hot: { label: "Hot numbers", description: "", weights: { timesfm: 0.25, hot: 0.75, cold: 0, uniform: 0 } },
      cold: { label: "Contrarian / cold", description: "", weights: { timesfm: 0.25, hot: 0, cold: 0.75, uniform: 0 } },
      entropy: { label: "High entropy", description: "", weights: { timesfm: 0, hot: 0, cold: 0, uniform: 1 } },
    },
    disclaimer: "",
  };
  const game = {
    key: "powerball" as const, name: "Powerball", region: "US", pick: 5, pool: 69, bonus_pool: 26, bonus_name: "Powerball",
    main_since: "2015-10-07", bonus_since: "2015-10-07", ...POWERBALL, jackpot_odds: 292_201_338, draw_count: 1416,
    first_draw_date: "2015-10-07", latest_draw: null, next_draw_at: "2026-10-07T22:59:00-04:00",
    next_jackpot: { draw_date: "2026-10-07", jackpot_usd: 485_000_000, cash_value_usd: 199_800_000, source: "walottery.com", fetched_at: "2026-10-07T07:00:00Z" },
  };
  return { forecast, game };
}

test("the hosted site generates lines like the server does", () => {
  const { forecast, game } = snapshot();
  const out = generateFrom(forecast, game, { lines: 3, strategy: "hot", temperature: 1 }, seeded(5));
  assert.equal(out.saved, false); // sampling alone stores nothing; the caller saves to the browser
  assert.equal(out.strategy, "hot");
  assert.deepEqual(out.weights, { timesfm: 0.25, hot: 0.75, cold: 0, uniform: 0 });
  assert.equal(out.jackpot_odds, 292_201_338);
  assert.equal(out.lines.length, 3);
  for (const line of out.lines) {
    assert.equal(line.sum, line.primary_numbers.reduce((a, b) => a + b, 0));
    assert.equal(line.odd, line.primary_numbers.filter((n) => n % 2 === 1).length);
    assert.equal(line.sum_in_forecast_band, line.sum >= 124 && line.sum <= 227);
  }
  const custom = generateFrom(forecast, game, { lines: 1, weights: { timesfm: 0, hot: 3, cold: 1, uniform: 0 } }, seeded(6));
  assert.equal(custom.strategy, "custom");
  assert.deepEqual(custom.weights, { timesfm: 0, hot: 0.75, cold: 0.25, uniform: 0 });
});

test("the snapshot's schedule is brought up to date and an expired jackpot is dropped", () => {
  const { game } = snapshot();
  const beforeDraw = withLiveSchedule(game, new Date("2026-10-07T12:00:00-04:00"));
  assert.equal(beforeDraw.next_draw_at, "2026-10-07T22:59:00-04:00");
  assert.equal(beforeDraw.next_jackpot?.jackpot_usd, 485_000_000);
  // A week later the snapshot is stale: the countdown moves on, and the old estimate is not shown as current.
  const weekLater = withLiveSchedule(game, new Date("2026-10-14T12:00:00-04:00"));
  assert.equal(weekLater.next_draw_at, "2026-10-14T22:59:00-04:00");
  assert.equal(weekLater.next_jackpot, null);
});
