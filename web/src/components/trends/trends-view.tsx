"use client";

import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Ball, bonusKind } from "@/components/ball";
import { ChartCard } from "@/components/charts/chart-card";
import { AXIS_LINE, BAR_RADIUS, CURSOR_BAND, CURSOR_LINE, GRID, MAX_BAR, TICK, TooltipBox } from "@/components/charts/theme";
import { ErrorNote, LoadingBlock } from "@/components/state";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { useApi, type DistributionRow, type Game, type Metrics, type PoolMetrics, type Trends } from "@/lib/api";
import { dateTickFormatter, formatDate, formatInt, formatP, formatPercent } from "@/lib/format";
import type { GameKey } from "@/lib/games";
import { niceTicks } from "@/lib/scale";

const WINDOWS = [100, 200, 500];
const MARGIN = { top: 12, right: 8, bottom: 0, left: 0 };

function uniformityNote(pool: PoolMetrics, what: string): string {
  const p = pool.uniformity.p_value;
  if (p === null) return "";
  const verdict =
    p >= 0.05
      ? "the counts are consistent with every number being equally likely"
      : "the counts are more uneven than usual for fair draws; across several games and pools a result like this turns up by chance now and then";
  return `Chi-square test over ${formatInt(pool.draws)} draws of the ${what}: p = ${formatP(p)}, so ${verdict}.`;
}

