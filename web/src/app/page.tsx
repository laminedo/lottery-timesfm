import { redirect } from "next/navigation";

import { GAMES } from "@/lib/games";

export default function Home() {
  redirect(`/${GAMES[0].key}`);
}
