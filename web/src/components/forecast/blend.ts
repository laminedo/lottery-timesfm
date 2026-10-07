import type { Component, PoolForecast, Weights } from "@/lib/api";

export const COMPONENTS: Component[] = ["timesfm", "hot", "cold", "uniform"];
export const COMPONENT_LABELS: Record<Component, string> = {
  timesfm: "TimesFM core",
  hot: "Hot (recent hits)",
  cold: "Overdue (long gaps)",
  uniform: "Pure chance",
};
export const MIN_TEMPERATURE = 0.2;
export const MAX_TEMPERATURE = 3;

function normalized(values: number[]): number[] {
  const total = values.reduce((a, b) => a + Math.max(0, b), 0);
  return total > 0 ? values.map((v) => Math.max(0, v) / total) : values.map(() => 1 / values.length);
}

export function normalizeWeights(weights: Weights): Weights {
  const [timesfm, hot, cold, uniform] = normalized(COMPONENTS.map((c) => weights[c]));
  return { timesfm, hot, cold, uniform };
}

/**
 * The sampling distribution for a pool: the weighted mix of the model components, sharpened or
 * flattened by temperature. Mirrors `blend` in backend/app/forecast/sampler.py. Sums to 1.
 */
export function blend(pool: PoolForecast, weights: Weights, temperature: number): number[] {
  const w = normalizeWeights(weights);
  const parts: Record<Component, number[]> = {
    timesfm: normalized(pool.numbers.map((n) => n.timesfm)),
    hot: normalized(pool.numbers.map((n) => n.hot)),
    cold: normalized(pool.numbers.map((n) => n.cold)),
    uniform: pool.numbers.map(() => 1 / pool.pool),
  };
  const mix = pool.numbers.map((_, i) => COMPONENTS.reduce((sum, c) => sum + w[c] * parts[c][i], 0));
  const t = Math.min(Math.max(temperature, MIN_TEMPERATURE), 5);
  return normalized(mix.map((p) => Math.pow(Math.max(p, 1e-12), 1 / t)));
}

/** Selection probabilities (sum 1) as presence probabilities (sum = pick), the scale the heatmap uses. */
export function toPresence(probabilities: number[], pick: number): number[] {
  return probabilities.map((p) => Math.min(1, p * pick));
}
