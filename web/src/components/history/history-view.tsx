"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";

import { BallRow } from "@/components/ball";
import { ErrorNote, LoadingBlock } from "@/components/state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi, type Accuracy, type DrawPage, type Game, type StoredForecast } from "@/lib/api";
import { formatDate, formatInt, formatJackpot } from "@/lib/format";
import type { GameKey } from "@/lib/games";

const PAGE_SIZE = 25;
const STRATEGY_LABELS: Record<string, string> = {
  balanced: "Balanced",
  hot: "Hot numbers",
  cold: "Contrarian / cold",
  entropy: "High entropy",
  custom: "Custom blend",
};

function PastForecasts({ game }: { game: Game }) {
  const { data: forecasts } = useApi<StoredForecast[]>(`/api/games/${game.key}/forecasts?limit=10`);
  const { data: accuracy } = useApi<Accuracy>(`/api/games/${game.key}/accuracy`);
  if (!forecasts) return <LoadingBlock className="h-32" />;
  const live = accuracy?.live;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Your generated lines</CardTitle>
        <CardDescription>
          {forecasts.length === 0
            ? "Lines you generate on the Forecast tab are saved here and scored once their draw has happened."
            : live && live.scored_lines > 0
              ? `${live.scored_lines} scored ${live.scored_lines === 1 ? "line" : "lines"} so far averaged ${live.mean_matches?.toFixed(2)} matches; chance averages ${accuracy.expected_matches.toFixed(2)}. ${live.pending_lines} waiting for their draw.`
              : `${live?.pending_lines ?? 0} ${live?.pending_lines === 1 ? "line is" : "lines are"} waiting for the draw. Chance averages ${accuracy?.expected_matches.toFixed(2) ?? "…"} matches per line.`}
        </CardDescription>
      </CardHeader>
      {forecasts.length > 0 && (
        <CardContent className="flex flex-col gap-4">
          {forecasts.map((f) => (
            <div key={f.forecast_id} className="flex flex-col gap-2 border-t pt-3 first:border-t-0 first:pt-0">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span className="font-medium text-foreground">For the {formatDate(f.target_draw_date)} draw</span>
                <span>{STRATEGY_LABELS[f.strategy] ?? f.strategy}</span>
                <Badge variant={f.draw ? "secondary" : "outline"}>{f.draw ? "Scored" : "Waiting for the draw"}</Badge>
              </div>
              {f.draw && (
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span className="w-14">Drawn</span>
                  <BallRow numbers={f.draw.primary_numbers} bonus={f.draw.bonus_number} bonusName={game.bonus_name} size="sm" />
                </div>
              )}
              {f.lines.map((line, i) => (
                <div key={i} className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span className="w-14">Line {i + 1}</span>
                  <BallRow
                    numbers={line.primary_numbers}
                    bonus={line.bonus_number}
                    bonusName={game.bonus_name}
                    size="sm"
                    matches={f.draw ? f.draw.primary_numbers : undefined}
                    bonusMatched={f.draw && line.bonus_number != null ? line.bonus_match : null}
                  />
                  {line.scored && (
                    <span className="tabular-nums">
                      {line.main_matches} of {game.pick}
                      {line.bonus_match ? ` + ${game.bonus_name}` : ""}
                    </span>
                  )}
                </div>
              ))}
            </div>
          ))}
        </CardContent>
      )}
    </Card>
  );
}

export function HistoryView({ game: key }: { game: GameKey }) {
  const [page, setPage] = useState(0);
  const { data: game } = useApi<Game>(`/api/games/${key}`);
  const { data, error, isValidating } = useApi<DrawPage>(`/api/games/${key}/draws?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`);

  if (error && !data) return <ErrorNote error={error} />;
  if (!data || !game) return <LoadingBlock className="h-96" />;

  const pages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  const showMultiplier = data.draws.some((d) => d.multiplier !== null);
  const first = data.offset + 1;
  const last = data.offset + data.draws.length;

  return (
    <div className="flex flex-col gap-4">
      <PastForecasts game={game} />
      <Card>
        <CardHeader>
          <CardTitle>Draw history</CardTitle>
          <CardDescription>
            Official results under the current {game.pick}-of-{game.pool} format, newest first. Jackpot amounts are shown where the
            source publishes them.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className={`overflow-x-auto ${isValidating ? "opacity-60" : ""}`}>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Draw</TableHead>
                  <TableHead>Numbers</TableHead>
                  <TableHead className="text-right">Sum</TableHead>
                  {showMultiplier && <TableHead className="text-right">Multiplier</TableHead>}
                  <TableHead className="text-right">Jackpot</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.draws.map((d) => (
                  <TableRow key={d.draw_id}>
                    <TableCell className="whitespace-nowrap">{formatDate(d.draw_date)}</TableCell>
                    <TableCell>
                      <BallRow numbers={d.primary_numbers} bonus={d.bonus_number} bonusName={game.bonus_name} size="sm" />
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{d.primary_numbers.reduce((a, b) => a + b, 0)}</TableCell>
                    {showMultiplier && <TableCell className="text-right tabular-nums">{d.multiplier ? `${d.multiplier}×` : "–"}</TableCell>}
                    <TableCell className="text-right whitespace-nowrap tabular-nums">
                      {d.jackpot_usd ? formatJackpot(d.jackpot_usd) : <span className="text-muted-foreground">not published</span>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <div className="flex items-center justify-between gap-3 text-sm text-muted-foreground">
            <span className="tabular-nums">
              {formatInt(first)}–{formatInt(last)} of {formatInt(data.total)}
            </span>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0}>
                <ChevronLeft /> Newer
              </Button>
              <span className="tabular-nums">
                Page {page + 1} of {formatInt(pages)}
              </span>
              <Button variant="outline" size="sm" onClick={() => setPage((p) => Math.min(pages - 1, p + 1))} disabled={page >= pages - 1}>
                Older <ChevronRight />
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
