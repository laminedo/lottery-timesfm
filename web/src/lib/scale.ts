/** Round axis ticks (steps of 1, 2, 2.5 or 5 times a power of ten) that cover min..max. */
export function niceTicks(min: number, max: number, target = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
  if (max <= min) max = min + 1;
  const raw = (max - min) / Math.max(1, target - 1);
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw - 1e-12) ?? 10 * magnitude;
  const ticks: number[] = [];
  for (let v = Math.floor(min / step + 1e-9) * step; v < max + step - 1e-9; v += step) ticks.push(Number(v.toFixed(10)));
  return ticks;
}
