/**
 * Line sampling in the browser, for the static demo. Mirrors backend/app/forecast/sampler.py:
 * numbers are drawn without replacement in proportion to the blended distribution.
 */

/** A source of uniform random numbers in [0, 1). */
export type Random = () => number;

const FLOOR = 1e-12;

/** k distinct indices, each drawn in proportion to its weight among those left (Gumbel top-k). */
export function sampleWithoutReplacement(random: Random, weights: number[], k: number): number[] {
  if (k > weights.length) throw new Error(`Cannot draw ${k} distinct numbers from a pool of ${weights.length}`);
  const keyed = weights.map((w, index) => {
    const u = Math.max(random(), Number.MIN_VALUE);
    return { index, key: Math.log(Math.max(w, FLOOR)) - Math.log(-Math.log(u)) };
  });
  keyed.sort((a, b) => b.key - a.key);
  return keyed
    .slice(0, k)
    .map((x) => x.index)
    .sort((a, b) => a - b);
}

/** One index drawn in proportion to its weight. */
export function sampleOne(random: Random, weights: number[]): number {
  const total = weights.reduce((a, b) => a + Math.max(0, b), 0);
  let r = random() * total;
  for (let i = 0; i < weights.length; i++) {
    r -= Math.max(0, weights[i]);
    if (r < 0) return i;
  }
  return weights.length - 1;
}

export interface SampledLine {
  primary: number[];
  bonus: number | null;
  /** Geometric mean of p(number) / uniform over the line. */
  lift: number;
}

/**
 * `count` distinct lines. `main` and `bonus` are selection probabilities (each sums to 1) for balls
 * 1..n; `pick` main numbers per line, plus one bonus ball when `bonus` is given.
 */
export function generateLines(random: Random, main: number[], pick: number, bonus: number[] | null, count: number): SampledLine[] {
  const lines: SampledLine[] = [];
  const seen = new Set<string>();
  for (let attempt = 0; attempt < count * 50 && lines.length < count; attempt++) {
    const indices = sampleWithoutReplacement(random, main, pick);
    const primary = indices.map((i) => i + 1);
    const bonusBall = bonus ? sampleOne(random, bonus) + 1 : null;
    const key = `${primary.join(",")}|${bonusBall}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const meanLog = indices.reduce((sum, i) => sum + Math.log(Math.max(main[i], FLOOR) * main.length), 0) / pick;
    lines.push({ primary, bonus: bonusBall, lift: Math.exp(meanLog) });
  }
  return lines;
}
