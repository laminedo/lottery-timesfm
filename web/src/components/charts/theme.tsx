"use client";

import type { ReactNode } from "react";

/* Shared Recharts styling: recessive solid hairlines, muted axis text, thin marks. */

export const TICK = { fill: "var(--ink-muted)", fontSize: 12 } as const;
export const GRID = { stroke: "var(--chart-grid)", strokeDasharray: "0", vertical: false } as const;
export const AXIS_LINE = { stroke: "var(--chart-axis)" } as const;
export const BAR_RADIUS: [number, number, number, number] = [4, 4, 0, 0];
export const MAX_BAR = 24;
export const CURSOR_BAND = { fill: "var(--foreground)", fillOpacity: 0.05 } as const;
export const CURSOR_LINE = { stroke: "var(--chart-axis)", strokeWidth: 1 } as const;

interface Row {
  label: string;
  value: ReactNode;
  color?: string;
}

/** Tooltip body: the value leads in strong ink, the series name follows, keyed by a short stroke. */
export function TooltipBox({ title, rows, note }: { title?: ReactNode; rows: Row[]; note?: ReactNode }) {
  return (
    <div className="rounded-lg bg-popover px-3 py-2 text-xs shadow-md ring-1 ring-foreground/10">
      {title && <div className="mb-1 font-medium text-foreground">{title}</div>}
      <ul className="flex flex-col gap-0.5">
        {rows.map((row) => (
          <li key={row.label} className="flex items-center gap-2">
            {row.color && <span aria-hidden className="h-0.5 w-3 rounded-full" style={{ background: row.color }} />}
            <span className="font-semibold text-foreground tabular-nums">{row.value}</span>
            <span className="text-muted-foreground">{row.label}</span>
          </li>
        ))}
      </ul>
      {note && <div className="mt-1 text-muted-foreground">{note}</div>}
    </div>
  );
}
