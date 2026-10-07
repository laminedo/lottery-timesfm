"use client";

import { Activity, History, Sparkles, TrendingUp } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { GAMES, type GameKey } from "@/lib/games";
import { cn } from "@/lib/utils";

const SECTIONS = [
  { slug: "", label: "Forecast", icon: Sparkles },
  { slug: "backtest", label: "Backtest", icon: Activity },
  { slug: "trends", label: "Trends", icon: TrendingUp },
  { slug: "history", label: "History", icon: History },
] as const;

/** Game tabs. Switching game keeps you on the same section. */
export function GameTabs({ game }: { game: GameKey }) {
  const section = usePathname().split("/")[2] ?? "";
  return (
    <nav aria-label="Games" className="flex gap-1 overflow-x-auto rounded-xl bg-secondary p-1">
      {GAMES.map((g) => (
        <Link
          key={g.key}
          href={`/${g.key}${section ? `/${section}` : ""}`}
          aria-current={g.key === game ? "page" : undefined}
          className={cn(
            "flex-1 rounded-lg px-3 py-2 text-center text-sm font-medium whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground",
            g.key === game && "bg-card text-foreground shadow-sm ring-1 ring-foreground/10",
          )}
        >
          {g.name}
        </Link>
      ))}
    </nav>
  );
}

/** Section links within a game, drawn as an underlined tab row. */
export function SectionNav({ game }: { game: GameKey }) {
  const section = usePathname().split("/")[2] ?? "";
  return (
    <nav aria-label="Sections" className="flex gap-5 overflow-x-auto border-b">
      {SECTIONS.map(({ slug, label, icon: Icon }) => (
        <Link
          key={label}
          href={`/${game}${slug ? `/${slug}` : ""}`}
          aria-current={slug === section ? "page" : undefined}
          className={cn(
            "-mb-px flex items-center gap-1.5 border-b-2 border-transparent px-0.5 py-2.5 text-sm font-medium whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground",
            slug === section && "border-primary text-foreground",
          )}
        >
          <Icon className="size-4" />
          {label}
        </Link>
      ))}
    </nav>
  );
}
