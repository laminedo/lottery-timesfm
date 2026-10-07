import assert from "node:assert/strict";
import { test } from "node:test";

import { blend, normalizeWeights, toPresence } from "../src/components/forecast/blend.ts";
import { countdownParts, dateTickFormatter, formatDate, formatJackpot, formatP } from "../src/lib/format.ts";
import { niceTicks } from "../src/lib/scale.ts";

const close = (actual: number[], expected: number[]) =>
  actual.forEach((v, i) => assert.ok(Math.abs(v - expected[i]) < 1e-9, `index ${i}: ${v} vs ${expected[i]}`));

/** A four-number pool whose models disagree, as the API would describe it. */
function pool(timesfm: number[], hot: number[], cold: number[]) {
  const numbers = timesfm.map((t, i) => ({
    number: i + 1, timesfm: t, hot: hot[i], cold: cold[i],
    representation_a: t, representation_b: t, rate: t, rate_low: t, rate_high: t,
  }));
  return { pool: 4, pick: 2, baseline: 0.5, informative: true, context_draws: 100, numbers, channels: {} };
}

test("blend mixes normalised components by weight (same cases as the backend sampler tests)", () => {
  const p = pool([4, 0, 0, 0], [0, 1, 1, 0], [0, 0, 0, 9]);
  close(blend(p, { timesfm: 1, hot: 1, cold: 0, uniform: 0 }, 1), [0.5, 0.25, 0.25, 0]);
  close(blend(p, { timesfm: 0, hot: 0, cold: 0, uniform: 1 }, 1), [0.25, 0.25, 0.25, 0.25]);
  close(blend(p, { timesfm: 100, hot: 0, cold: 0, uniform: 0 }, 1), [1, 0, 0, 0]);
});

test("temperature sharpens below 1 and flattens above 1", () => {
  const p = pool([0.5, 0.3, 0.2, 0.0001], [1, 1, 1, 1], [1, 1, 1, 1]);
  const w = { timesfm: 1, hot: 0, cold: 0, uniform: 0 };
  const [cool, neutral, warm] = [0.5, 1, 3].map((t) => blend(p, w, t));
  assert.ok(cool[0] > neutral[0] && neutral[0] > warm[0]);
  for (const dist of [cool, neutral, warm]) assert.ok(Math.abs(dist.reduce((a, b) => a + b, 0) - 1) < 1e-9);
});

test("weights are normalised and presence probabilities are capped at 1", () => {
  assert.deepEqual(normalizeWeights({ timesfm: 0, hot: 3, cold: 1, uniform: 0 }), { timesfm: 0, hot: 0.75, cold: 0.25, uniform: 0 });
  close(toPresence([0.7, 0.2, 0.1, 0], 2), [1, 0.4, 0.2, 0]);
});

test("jackpots read naturally at every size", () => {
  assert.equal(formatJackpot(485_000_000), "$485 million");
  assert.equal(formatJackpot(199_800_000), "$199.8 million");
  assert.equal(formatJackpot(1_250_000_000), "$1.25 billion");
  assert.equal(formatJackpot(550_000), "$550,000");
});

test("dates keep their calendar day in any time zone", () => {
  assert.equal(formatDate("2026-10-07"), "Wed, Oct 7, 2026");
  assert.equal(formatDate("2026-01-01"), "Thu, Jan 1, 2026");
});

test("date ticks add the year only for long spans", () => {
  assert.equal(dateTickFormatter("2026-07-01", "2026-10-06")("2026-10-06"), "Oct 6");
  assert.equal(dateTickFormatter("2024-11-01", "2026-10-06")("2026-10-06"), "Oct ’26");
});

test("p-values and countdowns", () => {
  assert.equal(formatP(0.4321), "0.43");
  assert.equal(formatP(0.0081), "0.008");
  assert.equal(formatP(0.00001), "< 0.001");
  assert.equal(formatP(null), "n/a");
  assert.deepEqual(countdownParts(((2 * 24 + 19) * 3600 + 22 * 60 + 5) * 1000), { days: 2, hours: 19, minutes: 22, seconds: 5 });
  assert.deepEqual(countdownParts(-5000), { days: 0, hours: 0, minutes: 0, seconds: 0 });
});

test("axis ticks are round numbers that cover the data", () => {
  assert.deepEqual(niceTicks(0, 0.34), [0, 0.1, 0.2, 0.3, 0.4]);
  assert.deepEqual(niceTicks(154, 198), [140, 160, 180, 200]);
  assert.deepEqual(niceTicks(1.8, 3.0), [1.5, 2, 2.5, 3]);
  assert.deepEqual(niceTicks(5, 5), [5, 5.25, 5.5, 5.75, 6]);
});
