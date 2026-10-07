/**
 * The API, answered from the JSON snapshot in /data. Used by the read-only demo build, which has no
 * server: reads map to files written by `python -m app.cli export-static`, and the two writes the app
 * makes (generate lines, start a backtest) are served from the same snapshot in the browser.
 */
import type { BacktestRun, DrawPage, Forecast, Game, Generated, StrategyKey, Trends, Weights } from "./api";
import { ApiError } from "./api-error.ts";
import { blend, normalizeWeights } from "./blend.ts";
import { BASE_PATH } from "./env.ts";
import { GAMES, type GameKey } from "./games.ts";
import { generateLines, type Random } from "./sampler.ts";
import { isoInZone, localDate, nextDrawAt } from "./schedule.ts";

async function file<T>(name: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_PATH}/data/${name}`);
  } catch {
    throw new ApiError("The demo data could not be loaded. Check your connection and reload.", 0);
  }
  if (!response.ok) {
    throw new ApiError(
      response.status === 404 ? "That item is not part of this demo snapshot." : `The demo data could not be loaded (${response.status}).`,
      response.status,
    );
  }
  return response.json() as Promise<T>;
}

/** The snapshot's game summary with the schedule brought up to now. */
export function withLiveSchedule(game: Game, now: Date = new Date()): Game {
  const next = nextDrawAt(game, now);
  // A jackpot estimate belongs to one draw; once that draw has passed it says nothing about the next.
  const current = game.next_jackpot && game.next_jackpot.draw_date >= localDate(next, game.timezone);
  return { ...game, next_draw_at: isoInZone(next, game.timezone), next_jackpot: current ? game.next_jackpot : null };
}

export interface GenerateBody {
  lines?: number;
  strategy?: StrategyKey;
  weights?: Weights;
  temperature?: number;
}

/** Sample lines from the snapshot's forecast, as the server would, without saving them anywhere. */
export function generateFrom(forecast: Forecast, game: Game, body: GenerateBody, random: Random = Math.random): Generated {
  const temperature = body.temperature ?? 1;
  const strategy = body.weights ? "custom" : (body.strategy ?? "balanced");
  const weights = body.weights ? normalizeWeights(body.weights) : forecast.strategies[body.strategy ?? "balanced"].weights;
  const main = blend(forecast.main, weights, temperature);
  const bonus = forecast.bonus ? blend(forecast.bonus, weights, temperature) : null;
  const band = forecast.main.sum?.quantiles;
  const lines = generateLines(random, main, forecast.main.pick, bonus, body.lines ?? 3).map((line) => {
    const sum = line.primary.reduce((a, b) => a + b, 0);
    return {
      primary_numbers: line.primary,
      bonus_number: line.bonus,
      lift: line.lift,
      sum,
      odd: line.primary.filter((n) => n % 2 === 1).length,
      sum_in_forecast_band: band ? sum >= band[0] && sum <= band[band.length - 1] : null,
    };
  });
  return {
    forecast_id: Date.now(),
    created_at: new Date().toISOString(),
    game: game.key,
    strategy,
    backend: forecast.backend,
    weights,
    temperature,
    seed: 0,
    saved: false,
    target_draw_at: isoInZone(nextDrawAt(game), game.timezone),
    lines,
    jackpot_odds: game.jackpot_odds,
  };
}

function route(path: string) {
  const url = new URL(path, "http://snapshot.invalid");
  const [, resource, id, section, action] = url.pathname.split("/").filter(Boolean);
  return { resource, id, section, action, query: url.searchParams };
}

export async function staticGet<T>(path: string): Promise<T> {
  const { resource, id, section, query } = route(path);
  if (resource === "health") return file<T>("health.json");
  if (resource === "backtests" && id) return file<T>(`backtests/${id}.json`);
  if (resource === "games" && !id) {
    const games = await Promise.all(GAMES.map((g) => file<Game>(`${g.key}/game.json`)));
    return games.map((g) => withLiveSchedule(g)) as T;
  }
  if (resource === "games" && id) {
    const key = id as GameKey;
    switch (section) {
      case undefined:
        return withLiveSchedule(await file<Game>(`${key}/game.json`)) as T;
      case "draws": {
        const all = await file<DrawPage>(`${key}/draws.json`);
        const limit = Number(query.get("limit") ?? 50);
        const offset = Number(query.get("offset") ?? 0);
        return { ...all, limit, offset, draws: all.draws.slice(offset, offset + limit) } as T;
      }
      case "trends": {
        const trends = await file<Trends>(`${key}/trends.json`);
        const series = trends.series.slice(-Number(query.get("window") ?? 200));
        return { ...trends, window: series.length, series } as T;
      }
      case "forecast": {
        const [forecast, game] = await Promise.all([file<Forecast>(`${key}/forecast.json`), file<Game>(`${key}/game.json`)]);
        return { ...forecast, target_draw_at: isoInZone(nextDrawAt(game), game.timezone) } as T;
      }
      case "forecasts":
        return [] as T; // the demo saves nothing
      case "metrics":
      case "accuracy":
      case "backtests":
        return file<T>(`${key}/${section}.json`);
    }
  }
  throw new ApiError("That is not available in the demo.", 404);
}

export async function staticPost<T>(path: string, body: unknown): Promise<T> {
  const { resource, id, section, action } = route(path);
  if (resource === "games" && id && section === "forecast" && action === "generate") {
    const [forecast, game] = await Promise.all([file<Forecast>(`${id}/forecast.json`), file<Game>(`${id}/game.json`)]);
    return generateFrom(forecast, game, body as GenerateBody) as T;
  }
  if (resource === "games" && id && section === "backtests") {
    const runs = await file<BacktestRun[]>(`${id}/backtests.json`);
    const wanted = (body as { draws?: number }).draws;
    const run = runs.find((r) => r.params.draws === wanted);
    if (!run) {
      const sizes = runs.map((r) => r.params.draws).sort((a, b) => a - b);
      throw new ApiError(`This demo includes backtests over ${sizes.join(", ")} draws only.`, 404);
    }
    return run as T;
  }
  throw new ApiError("That is not available in the demo.", 404);
}
