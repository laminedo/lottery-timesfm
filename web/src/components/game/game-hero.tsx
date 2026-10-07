"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { BallRow } from "@/components/ball";
import { ErrorNote } from "@/components/state";
import { Skeleton } from "@/components/ui/skeleton";
import { useApi, type Accuracy, type Game } from "@/lib/api";
import { IS_STATIC } from "@/lib/env";
import { countdownParts, formatDate, formatInt, formatJackpot, formatP } from "@/lib/format";
import type { GameKey } from "@/lib/games";

function Tile({ label, children, note }: { label: string; children: ReactNode; note?: ReactNode }) {
  return (
    <div className="flex flex-col gap-1 rounded-xl bg-card p-4 ring-1 ring-foreground/10">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="text-xl leading-tight font-semibold sm:text-2xl">{children}</div>
      {note && <div className="text-xs text-muted-foreground">{note}</div>}
    </div>
  );
}

/** Time left until the next drawing. Renders after mount, so server and browser clocks never disagree. */
function Countdown({ target }: { target: string }) {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  if (now === null) return <Skeleton className="h-8 w-32" />;
  const left = new Date(target).getTime() - now;
  if (left <= 0) return <span>Drawing now</span>;
  const { days, hours, minutes, seconds } = countdownParts(left);
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    <span className="tabular-nums" aria-live="off">
      {days > 0 && `${days}d `}
      {pad(hours)}:{pad(minutes)}:{pad(seconds)}
    </span>
  );
}

function drawTimeLabel(game: Game): string {
  const at = new Date(game.next_draw_at);
  const local = at.toLocaleString("en-US", { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  return `${local} your time`;
}

/** The historical accuracy tracker: how the model's picks have scored, next to what chance scores. */
function AccuracyTile({ game, accuracy }: { game: Game; accuracy: Accuracy | undefined }) {
  const chance = accuracy?.expected_matches ?? (game.pick * game.pick) / game.pool;
  const core = accuracy?.backtest?.strategies.find((s) => s.key === "balanced") ?? accuracy?.backtest?.strategies[0];
  if (accuracy?.backtest && core) {
    return (
      <Tile
        label="Accuracy tracker"
        note={
          <>
            matches per draw over the last {accuracy.backtest.draws} draws, vs {chance.toFixed(2)} by chance (p = {formatP(core.p_value)}
            ). <Link className="underline underline-offset-2" href={`/${game.key}/backtest`}>Details</Link>
          </>
        }
      >
        {core.mean_matches.toFixed(2)}
      </Tile>
    );
  }
  return (
    <Tile
      label="Accuracy tracker"
      note={
        <>
          No backtest yet. Chance scores {chance.toFixed(2)} matches per draw.{" "}
          <Link className="underline underline-offset-2" href={`/${game.key}/backtest`}>Run one</Link>
        </>
      }
    >
      <span className="text-muted-foreground">Not measured</span>
    </Tile>
  );
}

export function GameHero({ game: key }: { game: GameKey }) {
  const { data: game, error } = useApi<Game>(`/api/games/${key}`, { refreshInterval: 60_000 });
  const { data: accuracy } = useApi<Accuracy>(`/api/games/${key}/accuracy`);
  if (error && !game) return <ErrorNote error={error} />;
  if (!game) return <Skeleton className="h-44 w-full" />;
  const latest = game.latest_draw;
  const jackpot = game.next_jackpot;
  return (
    <section aria-label={`${game.name} summary`} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div>
          <h1 className="text-xl font-semibold">
            {game.name}
            {game.region !== "US" && <span className="ml-2 text-sm font-normal text-muted-foreground">Washington</span>}
          </h1>
          <p className="text-sm text-muted-foreground">
            {game.pick} numbers from 1–{game.pool}
            {game.bonus_pool ? `, plus the ${game.bonus_name} from 1–${game.bonus_pool}` : ""} · {formatInt(game.draw_count)} draws
            since {formatDate(game.main_since)}
          </p>
        </div>
        {latest && (
          <div className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Latest draw · {formatDate(latest.draw_date)}</span>
            <BallRow numbers={latest.primary_numbers} bonus={latest.bonus_number} bonusName={game.bonus_name} />
          </div>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Tile label="Next draw in" note={drawTimeLabel(game)}>
          <Countdown target={game.next_draw_at} />
        </Tile>
        <Tile
          label="Estimated jackpot"
          note={
            jackpot
              ? `${jackpot.cash_value_usd ? `Cash value ${formatJackpot(jackpot.cash_value_usd)} · ` : ""}${jackpot.source}`
              : IS_STATIC
                ? "The demo snapshot has no estimate for this draw."
                : "The lottery has not published an estimate we could read."
          }
        >
          {jackpot ? formatJackpot(jackpot.jackpot_usd) : <span className="text-muted-foreground">Not available</span>}
        </Tile>
        <AccuracyTile game={game} accuracy={accuracy} />
        <Tile label="Jackpot odds per line" note="The same for every line, whatever numbers it holds.">
          1 in {formatInt(game.jackpot_odds)}
        </Tile>
      </div>
    </section>
  );
}
