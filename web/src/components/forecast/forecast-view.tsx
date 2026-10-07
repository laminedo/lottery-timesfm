"use client";

import { Check, Dices, LoaderCircle } from "lucide-react";
import Link from "next/link";
import { useId, useMemo, useState } from "react";

import { BallRow } from "@/components/ball";
import { ChartCard } from "@/components/charts/chart-card";
import { ErrorNote, LoadingBlock } from "@/components/state";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  postJson,
  useApi,
  type Component,
  type Forecast,
  type Game,
  type Generated,
  type StrategyKey,
  type Weights,
} from "@/lib/api";
import { formatDate, formatInt } from "@/lib/format";
import type { GameKey } from "@/lib/games";

import { blend, COMPONENT_LABELS, COMPONENTS, MAX_TEMPERATURE, MIN_TEMPERATURE, normalizeWeights, toPresence } from "@/lib/blend";
import { Heatmap, HeatmapTable } from "./heatmap";
import { PositionChart, PositionTable } from "./position-chart";

const LINE_COUNTS = [1, 3, 5];
const STRATEGY_ORDER: StrategyKey[] = ["balanced", "hot", "cold", "entropy"];
type Model = "blend" | "timesfm" | "hot" | "cold";
const MODEL_LABELS: Record<Model, string> = { blend: "Your blend", timesfm: "TimesFM", hot: "Hot", cold: "Overdue" };

function single<T extends string>(values: unknown[], fallback: T): T {
  return (values[0] as T | undefined) ?? fallback;
}

function WeightSlider({
  label,
  value,
  onChange,
  min = 0,
  max = 100,
  step = 5,
  display,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  display: string;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between text-sm">
        <span id={id}>{label}</span>
        <span className="text-muted-foreground tabular-nums">{display}</span>
      </div>
      <Slider
        aria-labelledby={id}
        value={[value]}
        min={min}
        max={max}
        step={step}
        onValueChange={(v) => onChange(Array.isArray(v) ? v[0] : v)}
      />
    </div>
  );
}

function Ticket({ index, line, game, result }: { index: number; line: Generated["lines"][number]; game: Game; result: Generated }) {
  const even = line.primary_numbers.length - line.odd;
  return (
    <li className="flex flex-col gap-2 rounded-xl bg-card p-3 ring-1 ring-foreground/10">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Line {index + 1}</span>
        <Tooltip>
          <TooltipTrigger className="cursor-help underline decoration-dotted underline-offset-2">
            {line.lift.toFixed(2)}× blend weight
          </TooltipTrigger>
          <TooltipContent>
            How strongly your blend favours these numbers compared with picking at random (1.00×). It is not a chance of winning:
            every line wins the jackpot 1 time in {formatInt(result.jackpot_odds)}.
          </TooltipContent>
        </Tooltip>
      </div>
      <BallRow numbers={line.primary_numbers} bonus={line.bonus_number} bonusName={game.bonus_name} size="lg" />
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>
          Sum {line.sum}
          {line.sum_in_forecast_band !== null && (line.sum_in_forecast_band ? " · inside TimesFM's 80% sum band" : " · outside TimesFM's 80% sum band")}
        </span>
        <span>
          {line.odd} odd / {even} even
        </span>
      </div>
    </li>
  );
}

