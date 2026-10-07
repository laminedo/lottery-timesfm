import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { HistoryView } from "@/components/history/history-view";
import { LoadingBlock } from "@/components/state";
import { GAMES, gameName, isGameKey } from "@/lib/games";

export function generateStaticParams() {
  return GAMES.map((g) => ({ game: g.key }));
}

export async function generateMetadata({ params }: PageProps<"/[game]/history">): Promise<Metadata> {
  const { game } = await params;
  return { title: isGameKey(game) ? `${gameName(game)} history` : "Not found" };
}

async function View({ params }: Pick<PageProps<"/[game]/history">, "params">) {
  const { game } = await params;
  if (!isGameKey(game)) notFound();
  return <HistoryView key={game} game={game} />;
}

// The game comes from the URL, so it is read inside Suspense: the shell renders at once.
export default function Page({ params }: PageProps<"/[game]/history">) {
  return (
    <Suspense fallback={<LoadingBlock className="h-96" />}>
      <View params={params} />
    </Suspense>
  );
}
