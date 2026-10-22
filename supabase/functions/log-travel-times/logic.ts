// Pure parts of the logger, kept apart from index.ts so `deno test` can check
// them without network access or secrets.

export const MAX_ORIGINS_PER_REQUEST = 25; // Distance Matrix limit

export type Zone = { zone: string; lat: number; lon: number };

// One Distance Matrix element (one origin to JKIA).
export type Element = {
  status?: string;
  distance?: { value: number };
  duration?: { value: number };
  duration_in_traffic?: { value: number };
};

// One travel_time_observations row (migration 014).
export type Row = {
  logged_at_utc: string;
  logged_at_eat: string;
  day_of_week: string;
  hour_eat: number;
  minute_eat: number;
  zone: string;
  origin_lat: number;
  origin_lon: number;
  element_status: string;
  distance_m: number | null;
  duration_sec: number | null;
  duration_in_traffic_sec: number | null;
  run_id: string;
};

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
// Kenya is UTC+3 all year (no daylight saving), so a fixed offset is exact.
const EAT_OFFSET_MS = 3 * 60 * 60 * 1000;

export function batches<T>(items: T[], size = MAX_ORIGINS_PER_REQUEST): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

// Whole seconds, as the Python logger used (microsecond=0).
export function runTime(now: Date): Date {
  return new Date(Math.floor(now.getTime() / 1000) * 1000);
}

export function buildRow(zone: Zone, el: Element, nowUtc: Date, runId: string): Row {
  const eat = new Date(nowUtc.getTime() + EAT_OFFSET_MS);
  const status = el.status ?? "MISSING";
  const ok = status === "OK";
  return {
    logged_at_utc: nowUtc.toISOString().replace(".000Z", "Z"),
    // getUTC* on the shifted date reads the Nairobi wall clock.
    logged_at_eat: eat.toISOString().slice(0, 19),
    day_of_week: DAYS[eat.getUTCDay()],
    hour_eat: eat.getUTCHours(),
    minute_eat: eat.getUTCMinutes(),
    zone: zone.zone,
    origin_lat: zone.lat,
    origin_lon: zone.lon,
    element_status: status,
    distance_m: ok ? el.distance?.value ?? null : null,
    duration_sec: ok ? el.duration?.value ?? null : null,
    duration_in_traffic_sec: ok ? el.duration_in_traffic?.value ?? null : null,
    run_id: runId,
  };
}

// Compares in time that does not depend on where the strings first differ,
// so the secret cannot be guessed one character at a time.
export function secretMatches(given: string | null, expected: string): boolean {
  if (given === null || expected.length === 0) return false;
  const a = new TextEncoder().encode(given);
  const b = new TextEncoder().encode(expected);
  let diff = a.length ^ b.length;
  for (let i = 0; i < b.length; i++) diff |= (a[i] ?? 0) ^ b[i];
  return diff === 0;
}