export function ForecastView({ game: key }: { game: GameKey }) {
  const { data: game } = useApi<Game>(`/api/games/${key}`);
  const { data: forecast, error } = useApi<Forecast>(`/api/games/${key}/forecast`);

  const [count, setCount] = useState(3);
  const [strategy, setStrategy] = useState<StrategyKey | "custom">("balanced");
  const [weights, setWeights] = useState<Weights>({ timesfm: 100, hot: 0, cold: 0, uniform: 0 });
  const [temperature, setTemperature] = useState(1);
  const [model, setModel] = useState<Model>("blend");
  const [result, setResult] = useState<Generated | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Error | null>(null);

  const mainBlend = useMemo(
    () => (forecast ? toPresence(blend(forecast.main, weights, temperature), forecast.main.pick) : []),
    [forecast, weights, temperature],
  );
  const bonusBlend = useMemo(
    () => (forecast?.bonus ? toPresence(blend(forecast.bonus, weights, temperature), 1) : []),
    [forecast, weights, temperature],
  );
  const mainValues = !forecast || model === "blend" ? mainBlend : forecast.main.numbers.map((n) => n[model]);
  const bonusValues = !forecast?.bonus || model === "blend" ? bonusBlend : forecast.bonus.numbers.map((n) => n[model]);

  if (error && !forecast) return <ErrorNote error={error} />;
  if (!forecast || !game) return <LoadingBlock className="h-96" />;

  const choosePreset = (next: StrategyKey) => {
    const preset = forecast.strategies[next].weights;
    setStrategy(next);
    setWeights({
      timesfm: Math.round(preset.timesfm * 100),
      hot: Math.round(preset.hot * 100),
      cold: Math.round(preset.cold * 100),
      uniform: Math.round(preset.uniform * 100),
    });
  };
  const setWeight = (component: Component, value: number) => {
    setStrategy("custom");
    setWeights((w) => ({ ...w, [component]: value }));
  };
  const totalWeight = COMPONENTS.reduce((sum, c) => sum + weights[c], 0);
  const shares = totalWeight > 0 ? normalizeWeights(weights) : null;

  const generate = async () => {
    setBusy(true);
    setFailure(null);
    try {
      const body = strategy === "custom" ? { lines: count, weights, temperature } : { lines: count, strategy, temperature };
      setResult(await postJson<Generated>(`/api/games/${key}/forecast/generate`, body));
    } catch (e) {
      setFailure(e as Error);
    } finally {
      setBusy(false);
    }
  };

  const targetDate = formatDate(forecast.target_draw_at.slice(0, 10), false);
  const modelLabel = MODEL_LABELS[model];
  const sum = forecast.main.sum;

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <div className="flex flex-col gap-4">
        <Card>
          <CardHeader>
            <CardTitle>Generate forecasted sets</CardTitle>
            <CardDescription>
              Candidate lines for the {targetDate} draw, sampled from the blend below. Based on {formatInt(forecast.main.context_draws)}{" "}
              draws up to {formatDate(forecast.as_of.draw_date)}.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium">Strategy</span>
              <ToggleGroup
                variant="outline"
                spacing={0}
                className="w-full"
                value={strategy === "custom" ? [] : [strategy]}
                onValueChange={(v) => v.length > 0 && choosePreset(single<StrategyKey>(v, "balanced"))}
              >
                {STRATEGY_ORDER.map((s) => (
                  <ToggleGroupItem key={s} value={s} className="h-auto flex-1 px-1.5 py-1.5 text-xs whitespace-normal sm:text-sm">
                    {forecast.strategies[s].label}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
              <p className="text-xs text-muted-foreground">
                {strategy === "custom" ? "Custom blend: the sliders set how much each model contributes." : forecast.strategies[strategy].description}
              </p>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              {COMPONENTS.map((c) => (
                <WeightSlider
                  key={c}
                  label={COMPONENT_LABELS[c]}
                  value={weights[c]}
                  onChange={(v) => setWeight(c, v)}
                  display={shares ? `${Math.round(shares[c] * 100)}%` : "0%"}
                />
              ))}
              <div className="sm:col-span-2">
                <WeightSlider
                  label="Risk: focused ↔ spread out"
                  value={temperature}
                  min={MIN_TEMPERATURE}
                  max={MAX_TEMPERATURE}
                  step={0.1}
                  onChange={setTemperature}
                  display={temperature < 0.95 ? `${temperature.toFixed(1)} · sticks to the favourites` : temperature > 1.05 ? `${temperature.toFixed(1)} · closer to random` : "1.0 · as modelled"}
                />
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <ToggleGroup
                variant="outline"
                spacing={0}
                aria-label="Number of lines"
                value={[String(count)]}
                onValueChange={(v) => v.length > 0 && setCount(Number(v[0]))}
              >
                {LINE_COUNTS.map((n) => (
                  <ToggleGroupItem key={n} value={String(n)} className="px-3">
                    {n} {n === 1 ? "line" : "lines"}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
              <Button size="lg" className="flex-1" onClick={generate} disabled={busy || totalWeight === 0}>
                {busy ? <LoaderCircle className="animate-spin" /> : <Dices />}
                Generate forecasted sets
              </Button>
            </div>
            {totalWeight === 0 && <p className="text-xs text-destructive">Give at least one model some weight.</p>}
            {failure && <ErrorNote error={failure} />}
          </CardContent>
        </Card>

        {result && (
          <section aria-label="Generated lines" aria-live="polite" className="flex flex-col gap-2">
            <ul className="flex flex-col gap-2">
              {result.lines.map((line, i) => (
                <Ticket key={`${result.forecast_id}-${i}`} index={i} line={line} game={game} result={result} />
              ))}
            </ul>
            <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
              <Check className="mt-0.5 size-3.5 shrink-0" />
              {result.saved === false ? (
                <span>Sampled in your browser for the {formatDate(result.target_draw_at.slice(0, 10), false)} draw. This demo does not save lines.</span>
              ) : (
                <span>
                  Saved for the {formatDate(result.target_draw_at.slice(0, 10), false)} draw and scored against the result afterwards.
                  See <Link className="underline underline-offset-2" href={`/${key}/history`}>History</Link>. Seed {result.seed}.
                </span>
              )}
            </p>
          </section>
        )}
      </div>

      <div className="flex flex-col gap-4">
        <ChartCard
          title="Probability heatmap"
          description="Each number's chance of appearing in the next draw according to the selected model, colored by how far it sits from pure chance."
          table={
            <div className="flex flex-col gap-4">
              <HeatmapTable pool={forecast.main} values={mainValues} blendValues={mainBlend} modelLabel={modelLabel} />
              {forecast.bonus && (
                <HeatmapTable pool={forecast.bonus} values={bonusValues} blendValues={bonusBlend} modelLabel={modelLabel} />
              )}
            </div>
          }
          footer={
            forecast.backend.name === "timesfm"
              ? "TimesFM forecasts each number's rolling hit rate, recency gap and sorted position; Hot and Overdue are classical frequency and gap models. Draws are independent, so these differences are patterns in past data, not information about the next draw."
              : "TimesFM is not installed on the server: the “TimesFM” values here come from exponential smoothing instead."
          }
        >
          <ToggleGroup
            variant="outline"
            spacing={0}
            aria-label="Model shown"
            value={[model]}
            onValueChange={(v) => v.length > 0 && setModel(single<Model>(v, "blend"))}
          >
            {(Object.keys(MODEL_LABELS) as Model[]).map((m) => (
              <ToggleGroupItem key={m} value={m} className="px-3">
                {MODEL_LABELS[m]}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <Heatmap pool={forecast.main} values={mainValues} modelLabel={modelLabel} caption={`Main numbers · ${forecast.main.pick} of ${forecast.main.pool}`} />
          {forecast.bonus && (
            <Heatmap
              pool={forecast.bonus}
              values={bonusValues}
              modelLabel={modelLabel}
              caption={
                forecast.bonus.informative
                  ? `${game.bonus_name} · 1 of ${forecast.bonus.pool} · ${forecast.bonus.context_draws} draws under the current matrix`
                  : `${game.bonus_name} · too few draws under the current matrix to model, shown as pure chance`
              }
            />
          )}
        </ChartCard>

        {forecast.main.positions.length > 0 && (
          <ChartCard
            title="Positional forecast"
            description="Sorting each draw from lowest to highest gives one series per position. The band is where TimesFM puts each position of the next draw."
            legend={[
              { label: "TimesFM 80% band", color: "var(--series-1-wash)", mark: "rect" },
              { label: "TimesFM median", color: "var(--series-1)", mark: "dot" },
              { label: "Fair-draw average", color: "var(--context)", mark: "line" },
            ]}
            table={<PositionTable positions={forecast.main.positions} />}
            footer={
              sum && (
                <>
                  Line sum: TimesFM expects about {sum.mean.toFixed(0)} (80% band {sum.quantiles[0].toFixed(0)}–{sum.quantiles[8].toFixed(0)}). A
                  fair draw averages {sum.expected_mean.toFixed(0)} with a standard deviation of {sum.expected_sd.toFixed(0)}.
                </>
              )
            }
          >
            <PositionChart positions={forecast.main.positions} pool={forecast.main.pool} />
          </ChartCard>
        )}
      </div>
    </div>
  );
}
