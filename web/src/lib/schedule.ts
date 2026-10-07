/** Draw schedules, worked out in the browser. The static demo has no server to ask. */

export interface Schedule {
  /** Draw days, Monday = 0. */
  draw_days: number[];
  /** "HH:MM" in the game's own time zone. */
  draw_time: string;
  timezone: string;
}

interface WallTime {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
}

/** The calendar date and clock time an instant has in a time zone. */
function wallTime(instant: Date, timeZone: string): WallTime {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "numeric",
    minute: "numeric",
  }).formatToParts(instant);
  const get = (type: string) => Number(parts.find((p) => p.type === type)!.value);
  return { year: get("year"), month: get("month"), day: get("day"), hour: get("hour"), minute: get("minute") };
}

/** The instant at which a time zone's clocks show the given date and time. */
function instantOf(wall: WallTime, timeZone: string): Date {
  const target = Date.UTC(wall.year, wall.month - 1, wall.day, wall.hour, wall.minute);
  let guess = target;
  // Two passes settle the offset even when the first guess lands on the other side of a clock change.
  for (let i = 0; i < 2; i++) {
    const seen = wallTime(new Date(guess), timeZone);
    guess += target - Date.UTC(seen.year, seen.month - 1, seen.day, seen.hour, seen.minute);
  }
  return new Date(guess);
}

/** The next scheduled drawing strictly after `now`. */
export function nextDrawAt(schedule: Schedule, now: Date = new Date()): Date {
  const [hour, minute] = schedule.draw_time.split(":").map(Number);
  const today = wallTime(now, schedule.timezone);
  for (let offset = 0; offset < 8; offset++) {
    // Date.UTC normalises day overflow, which gives calendar arithmetic free of time-zone effects.
    const day = new Date(Date.UTC(today.year, today.month - 1, today.day + offset));
    const weekday = (day.getUTCDay() + 6) % 7;
    if (!schedule.draw_days.includes(weekday)) continue;
    const at = instantOf(
      { year: day.getUTCFullYear(), month: day.getUTCMonth() + 1, day: day.getUTCDate(), hour, minute },
      schedule.timezone,
    );
    if (at.getTime() > now.getTime()) return at;
  }
  throw new Error("The game has no draw days");
}

/** "2026-10-07" for an instant, as dated in the given time zone. */
export function localDate(instant: Date, timeZone: string): string {
  const w = wallTime(instant, timeZone);
  return `${w.year}-${String(w.month).padStart(2, "0")}-${String(w.day).padStart(2, "0")}`;
}

/** ISO 8601 with the zone's own offset, e.g. "2026-10-07T22:59:00-04:00", as the API formats draw times. */
export function isoInZone(instant: Date, timeZone: string): string {
  const w = wallTime(instant, timeZone);
  const offsetMinutes = Math.round((Date.UTC(w.year, w.month - 1, w.day, w.hour, w.minute) - instant.getTime()) / 60000);
  const sign = offsetMinutes < 0 ? "-" : "+";
  const pad = (n: number) => String(Math.abs(n)).padStart(2, "0");
  const offset = `${sign}${pad(Math.trunc(offsetMinutes / 60))}:${pad(offsetMinutes % 60)}`;
  return `${localDate(instant, timeZone)}T${pad(w.hour)}:${pad(w.minute)}:00${offset}`;
}
