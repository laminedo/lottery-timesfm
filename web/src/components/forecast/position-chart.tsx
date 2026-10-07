"use client";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { PositionForecast } from "@/lib/api";

const ORDINALS = ["Lowest", "2nd", "3rd", "4th", "5th", "6th"];

function positionLabel(position: number, count: number): string {
  if (position === count) return "Highest";
  return ORDINALS[position - 1] ?? `${position}th`;
}

/**
 * Where TimesFM expects each sorted position of the next draw to land: its 80% band and median on a
 * 1..pool track, with the long-run average of a fair draw marked for comparison.
 */
export function PositionChart({ positions, pool }: { positions: PositionForecast[]; pool: number }) {
  const at = (value: number) => `${((value - 1) / (pool - 1)) * 100}%`;
  const ticks = [1, Math.round(pool / 4), Math.round(pool / 2), Math.round((3 * pool) / 4), pool];
  return (
    <div className="flex flex-col gap-2">
      {positions.map((p) => {
        const [q10, , , , median, , , , q90] = p.quantiles;
        return (
          <div key={p.position} className="grid grid-cols-[4.5rem_1fr] items-center gap-3">
            <span className="text-xs text-muted-foreground">{positionLabel(p.position, positions.length)}</span>
            <Tooltip>
              <TooltipTrigger className="relative h-7 w-full rounded-md outline-none focus-visible:ring-2 focus-visible:ring-foreground">
                <span aria-hidden className="absolute inset-x-0 top-1/2 h-px bg-[var(--chart-grid)]" />
                <span
                  aria-hidden
                  className="absolute top-1/2 h-3 -translate-y-1/2 rounded-full bg-[var(--series-1-wash)] ring-1 ring-[var(--series-1)]/40"
                  style={{ left: at(q10), width: `calc(${at(q90)} - ${at(q10)})` }}
                />
                <span
                  aria-hidden
                  className="absolute top-1/2 h-4 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[var(--context)]"
                  style={{ left: at(p.expected) }}
                />
                <span
                  aria-hidden
                  className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[var(--series-1)] ring-2 ring-card"
                  style={{ left: at(median) }}
                />
              </TooltipTrigger>
              <TooltipContent className="flex-col items-start gap-0.5">
                <div className="font-semibold">{positionLabel(p.position, positions.length)} number</div>
                <div>
                  <b>{median.toFixed(1)}</b> TimesFM median · 80% band {q10.toFixed(0)}–{q90.toFixed(0)}
                </div>
                <div className="opacity-80">{p.expected.toFixed(1)} is the fair-draw average</div>
              </TooltipContent>
            </Tooltip>
          </div>
        );
      })}
      <div className="grid grid-cols-[4.5rem_1fr] gap-3">
        <span />
        <div className="relative h-4 text-xs text-[var(--ink-muted)] tabular-nums">
          {ticks.map((t) => (
            <span key={t} className="absolute -translate-x-1/2" style={{ left: at(t) }}>
              {t}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

export function PositionTable({ positions }: { positions: PositionForecast[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Position</TableHead>
          <TableHead className="text-right">10%</TableHead>
          <TableHead className="text-right">Median</TableHead>
          <TableHead className="text-right">90%</TableHead>
          <TableHead className="text-right">Fair-draw average</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {positions.map((p) => (
          <TableRow key={p.position} className="tabular-nums">
            <TableCell className="font-medium">{positionLabel(p.position, positions.length)}</TableCell>
            <TableCell className="text-right">{p.quantiles[0].toFixed(1)}</TableCell>
            <TableCell className="text-right">{p.quantiles[4].toFixed(1)}</TableCell>
            <TableCell className="text-right">{p.quantiles[8].toFixed(1)}</TableCell>
            <TableCell className="text-right">{p.expected.toFixed(1)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
