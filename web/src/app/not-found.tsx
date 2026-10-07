import Link from "next/link";

import { GAMES } from "@/lib/games";

export default function NotFound() {
  return (
    <div className="flex flex-col items-start gap-3 py-12">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <p className="text-muted-foreground">That game or page does not exist. Pick a game:</p>
      <ul className="flex flex-wrap gap-3">
        {GAMES.map((g) => (
          <li key={g.key}>
            <Link className="text-primary underline-offset-4 hover:underline" href={`/${g.key}`}>
              {g.name}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
