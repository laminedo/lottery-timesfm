"use client";

import { FlaskConical, LoaderCircle, Scale } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ErrorBar,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { mutate } from "swr";

import { BallRow } from "@/components/ball";
import { ChartCard } from "@/components/charts/chart-card";
import { AXIS_LINE, BAR_RADIUS, CURSOR_BAND, CURSOR_LINE, GRID, MAX_BAR, TICK, TooltipBox } from "@/components/charts/theme";
import { ErrorNote, LoadingBlock } from "@/components/state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress, ProgressLabel, ProgressValue } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { postJson, useApi, type BacktestResult, type BacktestRun, type Game, type StrategyKey } from "@/lib/api";
import { IS_STATIC } from "@/lib/env";
import { dateTickFormatter, formatDate, formatP, formatPercent } from "@/lib/format";
import type { GameKey } from "@/lib/games";
import { niceTicks } from "@/lib/scale";

const DRAW_OPTIONS = [25, 50, 100, 200];
const VISIBLE_ROWS = 15;

function signed(value: number, digits = 2): string {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(digits)}`;
}

/** The plain-language reading of the significance tests, including the multiple-comparison caveat. */
function Verdict({ result }: { result: BacktestResult }) {
  const flagged = result.strategies.filter((s) => !s.top_pick.consistent_with_chance);
  const n = result.strategies.length;
  const falseAlarm = 1 - Math.pow(0.95, n);
  return (
    <Alert>
      <Scale />
      <AlertTitle>
        {flagged.length === 0
          ? `No strategy is distinguishable from chance over these ${result.draws} draws`
          : `${flagged.map((s) => s.label).join(" and ")} ${flagged.length === 1 ? "differs" : "differ"} from chance at the 5% level`}
      </AlertTitle>
      <AlertDescription>
        {flagged.length === 0
          ? `Each strategy's best-guess line matched about as many numbers per draw as a random line would (${result.baseline.expected_matches.toFixed(2)}). That is what independent random draws predict.`
          : `Read this with care: with ${n} strategies tested, a result like this shows up in about ${formatPercent(falseAlarm, 0)} of backtests by chance alone, in either direction. It is not evidence of an edge unless it holds up across many more draws.`}
      </AlertDescription>
    </Alert>
  );
}

function StrategyTiles({ result }: { result: BacktestResult }) {
  const chance = result.baseline.expected_matches;
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {result.strategies.map((s) => (
        <div key={s.key} className="flex flex-col gap-1 rounded-xl bg-card p-4 ring-1 ring-foreground/10">
          <div className="text-xs font-medium text-muted-foreground">{s.label}</div>
          <div className="text-2xl leading-tight font-semibold">{s.top_pick.mean_matches.toFixed(2)}</div>
          <div className="text-xs text-muted-foreground">
            matches per draw · {signed(s.top_pick.mean_matches - chance)} vs chance · p = {formatP(s.top_pick.p_value)}
          </div>
        </div>
      ))}
    </div>
  );
}