function FrequencyChart({ pool, title, what }: { pool: PoolMetrics; title: string; what: string }) {
  return (
    <ChartCard
      title={title}
      description={`How many times each number has been drawn. A fair draw gives every number about ${pool.expected_count.toFixed(0)} appearances; the spread around that line is ordinary random variation.`}
      legend={[
        { label: "Times drawn", color: "var(--series-1)" },
        { label: `Expected (${pool.expected_count.toFixed(1)})`, color: "var(--context)", mark: "line" },
      ]}
      footer={uniformityNote(pool, what)}
      table={
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Number</TableHead>
              <TableHead className="text-right">Drawn</TableHead>
              <TableHead className="text-right">vs expected</TableHead>
              <TableHead className="text-right">Last 30</TableHead>
              <TableHead className="text-right">Draws since</TableHead>
              <TableHead className="text-right">Average wait</TableHead>
              <TableHead className="text-right">Longest wait</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pool.numbers.map((n) => (
              <TableRow key={n.number} className="tabular-nums">
                <TableCell className="font-medium">{n.number}</TableCell>
                <TableCell className="text-right">{n.count}</TableCell>
                <TableCell className="text-right">
                  {n.z_score >= 0 ? "+" : "−"}
                  {Math.abs(n.z_score).toFixed(1)} sd
                </TableCell>
                <TableCell className="text-right">{n.hits_30}</TableCell>
                <TableCell className="text-right">{n.current_gap}</TableCell>
                <TableCell className="text-right">{n.mean_gap === null ? "n/a" : n.mean_gap.toFixed(1)}</TableCell>
                <TableCell className="text-right">{n.max_gap}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      }
    >
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={pool.numbers} margin={MARGIN} barCategoryGap={2}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="number" tick={TICK} axisLine={AXIS_LINE} tickLine={false} minTickGap={12} />
            <YAxis tick={TICK} axisLine={false} tickLine={false} width={36} allowDecimals={false} />
            <ChartTooltip
              cursor={CURSOR_BAND}
              isAnimationActive={false}
              content={({ active, payload }) => {
                const n = active && payload?.[0]?.payload;
                if (!n) return null;
                return (
                  <TooltipBox
                    title={`Number ${n.number}`}
                    rows={[
                      { label: "times drawn", value: n.count, color: "var(--series-1)" },
                      { label: "expected", value: pool.expected_count.toFixed(1), color: "var(--context)" },
                    ]}
                    note={`${n.hits_30} in the last 30 draws · last seen ${n.current_gap === 0 ? "in the latest draw" : `${n.current_gap} draws ago`}`}
                  />
                );
              }}
            />
            <Bar dataKey="count" fill="var(--series-1)" radius={BAR_RADIUS} maxBarSize={MAX_BAR} isAnimationActive={false} />
            <ReferenceLine y={pool.expected_count} stroke="var(--context)" strokeWidth={2} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

function HotCold({ metrics, game }: { metrics: Metrics; game: Game }) {
  const byNumber = new Map(metrics.main.numbers.map((n) => [n.number, n]));
  const row = (numbers: number[], detail: (n: number) => string) => (
    <ul className="flex flex-wrap gap-x-3 gap-y-2">
      {numbers.map((n) => (
        <li key={n} className="flex flex-col items-center gap-0.5">
          <Ball n={n} />
          <span className="text-[0.7rem] text-muted-foreground tabular-nums">{detail(n)}</span>
        </li>
      ))}
    </ul>
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>Hot and cold numbers</CardTitle>
        <CardDescription>
          Hot numbers appeared most in the last 30 draws; cold numbers have waited longest. On average a number waits{" "}
          {metrics.main.expected_gap.toFixed(1)} draws between appearances. Neither list changes a number&apos;s odds in the next draw.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium">Hot · hits in the last 30 draws</span>
          {row(metrics.main.hot, (n) => `${byNumber.get(n)?.hits_30 ?? 0}×`)}
        </div>
        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium">Cold · draws since last seen</span>
          {row(metrics.main.cold, (n) => `${byNumber.get(n)?.current_gap ?? 0}`)}
        </div>
        {metrics.bonus && (
          <div className="flex flex-col gap-2 sm:col-span-2">
            <span className="text-sm font-medium">
              {game.bonus_name} · longest waits (since {formatDate(metrics.bonus.since ?? game.main_since)})
            </span>
            <ul className="flex flex-wrap gap-x-3 gap-y-2">
              {metrics.bonus.cold.slice(0, 6).map((n) => (
                <li key={n} className="flex flex-col items-center gap-0.5">
                  <Ball n={n} kind={bonusKind(game.bonus_name)} />
                  <span className="text-[0.7rem] text-muted-foreground tabular-nums">
                    {metrics.bonus!.numbers.find((x) => x.number === n)?.current_gap ?? 0}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function DistributionChart({
  title,
  description,
  rows,
  labelKey,
  label,
  footer,
}: {
  title: string;
  description: string;
  rows: DistributionRow[];
  labelKey: string;
  label: (value: number) => string;
  footer?: string;
}) {
  const data = rows.map((r) => ({ ...r, name: label(r[labelKey]) }));
  const ticks = niceTicks(0, Math.max(...rows.map((r) => Math.max(r.observed_share, r.expected_share))));
  return (
    <ChartCard
      title={title}
      description={description}
      legend={[
        { label: "Share of draws", color: "var(--series-1)" },
        { label: "Expected by chance", color: "var(--context)" },
      ]}
      footer={footer}
      table={
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Split</TableHead>
              <TableHead className="text-right">Draws</TableHead>
              <TableHead className="text-right">Share</TableHead>
              <TableHead className="text-right">Expected share</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.map((r) => (
              <TableRow key={r.name} className="tabular-nums">
                <TableCell className="font-medium">{r.name}</TableCell>
                <TableCell className="text-right">{formatInt(r.observed)}</TableCell>
                <TableCell className="text-right">{formatPercent(r.observed_share)}</TableCell>
                <TableCell className="text-right">{formatPercent(r.expected_share)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      }
    >
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={MARGIN} barGap={2}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="name" tick={TICK} axisLine={AXIS_LINE} tickLine={false} interval={0} />
            <YAxis
              tick={TICK}
              axisLine={false}
              tickLine={false}
              width={40}
              ticks={ticks}
              domain={[0, ticks[ticks.length - 1]]}
              tickFormatter={(v: number) => formatPercent(v, 0)}
            />
            <ChartTooltip
              cursor={CURSOR_BAND}
              isAnimationActive={false}
              content={({ active, payload }) => {
                const r = active && payload?.[0]?.payload;
                if (!r) return null;
                return (
                  <TooltipBox
                    title={r.name}
                    rows={[
                      { label: `of draws (${formatInt(r.observed)})`, value: formatPercent(r.observed_share), color: "var(--series-1)" },
                      { label: "expected by chance", value: formatPercent(r.expected_share), color: "var(--context)" },
                    ]}
                  />
                );
              }}
            />
            <Bar dataKey="observed_share" fill="var(--series-1)" radius={BAR_RADIUS} maxBarSize={MAX_BAR} isAnimationActive={false} />
            <Bar dataKey="expected_share" fill="var(--context)" radius={BAR_RADIUS} maxBarSize={MAX_BAR} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

function SumHistogram({ trends }: { trends: Trends }) {
  const data = trends.sums.histogram.map((b) => ({ ...b, name: b.from === b.to ? `${b.from}` : `${b.from}–${b.to}` }));
  const s = trends.sums;
  return (
    <ChartCard
      title="Historical sum ranges"
      description="Draws by the sum of their numbers. Sums cluster in the middle because far more combinations add up to a middling total than to an extreme one."
      legend={[
        { label: "Draws", color: "var(--series-1)" },
        { label: "Expected by chance", color: "var(--context)", mark: "line" },
      ]}
      footer={
        s.mean !== null && s.sd !== null
          ? `Observed average ${s.mean.toFixed(1)} (sd ${s.sd.toFixed(1)}), range ${s.min}–${s.max}. A fair draw averages ${s.expected_mean.toFixed(1)} (sd ${s.expected_sd.toFixed(1)}).`
          : undefined
      }
      table={
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Sum</TableHead>
              <TableHead className="text-right">Draws</TableHead>
              <TableHead className="text-right">Expected</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.map((b) => (
              <TableRow key={b.name} className="tabular-nums">
                <TableCell className="font-medium">{b.name}</TableCell>
                <TableCell className="text-right">{b.observed}</TableCell>
                <TableCell className="text-right">{b.expected.toFixed(1)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      }
    >
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={MARGIN} barCategoryGap={2}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="name" tick={TICK} axisLine={AXIS_LINE} tickLine={false} minTickGap={24} />
            <YAxis tick={TICK} axisLine={false} tickLine={false} width={36} allowDecimals={false} />
            <ChartTooltip
              cursor={CURSOR_BAND}
              isAnimationActive={false}
              content={({ active, payload }) => {
                const b = active && payload?.[0]?.payload;
                if (!b) return null;
                return (
                  <TooltipBox
                    title={`Sum ${b.name}`}
                    rows={[
                      { label: "draws", value: b.observed, color: "var(--series-1)" },
                      { label: "expected by chance", value: b.expected.toFixed(1), color: "var(--context)" },
                    ]}
                  />
                );
              }}
            />
            <Bar dataKey="observed" fill="var(--series-1)" radius={BAR_RADIUS} maxBarSize={MAX_BAR} isAnimationActive={false} />
            <Line dataKey="expected" type="monotone" stroke="var(--context)" strokeWidth={2} dot={false} activeDot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

function RollingChart({
  title,
  description,
  trends,
  dataKey,
  rawKey,
  expected,
  unit,
  digits,
}: {
  title: string;
  description: string;
  trends: Trends;
  dataKey: "sum_avg" | "odd_avg" | "high_avg" | "consecutive_avg";
  rawKey: "sum" | "odd" | "high" | "consecutive";
  expected: number;
  unit: string;
  digits: number;
}) {
  const values = trends.series.map((r) => r[dataKey]);
  const ticks = niceTicks(Math.min(expected, ...values), Math.max(expected, ...values));
  const tickDate = dateTickFormatter(trends.series[0]?.date, trends.series[trends.series.length - 1]?.date);
  return (
    <ChartCard
      title={title}
      description={description}
      legend={[
        { label: `${trends.rolling_window}-draw average`, color: "var(--series-1)", mark: "line" },
        { label: `Expected (${expected.toFixed(digits)})`, color: "var(--context)", mark: "line" },
      ]}
      table={
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Draw</TableHead>
              <TableHead className="text-right">This draw</TableHead>
              <TableHead className="text-right">{trends.rolling_window}-draw average</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {[...trends.series].reverse().map((r) => (
              <TableRow key={r.date} className="tabular-nums">
                <TableCell>{formatDate(r.date)}</TableCell>
                <TableCell className="text-right">{r[rawKey]}</TableCell>
                <TableCell className="text-right">{r[dataKey].toFixed(digits)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      }
    >
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={trends.series} margin={MARGIN}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="date" tick={TICK} axisLine={AXIS_LINE} tickLine={false} tickFormatter={tickDate} minTickGap={48} />
            <YAxis
              tick={TICK}
              axisLine={false}
              tickLine={false}
              width={40}
              ticks={ticks}
              domain={[ticks[0], ticks[ticks.length - 1]]}
              tickFormatter={(v: number) => String(Number(v.toFixed(2)))}
            />
            <ChartTooltip
              cursor={CURSOR_LINE}
              isAnimationActive={false}
              content={({ active, payload }) => {
                const r = active && payload?.[0]?.payload;
                if (!r) return null;
                return (
                  <TooltipBox
                    title={formatDate(r.date)}
                    rows={[
                      { label: `${trends.rolling_window}-draw average`, value: r[dataKey].toFixed(digits), color: "var(--series-1)" },
                      { label: "expected", value: expected.toFixed(digits), color: "var(--context)" },
                    ]}
                    note={`This draw: ${r[rawKey]} ${unit}`}
                  />
                );
              }}
            />
            <ReferenceLine y={expected} stroke="var(--context)" strokeWidth={2} />
            <Line
              dataKey={dataKey}
              type="linear"
              stroke="var(--series-1)"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, stroke: "var(--card)", strokeWidth: 2 }}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

export function TrendsView({ game: key }: { game: GameKey }) {
  const [window, setWindow] = useState(200);
  const { data: game } = useApi<Game>(`/api/games/${key}`);
  const { data: metrics, error: metricsError } = useApi<Metrics>(`/api/games/${key}/metrics`);
  const { data: trends, error: trendsError, isValidating } = useApi<Trends>(`/api/games/${key}/trends?window=${window}`);

  const error = metricsError ?? trendsError;
  if (error && (!metrics || !trends)) return <ErrorNote error={error} />;
  if (!metrics || !trends || !game) return <LoadingBlock className="h-96" />;

  const pick = game.pick;
  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-base font-semibold">All {formatInt(trends.draws)} draws</h2>
      <FrequencyChart pool={metrics.main} title="Number frequency" what="main numbers" />
      {metrics.bonus && <FrequencyChart pool={metrics.bonus} title={`${game.bonus_name} frequency`} what={game.bonus_name ?? "bonus ball"} />}
      <HotCold metrics={metrics} game={game} />
      <div className="grid gap-4 lg:grid-cols-2">
        <DistributionChart
          title="Odd / even ratio"
          description="Share of draws by how many of the numbers were odd."
          rows={trends.odd_even.distribution}
          labelKey="odd"
          label={(odd) => `${odd}/${pick - odd}`}
          footer={`Read each label as odd/even. Average odd numbers per draw: ${trends.odd_even.mean_odd?.toFixed(2)} (expected ${trends.odd_even.expected_odd.toFixed(2)}).`}
        />
        <DistributionChart
          title="High / low split"
          description={`Share of draws by how many numbers were high (${trends.high_low.split_at + 1}–${game.pool}) rather than low (1–${trends.high_low.split_at}).`}
          rows={trends.high_low.distribution}
          labelKey="high"
          label={(high) => `${high}/${pick - high}`}
          footer={`Read each label as high/low. Average high numbers per draw: ${trends.high_low.mean_high?.toFixed(2)} (expected ${trends.high_low.expected_high.toFixed(2)}).`}
        />
        <DistributionChart
          title="Consecutive numbers"
          description="Share of draws by how many adjacent pairs they contain, such as 17 and 18."
          rows={trends.consecutive.distribution}
          labelKey="pairs"
          label={(pairs) => `${pairs}`}
          footer={`${formatPercent(trends.consecutive.share_with_any ?? 0)} of draws had at least one adjacent pair; chance predicts ${formatPercent(trends.consecutive.expected_share_with_any)}.`}
        />
        <SumHistogram trends={trends} />
      </div>

      <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold">Over time</h2>
        <ToggleGroup
          variant="outline"
          spacing={0}
          aria-label="Draws shown in the time charts"
          value={[String(window)]}
          onValueChange={(v) => v.length > 0 && setWindow(Number(v[0]))}
        >
          {WINDOWS.map((n) => (
            <ToggleGroupItem key={n} value={String(n)} className="px-3">
              Last {n} draws
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      </div>
      <div className={`grid gap-4 lg:grid-cols-2 ${isValidating ? "opacity-60" : ""}`}>
        <RollingChart
          title="Line sum over time"
          description="The moving average of the draw sum, against the long-run average of a fair draw."
          trends={trends}
          dataKey="sum_avg"
          rawKey="sum"
          expected={trends.sums.expected_mean}
          unit="total"
          digits={1}
        />
        <RollingChart
          title="Odd numbers over time"
          description="The moving average of odd numbers per draw."
          trends={trends}
          dataKey="odd_avg"
          rawKey="odd"
          expected={trends.odd_even.expected_odd}
          unit="odd"
          digits={2}
        />
        <RollingChart
          title="High numbers over time"
          description="The moving average of high numbers per draw."
          trends={trends}
          dataKey="high_avg"
          rawKey="high"
          expected={trends.high_low.expected_high}
          unit="high"
          digits={2}
        />
        <RollingChart
          title="Adjacent pairs over time"
          description="The moving average of consecutive-number pairs per draw."
          trends={trends}
          dataKey="consecutive_avg"
          rawKey="consecutive"
          expected={trends.consecutive.distribution.reduce((sum, r) => sum + r.pairs * r.expected_share, 0)}
          unit="pairs"
          digits={2}
        />
      </div>
    </div>
  );
}
