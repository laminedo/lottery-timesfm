import { cn } from "@/lib/utils";

type Kind = "main" | "powerball" | "megaball";

const SIZES = { sm: "size-7 text-xs", md: "size-9 text-sm", lg: "size-11 text-base" };
const KINDS: Record<Kind, string> = {
  main: "bg-[var(--ball)] text-foreground ring-1 ring-foreground/20",
  powerball: "bg-[var(--ball-powerball)] text-white",
  megaball: "bg-[var(--ball-megaball)] text-[#0b0b0b]",
};

export function bonusKind(bonusName: string | null | undefined): Kind {
  return bonusName === "Mega Ball" ? "megaball" : "powerball";
}

/** One lottery ball. `matched` rings it; `dim` fades a ball that did not match. */
export function Ball({
  n,
  kind = "main",
  size = "md",
  matched,
  dim,
  label,
}: {
  n: number;
  kind?: Kind;
  size?: keyof typeof SIZES;
  matched?: boolean;
  dim?: boolean;
  label?: string;
}) {
  return (
    <span
      role="img"
      aria-label={label ?? (kind === "main" ? `${n}` : `bonus ball ${n}`)}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full font-semibold tabular-nums",
        SIZES[size],
        KINDS[kind],
        matched && "outline-2 outline-offset-2 outline-[var(--status-good)]",
        dim && "opacity-60",
      )}
    >
      {n}
    </span>
  );
}

/** A full line: main numbers, then the bonus ball if the game has one. */
export function BallRow({
  numbers,
  bonus,
  bonusName,
  size = "md",
  matches,
  bonusMatched,
}: {
  numbers: number[];
  bonus?: number | null;
  bonusName?: string | null;
  size?: keyof typeof SIZES;
  /** Numbers to mark as matched; when given, the others are dimmed. */
  matches?: number[];
  bonusMatched?: boolean | null;
}) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {numbers.map((n) => (
        <Ball key={n} n={n} size={size} matched={matches?.includes(n)} dim={matches ? !matches.includes(n) : false} />
      ))}
      {bonus != null && (
        <Ball
          n={bonus}
          kind={bonusKind(bonusName)}
          size={size}
          label={`${bonusName ?? "bonus"} ${bonus}`}
          matched={bonusMatched === true}
          dim={bonusMatched === false}
        />
      )}
    </span>
  );
}
