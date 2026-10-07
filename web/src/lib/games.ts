/** Games in tab order. Rules and schedules come from the API; this is only what routing needs. */
export const GAMES = [
  { key: "powerball", name: "Powerball" },
  { key: "megamillions", name: "Mega Millions" },
  { key: "wa-hit5", name: "Hit 5" },
  { key: "wa-lotto", name: "Lotto" },
] as const;

export type GameKey = (typeof GAMES)[number]["key"];

export function isGameKey(value: string): value is GameKey {
  return GAMES.some((g) => g.key === value);
}

export function gameName(key: GameKey): string {
  return GAMES.find((g) => g.key === key)!.name;
}
