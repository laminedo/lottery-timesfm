"use client";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { PoolForecast } from "@/lib/api";
import { formatPercent } from "@/lib/format";

/** How far from the chance baseline the colors saturate, at least. Keeps tiny differences from looking loud. */
const MIN_SCALE = 0.25;

export function deviationScale(values: number[], baseline: number): number {
  return Math.max(MIN_SCALE, ...values.map((v) => Math.abs(v / baseline - 1)));
}

function cellStyle(value: number, baseline: number, scale: number) {
  const deviation = value / baseline - 1;
  const strength = Math.min(1, Math.abs(deviation) / scale);
  const pole = deviation >= 0 ? "var(--diverge-high)" : "var(--diverge-low)";
  return {
    background: `color-mix(in oklab, ${pole} ${Math.round(strength * 100)}%, var(--diverge-mid))`,
    color: strength < 0.75 ? "var(--cell-ink-weak)" : "var(--cell-ink-strong)",
  };
}

function signed(deviation: number): string {
  return `${deviation >= 0 ? "+" : "−"}${Math.abs(deviation * 100).toFixed(0)}%`;
}

/** One number per cell, colored by how far its probability sits above (warm) or below (cool) chance. */
export function Heatmap({
  pool,
  values,
  modelLabel,
  caption,
}: {
  pool: PoolForecast;
  /** Presence probability per number for the model being shown. */
  values: number[];
  modelLabel: string;
  caption: string;
}) {
  const scale = deviationScale(values, pool.baseline);
  return (
    <figure className="flex flex-col gap-2">
      <figcaption className="text-xs font-medium text-muted-foreground">{caption}</figcaption>
      <div className="grid grid-cols-7 gap-0.5 sm:grid-cols-10">
        {pool.numbers.map((n, i) => {
          const value = values[i];
          return (
            <Tooltip key={n.number}>
              <TooltipTrigger
                className="flex aspect-square items-center justify-center rounded-md text-sm font-semibold tabular-nums outline-none hover:ring-2 hover:ring-foreground/40 focus-visible:ring-2 focus-visible:ring-foreground"
                style={cellStyle(value, pool.baseline, scale)}
                aria-label={`${n.number}: ${formatPercent(value)} (${signed(value / pool.baseline - 1)} vs chance)`}
              >
                {n.number}
              </TooltipTrigger>
              <TooltipContent className="flex-col items-start gap-0.5">
                <div className="font-semibold">Number {n.number}</div>
                <div>
                  <b>{formatPercent(value)}</b> {modelLabel} · {signed(value / pool.baseline - 1)} vs chance
                </div>
                <div className="opacity-80">
                  TimesFM {formatPercent(n.timesfm)} · hot {formatPercent(n.hot)} · overdue {formatPercent(n.cold)}
                </div>
                {pool.informative && (
                  <div className="opacity-80">
                    TimesFM hit-rate band {formatPercent(n.rate_low)}–{formatPercent(n.rate_high)}
                  </div>
                )}
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>
      <ScaleLegend baseline={pool.baseline} scale={scale} />
    </figure>
  );
}

function ScaleLegend({ baseline, scale }: { baseline: number; scale: number }) {
  return (
    <div className="flex flex-col gap-1 text-xs text-muted-foreground">
      <div
        aria-hidden
        className="h-2 rounded-full"
        style={{ background: "linear-gradient(to right in oklab, var(--diverge-low), var(--diverge-mid), var(--diverge-high))" }}
      />
      <div className="flex justify-between tabular-nums">
        <span>{signed(-scale)} or lower</span>
        <span>chance ({formatPercent(baseline)})</span>
        <span>{signed(scale)} or higher</span>
      </div>
    </div>
  );
}

/** The heatmap's data as a table: every model side by side, sorted by the one being shown. */
export function HeatmapTable({
  pool,
  values,
  blendValues,
  modelLabel,
}: {
  pool: PoolForecast;
  /** Presence probability per number for the model being shown; sets the order and the "vs chance" column. */
  values: number[];
  blendValues: number[];
  modelLabel: string;
}) {
  const rows = pool.numbers.map((n, i) => ({ ...n, value: values[i], blend: blendValues[i] })).sort((a, b) => b.value - a.value);
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Number</TableHead>
          <TableHead className="text-right">Your blend</TableHead>
          <TableHead className="text-right">TimesFM</TableHead>
          <TableHead className="text-right">Hot</TableHead>
          <TableHead className="text-right">Overdue</TableHead>
          <TableHead className="text-right">{modelLabel} vs chance</TableHead>
          <TableHead className="text-right">TimesFM band</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.number} className="tabular-nums">
            <TableCell className="font-medium">{r.number}</TableCell>
            <TableCell className="text-right">{formatPercent(r.blend)}</TableCell>
            <TableCell className="text-right">{formatPercent(r.timesfm)}</TableCell>
            <TableCell className="text-right">{formatPercent(r.hot)}</TableCell>
            <TableCell className="text-right">{formatPercent(r.cold)}</TableCell>
            <TableCell className="text-right">{signed(r.value / pool.baseline - 1)}</TableCell>
            <TableCell className="text-right">
              {formatPercent(r.rate_low)}–{formatPercent(r.rate_high)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
