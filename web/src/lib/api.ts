"use client";

import useSWR, { type SWRConfiguration } from "swr";

import { ApiError } from "./api-error";
import { IS_STATIC } from "./env";
import type { GameKey } from "./games";
import { staticGet, staticPost } from "./static-api";

export { ApiError };

/* ---- response shapes (see backend/app/main.py) ---- */

export interface Draw {
  draw_id: number;
  game_key: GameKey;
  draw_date: string;
  primary_numbers: number[];
  bonus_number: number | null;
  multiplier: number | null;
  jackpot_usd: number | null;
}

export interface Game {
  key: GameKey;
  name: string;
  region: string;
  pick: number;
  pool: number;
  bonus_pool: number | null;
  bonus_name: string | null;
  main_since: string;
  bonus_since: string | null;
  draw_days: number[];
  draw_time: string;
  timezone: string;
  jackpot_odds: number;
  draw_count: number;
  first_draw_date: string | null;
  latest_draw: Draw | null;
  next_draw_at: string;
  next_jackpot: {
    draw_date: string;
    jackpot_usd: number;
    cash_value_usd: number | null;
    source: string;
    fetched_at: string;
  } | null;
}

export interface BackendInfo {
  name: "timesfm" | "smoothing";
  label: string;
  ready: boolean;
  device?: string | null;
  model?: string;
  remote?: string;
}

export interface Health {
  status: string;
  database: string;
  backend: BackendInfo;
  draws: Record<string, number>;
  last_refresh: string | null;
  /** Present in the read-only demo: when its snapshot was taken. */
  static?: boolean;
  exported_at?: string;
}

export interface NumberForecast {
  number: number;
  /** Presence probabilities: the chance the number is in the next draw according to each model. */
  timesfm: number;
  hot: number;
  cold: number;
  representation_a: number;
  representation_b: number;
  /** TimesFM's forecast of the hit rate over the coming draws, with its 10%-90% band. */
  rate: number;
  rate_low: number;
  rate_high: number;
}

export interface PoolForecast {
  pool: number;
  pick: number;
  baseline: number;
  informative: boolean;
  context_draws: number;
  numbers: NumberForecast[];
  channels: Record<string, number[]>;
}

export interface PositionForecast {
  position: number;
  mean: number;
  quantiles: number[];
  expected: number;
}

export type StrategyKey = "balanced" | "hot" | "cold" | "entropy";
export type Component = "timesfm" | "hot" | "cold" | "uniform";
export type Weights = Record<Component, number>;

export interface Strategy {
  label: string;
  description: string;
  weights: Weights;
}

export interface Forecast {
  game: GameKey;
  backend: BackendInfo;
  target_draw_at: string;
  as_of: { draw_id: number; draw_date: string; primary_numbers: number[]; bonus_number: number | null };
  main: PoolForecast & {
    positions: PositionForecast[];
    sum: { mean: number; quantiles: number[]; expected_mean: number; expected_sd: number } | null;
    moving_sum: { mean: number; low: number; high: number } | null;
  };
  bonus: PoolForecast | null;
  strategies: Record<StrategyKey, Strategy>;
  disclaimer: string;
}

export interface GeneratedLine {
  primary_numbers: number[];
  bonus_number: number | null;
  lift: number;
  sum: number;
  odd: number;
  sum_in_forecast_band: boolean | null;
}

export interface Generated {
  forecast_id: number;
  created_at: string;
  game: GameKey;
  strategy: StrategyKey | "custom";
  backend: BackendInfo;
  weights: Weights;
  temperature: number;
  seed: number;
  /** False in the read-only demo, where lines are sampled in the browser and not stored. */
  saved?: boolean;
  target_draw_at: string;
  lines: GeneratedLine[];
  jackpot_odds: number;
}

export interface StoredForecast {
  forecast_id: number;
  created_at: string;
  target_draw_date: string;
  strategy: string;
  backend: string;
  lines: {
    primary_numbers: number[];
    bonus_number: number | null;
    main_matches: number | null;
    bonus_match: boolean | null;
    scored: boolean;
  }[];
  draw: { primary_numbers: number[]; bonus_number: number | null } | null;
}

export interface Accuracy {
  game: GameKey;
  expected_matches: number;
  match_pmf: number[];
  live: {
    scored_lines: number;
    pending_lines: number;
    mean_matches: number | null;
    by_strategy: { strategy: string; scored: number; pending: number; mean_matches: number | null; best: number | null; bonus_hits: number }[];
  };
  backtest: {
    run_id: number;
    finished_at: string;
    draws: number;
    from: string;
    to: string;
    strategies: { key: StrategyKey; label: string; mean_matches: number; p_value: number | null; consistent_with_chance: boolean }[];
  } | null;
}