function MeanChart({ result }: { result: BacktestResult }) {
  const chance = result.baseline.expected_matches;
  const rows = result.strategies.map((s) => ({
    label: s.label,
    mean: s.top_pick.mean_matches,
    lo: s.top_pick.ci95[0],
    hi: s.top_pick.ci95[1],
    ci: [s.top_pick.mean_matches - Math.max(0, s.top_pick.ci95[0]), s.top_pick.ci95[1] - s.top_pick.mean_matches],
    sampled: s.sampled.mean_matches,
    p: s.top_pick.p_value,
  }));
  const ticks = niceTicks(0, Math.max(chance, ...rows.map((r) => r.hi)));
  return (
    <ChartCard
      title="Average matches per draw"
      description={`Each strategy's single best-guess line, scored on ${result.draws} draws it had not seen. Whiskers show the 95% confidence interval; the line marks what a random line scores.`}
      legend={[
        { label: "Strategy's top pick", color: "var(--series-1)" },
        { label: `Chance (${chance.toFixed(2)})`, color: "var(--context)", mark: "line" },
      ]}
      table={
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Strategy</TableHead>
              <TableHead className="text-right">Top pick</TableHead>
              <TableHead className="text-right">95% interval</TableHead>
              <TableHead className="text-right">Sampled lines</TableHead>
              <TableHead className="text-right">Chance</TableHead>
              <TableHead className="text-right">p-value</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.label} className="tabular-nums">
                <TableCell className="font-medium">{r.label}</TableCell>
                <TableCell className="text-right">{r.mean.toFixed(3)}</TableCell>
                <TableCell className="text-right">
                  {r.lo.toFixed(2)}–{r.hi.toFixed(2)}
                </TableCell>
                <TableCell className="text-right">{r.sampled === null ? "n/a" : r.sampled.toFixed(3)}</TableCell>
                <TableCell className="text-right">{chance.toFixed(3)}</TableCell>
                <TableCell className="text-right">{formatP(r.p)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      }
    >
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 12, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="label" tick={TICK} axisLine={AXIS_LINE} tickLine={false} interval={0} />
            <YAxis
              tick={TICK}
              axisLine={false}
              tickLine={false}
              width={36}
              ticks={ticks}
              domain={[0, ticks[ticks.length - 1]]}
              tickFormatter={(v: number) => String(Number(v.toFixed(2)))}
            />
            <ChartTooltip
              cursor={CURSOR_BAND}
              isAnimationActive={false}
              content={({ active, payload }) => {
                const r = active && payload?.[0]?.payload;
                if (!r) return null;
                return (
                  <TooltipBox
                    title={r.label}
                    rows={[
                      { label: "matches per draw (top pick)", value: r.mean.toFixed(3), color: "var(--series-1)" },
                      { label: "by chance", value: chance.toFixed(3), color: "var(--context)" },
                    ]}
                    note={`95% interval ${r.lo.toFixed(2)}–${r.hi.toFixed(2)} · p = ${formatP(r.p)}`}
                  />
                );
              }}
            />
            <Bar dataKey="mean" fill="var(--series-1)" radius={BAR_RADIUS} maxBarSize={MAX_BAR} isAnimationActive={false}>
              <ErrorBar dataKey="ci" width={6} strokeWidth={1.5} stroke="var(--foreground)" />
            </Bar>
            <ReferenceLine y={chance} stroke="var(--context)" strokeWidth={2} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

function CumulativeChart({ result, selected }: { result: BacktestResult; selected: StrategyKey }) {
  const chance = result.baseline.expected_matches;
  const keys = result.strategies.map((s) => s.key);
  const labels = Object.fromEntries(result.strategies.map((s) => [s.key, s.label])) as Record<StrategyKey, string>;
  const rows = useMemo(() => {
    const totals = Object.fromEntries(keys.map((k) => [k, 0])) as Record<StrategyKey, number>;
    return result.timeline.map((step) => {
      const row: Record<string, number | string> = { date: step.date };
      for (const k of keys) {
        totals[k] += (step[k]?.matches ?? 0) - chance;
        row[k] = Number(totals[k].toFixed(3));
      }
      return row;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result]);
  const others = keys.filter((k) => k !== selected);
  const tickDate = dateTickFormatter(result.from ?? undefined, result.to ?? undefined);
  return (
    <ChartCard
      title="Running total against chance"
      description="Matches scored so far minus what chance would have scored by the same draw. A line that wanders around zero has no edge."
      legend={[
        { label: labels[selected], color: "var(--series-1)", mark: "line" },
        { label: "Other strategies", color: "var(--context)", mark: "line" },
      ]}
      table={
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Draw</TableHead>
              {keys.map((k) => (
                <TableHead key={k} className="text-right">
                  {labels[k]}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.date as string} className="tabular-nums">
                <TableCell>{formatDate(r.date as string)}</TableCell>
                {keys.map((k) => (
                  <TableCell key={k} className="text-right">
                    {signed(r[k] as number)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      }
    >
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 12, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="date" tick={TICK} axisLine={AXIS_LINE} tickLine={false} tickFormatter={tickDate} minTickGap={48} />
            <YAxis tick={TICK} axisLine={false} tickLine={false} width={36} />
            <ReferenceLine y={0} stroke="var(--chart-axis)" />
            <ChartTooltip
              cursor={CURSOR_LINE}
              isAnimationActive={false}
              content={({ active, payload, label }) => {
                const r = active && payload?.[0]?.payload;
                if (!r) return null;
                return (
                  <TooltipBox
                    title={formatDate(String(label))}
                    rows={[selected, ...others].map((k) => ({
                      label: labels[k],
                      value: signed(r[k]),
                      color: k === selected ? "var(--series-1)" : "var(--context)",
                    }))}
                    note="matches above or below chance so far"
                  />
                );
              }}
            />
            {others.map((k) => (
              <Line key={k} dataKey={k} type="linear" stroke="var(--context)" strokeWidth={1.5} dot={false} activeDot={false} isAnimationActive={false} />
            ))}
            <Line
              dataKey={selected}
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

function HistogramChart({ result, selected }: { result: BacktestResult; selected: StrategyKey }) {
  const strategy = result.strategies.find((s) => s.key === selected)!;
  const rows = strategy.top_pick.histogram.map((observed, matches) => ({
    matches,
    observed,
    expected: Number((result.baseline.match_pmf[matches] * result.draws).toFixed(2)),
  }));
  return (
    <ChartCard
      title="How many numbers matched"
      description={`Draws by number of matches for the ${strategy.label} top pick, next to the count chance predicts.`}
      legend={[
        { label: strategy.label, color: "var(--series-1)" },
        { label: "Expected by chance", color: "var(--context)" },
      ]}
      table={
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Matches</TableHead>
              <TableHead className="text-right">Draws</TableHead>
              <TableHead className="text-right">Expected by chance</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.matches} className="tabular-nums">
                <TableCell className="font-medium">{r.matches}</TableCell>
                <TableCell className="text-right">{r.observed}</TableCell>
                <TableCell className="text-right">{r.expected < 0.01 ? "< 0.01" : r.expected.toFixed(2)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      }
    >
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rows} margin={{ top: 12, right: 8, bottom: 0, left: 0 }} barGap={2}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="matches" tick={TICK} axisLine={AXIS_LINE} tickLine={false} />
            <YAxis tick={TICK} axisLine={false} tickLine={false} width={36} allowDecimals={false} />
            <ChartTooltip
              cursor={CURSOR_BAND}
              isAnimationActive={false}
              content={({ active, payload }) => {
                const r = active && payload?.[0]?.payload;
                if (!r) return null;
                return (
                  <TooltipBox
                    title={`${r.matches} ${r.matches === 1 ? "match" : "matches"}`}
                    rows={[
                      { label: "draws", value: r.observed, color: "var(--series-1)" },
                      { label: "expected by chance", value: r.expected < 0.01 ? "< 0.01" : r.expected.toFixed(1), color: "var(--context)" },
                    ]}
                  />
                );
              }}
            />
            <Bar dataKey="observed" fill="var(--series-1)" radius={BAR_RADIUS} maxBarSize={MAX_BAR} isAnimationActive={false} />
            <Bar dataKey="expected" fill="var(--context)" radius={BAR_RADIUS} maxBarSize={MAX_BAR} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

function BonusTable({ result, game }: { result: BacktestResult; game: Game }) {
  const rate = result.baseline.bonus_hit_rate;
  if (rate === null || !result.strategies[0]?.bonus) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{game.bonus_name} guesses</CardTitle>
        <CardDescription>
          How often each strategy&apos;s single most likely {game.bonus_name} was the one drawn. Chance is 1 in {Math.round(1 / rate)} (
          {formatPercent(rate)}).
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Strategy</TableHead>
              <TableHead className="text-right">Hits</TableHead>
              <TableHead className="text-right">Hit rate</TableHead>
              <TableHead className="text-right">Expected hits</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {result.strategies.map((s) => (
              <TableRow key={s.key} className="tabular-nums">
                <TableCell className="font-medium">{s.label}</TableCell>
                <TableCell className="text-right">
                  {s.bonus!.top_hits} of {s.bonus!.scored_draws}
                </TableCell>
                <TableCell className="text-right">{s.bonus!.top_hit_rate === null ? "n/a" : formatPercent(s.bonus!.top_hit_rate)}</TableCell>
                <TableCell className="text-right">{(rate * s.bonus!.scored_draws).toFixed(1)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function DrawTable({ result, selected, game }: { result: BacktestResult; selected: StrategyKey; game: Game }) {
  const [all, setAll] = useState(false);
  const label = result.strategies.find((s) => s.key === selected)!.label;
  const newestFirst = useMemo(() => [...result.timeline].reverse(), [result]);
  const rows = all ? newestFirst : newestFirst.slice(0, VISIBLE_ROWS);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Draw by draw</CardTitle>
        <CardDescription>
          The {label} top pick for each draw, made from earlier draws only, beside the numbers actually drawn. Matched numbers are ringed.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Draw</TableHead>
                <TableHead>Drawn</TableHead>
                <TableHead>{label} pick</TableHead>
                <TableHead className="text-right">Matches</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((step) => {
                const pick = step[selected];
                return (
                  <TableRow key={step.date}>
                    <TableCell className="whitespace-nowrap">{formatDate(step.date)}</TableCell>
                    <TableCell>
                      <BallRow numbers={step.actual} bonus={step.bonus} bonusName={game.bonus_name} size="sm" />
                    </TableCell>
                    <TableCell>
                      {pick && (
                        <BallRow
                          numbers={pick.line}
                          bonus={pick.bonus}
                          bonusName={game.bonus_name}
                          size="sm"
                          matches={step.actual}
                          bonusMatched={pick.bonus === undefined ? null : (pick.bonus_match ?? false)}
                        />
                      )}
                    </TableCell>
                    <TableCell className="text-right font-medium tabular-nums">{pick?.matches ?? "n/a"}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
        {newestFirst.length > VISIBLE_ROWS && (
          <Button variant="outline" size="sm" className="self-start" onClick={() => setAll((v) => !v)}>
            {all ? `Show the latest ${VISIBLE_ROWS}` : `Show all ${newestFirst.length} draws`}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

export function BacktestView({ game: key }: { game: GameKey }) {
  const listKey = `/api/games/${key}/backtests`;
  const { data: game } = useApi<Game>(`/api/games/${key}`);
  const { data: runs, error: listError } = useApi<BacktestRun[]>(listKey);
  const [draws, setDraws] = useState(100);
  const [chosenRun, setChosenRun] = useState<number | null>(null);
  const [selected, setSelected] = useState<StrategyKey>("balanced");
  const [starting, setStarting] = useState(false);
  const [failure, setFailure] = useState<Error | null>(null);

  // Watch the run just started; otherwise one still in progress; otherwise the latest finished one.
  const runId =
    chosenRun ??
    runs?.find((r) => r.status === "queued" || r.status === "running")?.run_id ??
    runs?.find((r) => r.status === "done")?.run_id ??
    null;
  const { data: run, error: runError } = useApi<BacktestRun>(runId ? `/api/backtests/${runId}` : null, {
    refreshInterval: (latest) => (latest && (latest.status === "done" || latest.status === "failed") ? 0 : 1000),
    keepPreviousData: false,
  });
  const finished = run?.status === "done" || run?.status === "failed";
  useEffect(() => {
    if (finished) {
      mutate(listKey);
      mutate(`/api/games/${key}/accuracy`);
    }
  }, [finished, listKey, key]);

  const start = async () => {
    setStarting(true);
    setFailure(null);
    try {
      const created = await postJson<BacktestRun>(listKey, { draws });
      setChosenRun(created.run_id);
    } catch (e) {
      setFailure(e as Error);
    } finally {
      setStarting(false);
    }
  };

  if (listError && !runs) return <ErrorNote error={listError} />;
  if (!runs || !game) return <LoadingBlock className="h-96" />;

  const running = run && !finished;
  const result = run?.status === "done" ? run.result : null;
  const strategyKey = result?.strategies.some((s) => s.key === selected) ? selected : (result?.strategies[0]?.key ?? selected);

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Walk-forward backtest</CardTitle>
          <CardDescription>
            Replays the most recent draws one at a time. Before each draw, every strategy forecasts it from earlier draws only, and its
            pick is scored against what was drawn.{" "}
            {IS_STATIC
              ? "This demo replays forecasts that were computed with the model in advance, so results appear at once."
              : "The first run forecasts each draw with the model (about 1–2 seconds per draw); results are cached, so reruns are instant."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <ToggleGroup
              variant="outline"
              spacing={0}
              aria-label="Draws to test"
              value={[String(draws)]}
              onValueChange={(v) => v.length > 0 && setDraws(Number(v[0]))}
            >
              {DRAW_OPTIONS.map((n) => (
                <ToggleGroupItem key={n} value={String(n)} className="px-3">
                  Last {n}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
            <Button size="lg" onClick={start} disabled={starting || !!running}>
              {starting || running ? <LoaderCircle className="animate-spin" /> : <FlaskConical />}
              {running ? "Running…" : "Run backtest"}
            </Button>
          </div>
          {running && (
            <Progress value={Math.round((run.progress ?? 0) * 100)}>
              <ProgressLabel>{run.message ?? "Starting"}</ProgressLabel>
              <ProgressValue />
            </Progress>
          )}
          {failure && <ErrorNote error={failure} />}
          {runError && <ErrorNote error={runError} />}
          {run?.status === "failed" && <ErrorNote error={new Error(run.error ?? "The backtest failed.")} action="Try running it again." />}
        </CardContent>
      </Card>

      {!result && !running && runs.length === 0 && (
        <p className="py-8 text-center text-sm text-muted-foreground">
          No backtest has been run for {game.name} yet. Run one to see how each strategy would have scored against chance.
        </p>
      )}
      {runId && !run && !runError && <LoadingBlock />}

      {result && (
        <>
          <p className="text-sm text-muted-foreground">
            {result.draws} draws from {formatDate(result.from!)} to {formatDate(result.to!)} · model: {result.backend.label} · one top-pick
            line per draw and strategy
          </p>
          <Verdict result={result} />
          <StrategyTiles result={result} />
          <MeanChart result={result} />
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-medium">Look closer at</span>
            <ToggleGroup
              variant="outline"
              spacing={0}
              aria-label="Strategy to inspect"
              value={[strategyKey]}
              onValueChange={(v) => v.length > 0 && setSelected(v[0] as StrategyKey)}
            >
              {result.strategies.map((s) => (
                <ToggleGroupItem key={s.key} value={s.key} className="px-3">
                  {s.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <CumulativeChart result={result} selected={strategyKey} />
            <HistogramChart result={result} selected={strategyKey} />
          </div>
          <BonusTable result={result} game={game} />
          <DrawTable result={result} selected={strategyKey} game={game} />
        </>
      )}
    </div>
  );
}
