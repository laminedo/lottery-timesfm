"use client";

import { ChartColumn, Table2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export interface LegendItem {
  label: string;
  color: string;
  /** rect for bars and fills, line for lines, dot for markers. */
  mark?: "rect" | "line" | "dot";
}

/** Identity for two or more series: a mark in the series color beside ink-colored text. */
export function Legend({ items }: { items: LegendItem[] }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-1.5">
          <span
            aria-hidden
            className={item.mark === "line" ? "h-0.5 w-4 rounded-full" : item.mark === "dot" ? "size-2 rounded-full" : "size-2.5 rounded-[2px]"}
            style={{ background: item.color }}
          />
          {item.label}
        </li>
      ))}
    </ul>
  );
}

/**
 * The frame every chart sits in: title, what it shows, legend, and a switch to the same data as a table
 * so no value is reachable only by hovering.
 */
export function ChartCard({
  title,
  description,
  legend,
  table,
  children,
  footer,
}: {
  title: string;
  description?: ReactNode;
  legend?: LegendItem[];
  table?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const [showTable, setShowTable] = useState(false);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
        {table && (
          <CardAction>
            <Button variant="ghost" size="sm" onClick={() => setShowTable((v) => !v)} aria-pressed={showTable}>
              {showTable ? <ChartColumn /> : <Table2 />}
              {showTable ? "Chart" : "Table"}
            </Button>
          </CardAction>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {legend && legend.length > 1 && !showTable && <Legend items={legend} />}
        {showTable && table ? <div className="max-h-96 overflow-auto">{table}</div> : children}
        {footer && <div className="text-xs text-muted-foreground">{footer}</div>}
      </CardContent>
    </Card>
  );
}