export interface BacktestStrategy {
  key: StrategyKey;
  label: string;
  top_pick: {
    mean_matches: number;
    total_matches: number;
    ci95: [number, number];
    histogram: number[];
    best: number;
    z: number | null;
    p_value: number | null;
    consistent_with_chance: boolean;
  };
  sampled: { mean_matches: number | null; lines_per_draw: number };
  mean_log_lift: number;
  bonus: { scored_draws: number; top_hits: number; top_hit_rate: number | null; mean_probability_on_drawn: number | null } | null;
}

export interface BacktestResult {
  game: GameKey;
  draws: number;
  from: string | null;
  to: string | null;
  seed: number;
  baseline: { expected_matches: number; sd_matches: number; match_pmf: number[]; bonus_hit_rate: number | null };
  strategies: BacktestStrategy[];
  timeline: ({ date: string; actual: number[]; bonus: number | null } & {
    [K in StrategyKey]?: { line: number[]; matches: number; bonus?: number; bonus_match?: boolean };
  })[];
  backend: BackendInfo;
  cached_steps: number;
}

export interface BacktestRun {
  run_id: number;
  game: GameKey;
  status: "queued" | "running" | "done" | "failed";
  progress: number;
  message: string | null;
  error: string | null;
  params: { draws: number; strategies: StrategyKey[]; samples: number; seed: number };
  created_at: string;
  finished_at: string | null;
  result?: BacktestResult | null;
  summary?: {
    draws: number;
    from: string;
    to: string;
    expected_matches: number;
    strategies: { key: StrategyKey; label: string; mean_matches: number; p_value: number | null }[];
  };
}

export interface NumberStat {
  number: number;
  count: number;
  frequency: number;
  z_score: number;
  current_gap: number;
  mean_gap: number | null;
  max_gap: number;
  hits_10: number;
  hits_30: number;
  hits_50: number;
  ema_10: number;
  ema_30: number;
  ema_50: number;
  momentum: number;
  status: "hot" | "cold" | "neutral";
}

export interface PoolMetrics {
  draws: number;
  pick: number;
  pool: number;
  expected_count: number;
  expected_frequency: number;
  expected_gap: number;
  uniformity: { statistic: number | null; p_value: number | null; dof: number };
  hot: number[];
  cold: number[];
  numbers: NumberStat[];
  since?: string;
}

export interface Metrics {
  game: GameKey;
  main: PoolMetrics;
  bonus: PoolMetrics | null;
}

export interface DistributionRow {
  observed: number;
  observed_share: number;
  expected: number;
  expected_share: number;
  [label: string]: number;
}

export interface Trends {
  game: GameKey;
  draws: number;
  window: number;
  rolling_window: number;
  odd_even: { distribution: DistributionRow[]; mean_odd: number | null; expected_odd: number };
  high_low: { distribution: DistributionRow[]; split_at: number; mean_high: number | null; expected_high: number };
  consecutive: { distribution: DistributionRow[]; share_with_any: number | null; expected_share_with_any: number };
  sums: {
    histogram: { from: number; to: number; observed: number; expected: number }[];
    mean: number | null;
    sd: number | null;
    expected_mean: number;
    expected_sd: number;
    min: number | null;
    max: number | null;
  };
  series: {
    date: string;
    odd: number;
    even: number;
    high: number;
    low: number;
    consecutive: number;
    sum: number;
    spread: number;
    odd_avg: number;
    high_avg: number;
    consecutive_avg: number;
    sum_avg: number;
  }[];
}

export interface DrawPage {
  game: GameKey;
  total: number;
  limit: number;
  offset: number;
  draws: Draw[];
}

/* ---- transport ---- */

async function parse<T>(response: Response): Promise<T> {
  if (response.ok) return response.json() as Promise<T>;
  let detail = `Request failed (${response.status})`;
  try {
    const body = await response.json();
    if (typeof body.detail === "string") detail = body.detail;
  } catch {
    // A proxy error page, not JSON: the API is most likely not running.
    if (response.status >= 500) detail = "The forecast API is not reachable.";
  }
  throw new ApiError(detail, response.status);
}

export async function getJson<T>(path: string): Promise<T> {
  if (IS_STATIC) return staticGet<T>(path);
  return parse<T>(await fetch(path, { headers: { Accept: "application/json" } }));
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  if (IS_STATIC) return staticPost<T>(path, body);
  return parse<T>(
    await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

/** GET with caching and revalidation. Pass null to skip the request. */
export function useApi<T>(path: string | null, config?: SWRConfiguration<T, ApiError>) {
  return useSWR<T, ApiError>(path, getJson, { revalidateOnFocus: false, keepPreviousData: true, ...config });
}
