/**
 * Generated lines kept in the browser, for the hosted site (which has no server to keep them).
 * They are scored here too, against the draw results the site ships with.
 */
import type { Accuracy, Draw, StoredForecast } from "./api";

/** The part of localStorage this needs. Tests pass a plain object. */
export interface KeyValueStore {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export interface SavedForecast {
  forecast_id: number;
  created_at: string;
  target_draw_date: string;
  strategy: string;
  backend: string;
  lines: { primary_numbers: number[]; bonus_number: number | null }[];
}

const MAX_SAVED = 40; // per game; the oldest are dropped first
const keyFor = (game: string) => `forecast-lab:lines:${game}`;

/** localStorage, or null where it is unavailable (private windows, blocked site data, the server). */
export function browserStore(): KeyValueStore | null {
  try {
    const store = globalThis.localStorage;
    store.getItem("forecast-lab:probe");
    return store;
  } catch {
    return null;
  }
}

/** Saved forecasts for a game, newest first. Unreadable data counts as none. */
export function loadSaved(store: KeyValueStore | null, game: string): SavedForecast[] {
  if (!store) return [];
  try {
    const parsed: unknown = JSON.parse(store.getItem(keyFor(game)) ?? "[]");
    return Array.isArray(parsed) ? (parsed as SavedForecast[]) : [];
  } catch {
    return [];
  }
}

/** Keep a forecast. Returns false when the browser will not store it. */
export function saveForecast(store: KeyValueStore | null, game: string, forecast: SavedForecast): boolean {
  if (!store) return false;
  try {
    store.setItem(keyFor(game), JSON.stringify([forecast, ...loadSaved(store, game)].slice(0, MAX_SAVED)));
    return true;
  } catch {
    return false; // storage full or refused
  }
}

export function clearSaved(store: KeyValueStore | null, game: string): void {
  try {
    store?.removeItem(keyFor(game));
  } catch {
    // nothing to clear
  }
}

/** Score saved forecasts against the results: a line is scored once its target draw is in `draws`. */
export function scoreSaved(saved: SavedForecast[], draws: Draw[]): StoredForecast[] {
  const byDate = new Map(draws.map((d) => [d.draw_date, d]));
  return saved.map((f) => {
    const draw = byDate.get(f.target_draw_date) ?? null;
    return {
      forecast_id: f.forecast_id,
      created_at: f.created_at,
      target_draw_date: f.target_draw_date,
      strategy: f.strategy,
      backend: f.backend,
      draw: draw && { primary_numbers: draw.primary_numbers, bonus_number: draw.bonus_number },
      lines: f.lines.map((line) => ({
        primary_numbers: line.primary_numbers,
        bonus_number: line.bonus_number,
        scored: draw !== null,
        main_matches: draw ? line.primary_numbers.filter((n) => draw.primary_numbers.includes(n)).length : null,
        bonus_match: draw && line.bonus_number !== null ? line.bonus_number === draw.bonus_number : null,
      })),
    };
  });
}

/** The accuracy tracker's summary of scored lines, shaped like the API's. */
export function liveAccuracy(scored: StoredForecast[]): Accuracy["live"] {
  const groups = new Map<string, { scored: number; pending: number; matches: number; best: number | null; bonus_hits: number }>();
  for (const forecast of scored) {
    const g = groups.get(forecast.strategy) ?? { scored: 0, pending: 0, matches: 0, best: null, bonus_hits: 0 };
    for (const line of forecast.lines) {
      if (line.scored && line.main_matches !== null) {
        g.scored += 1;
        g.matches += line.main_matches;
        g.best = Math.max(g.best ?? 0, line.main_matches);
        if (line.bonus_match) g.bonus_hits += 1;
      } else {
        g.pending += 1;
      }
    }
    groups.set(forecast.strategy, g);
  }
  const rows = [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
  const total = rows.reduce((sum, [, g]) => sum + g.scored, 0);
  const matches = rows.reduce((sum, [, g]) => sum + g.matches, 0);
  return {
    scored_lines: total,
    pending_lines: rows.reduce((sum, [, g]) => sum + g.pending, 0),
    mean_matches: total > 0 ? matches / total : null,
    by_strategy: rows.map(([strategy, g]) => ({
      strategy,
      scored: g.scored,
      pending: g.pending,
      mean_matches: g.scored > 0 ? g.matches / g.scored : null,
      best: g.best,
      bonus_hits: g.bonus_hits,
    })),
  };
}
