import { notFound } from "next/navigation";
import { Suspense } from "react";

import { GameHero } from "@/components/game/game-hero";
import { GameTabs, SectionNav } from "@/components/game/game-nav";
import { LoadingBlock } from "@/components/state";
import { GAMES, isGameKey } from "@/lib/games";

export function generateStaticParams() {
  return GAMES.map((g) => ({ game: g.key }));
}

async function GameChrome({ params }: Pick<LayoutProps<"/[game]">, "params">) {
  const { game } = await params;
  if (!isGameKey(game)) notFound();
  return (
    <>
      <GameTabs game={game} />
      <GameHero game={game} />
      <SectionNav game={game} />
    </>
  );
}

export default function GameLayout({ children, params }: LayoutProps<"/[game]">) {
  return (
    <>
      <Suspense fallback={<LoadingBlock className="h-72" />}>
        <GameChrome params={params} />
      </Suspense>
      {children}
    </>
  );
}
