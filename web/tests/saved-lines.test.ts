// Lines kept and scored in the browser on the hosted site.
import assert from "node:assert/strict";
import { test } from "node:test";

import { clearSaved, liveAccuracy, loadSaved, saveForecast, scoreSaved, type KeyValueStore, type SavedForecast } from "../src/lib/saved-lines.ts";

function memoryStore(): KeyValueStore & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => void data.set(k, v),
    removeItem: (k) => void data.delete(k),
  };
}

const forecast = (id: number, target: string, lines: [number[], number | null][], strategy = "balanced"): SavedForecast => ({
  forecast_id: id,
  created_at: `2026-10-0${id}T12:00:00Z`,
  target_draw_date: target,
  strategy,
  backend: "timesfm",
  lines: lines.map(([primary_numbers, bonus_number]) => ({ primary_numbers, bonus_number })),
});

const draw = (date: string, primary_numbers: number[], bonus_number: number | null) => ({
  draw_id: 1, game_key: "powerball" as const, draw_date: date, primary_numbers, bonus_number, multiplier: null, jackpot_usd: null,
});

test("saved forecasts are kept per game, newest first", () => {
  const store = memoryStore();
  assert.equal(saveForecast(store, "powerball", forecast(1, "2026-10-07", [[[1, 2, 3, 4, 5], 6]])), true);
  assert.equal(saveForecast(store, "powerball", forecast(2, "2026-10-10", [[[7, 8, 9, 10, 11], 12]])), true);
  saveForecast(store, "wa-hit5", forecast(3, "2026-10-07", [[[1, 2, 3, 4, 5], null]]));
  assert.deepEqual(loadSaved(store, "powerball").map((f) => f.forecast_id), [2, 1]);
  assert.deepEqual(loadSaved(store, "wa-hit5").map((f) => f.forecast_id), [3]);
  clearSaved(store, "powerball");
  assert.deepEqual(loadSaved(store, "powerball"), []);
  assert.equal(loadSaved(store, "wa-hit5").length, 1);
});

test("only the most recent forty are kept", () => {
  const store = memoryStore();
  for (let i = 1; i <= 45; i++) saveForecast(store, "powerball", forecast(i, "2026-10-07", [[[1, 2, 3, 4, 5], 6]]));
  const saved = loadSaved(store, "powerball");
  assert.equal(saved.length, 40);
  assert.equal(saved[0].forecast_id, 45);
  assert.equal(saved[39].forecast_id, 6);
});

test("a browser that refuses storage is reported, not thrown", () => {
  const refusing: KeyValueStore = {
    getItem: () => null,
    setItem: () => {
      throw new Error("QuotaExceededError");
    },
    removeItem: () => {},
  };
  assert.equal(saveForecast(refusing, "powerball", forecast(1, "2026-10-07", [])), false);
  assert.equal(saveForecast(null, "powerball", forecast(1, "2026-10-07", [])), false);
  assert.deepEqual(loadSaved(null, "powerball"), []);
  const corrupt = memoryStore();
  corrupt.data.set("forecast-lab:lines:powerball", "{not json");
  assert.deepEqual(loadSaved(corrupt, "powerball"), []);
  clearSaved(null, "powerball");
});

test("lines are scored once their draw is in, and wait otherwise", () => {
  const saved = [
    forecast(2, "2026-10-10", [[[1, 2, 3, 4, 5], 6]]), // draw not in yet
    forecast(1, "2026-10-07", [
      [[16, 23, 32, 40, 41], 9], // three main numbers and the bonus
      [[1, 2, 3, 4, 5], 10], // nothing
    ]),
  ];
  const scored = scoreSaved(saved, [draw("2026-10-07", [16, 23, 32, 36, 54], 9), draw("2026-10-05", [1, 2, 3, 4, 5], 6)]);
  assert.equal(scored[0].draw, null);
  assert.deepEqual(scored[0].lines[0], { primary_numbers: [1, 2, 3, 4, 5], bonus_number: 6, scored: false, main_matches: null, bonus_match: null });
  assert.deepEqual(scored[1].draw, { primary_numbers: [16, 23, 32, 36, 54], bonus_number: 9 });
  assert.deepEqual(scored[1].lines.map((l) => [l.main_matches, l.bonus_match, l.scored]), [[3, true, true], [0, false, true]]);
});

test("a game without a bonus ball never reports a bonus match", () => {
  const scored = scoreSaved([forecast(1, "2026-10-07", [[[11, 15, 21, 37, 38], null]])], [draw("2026-10-07", [11, 15, 21, 37, 38], null)]);
  assert.equal(scored[0].lines[0].main_matches, 5);
  assert.equal(scored[0].lines[0].bonus_match, null);
});

test("the accuracy summary averages scored lines and counts the ones still waiting", () => {
  const draws = [draw("2026-10-07", [16, 23, 32, 36, 54], 9)];
  const scored = scoreSaved(
    [
      forecast(3, "2026-10-10", [[[1, 2, 3, 4, 5], 6], [[7, 8, 9, 10, 11], 12]], "hot"),
      forecast(2, "2026-10-07", [[[16, 23, 1, 2, 3], 9]], "hot"),
      forecast(1, "2026-10-07", [[[16, 23, 32, 36, 1], 1], [[1, 2, 3, 4, 5], 1]]),
    ],
    draws,
  );
  const live = liveAccuracy(scored);
  assert.equal(live.scored_lines, 3);
  assert.equal(live.pending_lines, 2);
  assert.equal(live.mean_matches, (2 + 4 + 0) / 3);
  assert.deepEqual(live.by_strategy, [
    { strategy: "balanced", scored: 2, pending: 0, mean_matches: 2, best: 4, bonus_hits: 0 },
    { strategy: "hot", scored: 1, pending: 2, mean_matches: 2, best: 2, bonus_hits: 1 },
  ]);
  assert.deepEqual(liveAccuracy([]), { scored_lines: 0, pending_lines: 0, mean_matches: null, by_strategy: [] });
});
