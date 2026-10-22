// log-travel-times (#81): the hourly travel time logger, moved from GitHub
// Actions (logger/log_travel_times.py), whose schedule dropped most runs.
//
// Queries the Google Distance Matrix API for every pickup zone to JKIA
// (departure_time=now, best_guess traffic model) and inserts one row per zone
// into travel_time_observations. Called hourly by pg_cron (migration 015).
//
// Secrets (Supabase Edge Function secrets, never in code):
//   GOOGLE_MAPS_API_KEY  the Distance Matrix key
//   LOGGER_SECRET        callers must send it in the x-logger-secret header;
//                        verify_jwt is off, because the anon key is public and
//                        anyone holding it could otherwise run up Maps charges.
// SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are provided by Supabase.

import { batches, buildRow, type Element, type Row, runTime, secretMatches, type Zone } from "./logic.ts";
import zonesJson from "./zones.json" with { type: "json" };

const ZONES: Zone[] = zonesJson;
const API_URL = "https://maps.googleapis.com/maps/api/distancematrix/json";
const JKIA = "-1.3192,36.9278";
const RETRYABLE_STATUSES = new Set(["OVER_QUERY_LIMIT", "UNKNOWN_ERROR"]);
const MAX_ATTEMPTS = 3;

// GET with retries on network errors and retryable API statuses. The URL
// carries the API key, so neither it nor a fetch error (whose message can
// include the URL) is ever logged or returned.
async function queryBatch(zones: Zone[], key: string): Promise<Element[]> {
  const params = new URLSearchParams({
    origins: zones.map((z) => `${z.lat},${z.lon}`).join("|"),
    destinations: JKIA,
    mode: "driving",
    departure_time: "now",
    traffic_model: "best_guess",
    units: "metric",
    key,
  });
  let lastError = "unknown";
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    let body: { status?: string; rows?: { elements: Element[] }[] } | null = null;
    try {
      const resp = await fetch(`${API_URL}?${params}`, { signal: AbortSignal.timeout(30_000) });
      body = await resp.json();
    } catch (err) {
      lastError = `network error (${err instanceof Error ? err.name : "unknown"})`;
    }
    if (body) {
      if (body.status === "OK") {
        const rows = body.rows ?? [];
        if (rows.length !== zones.length) {
          throw new Error(`expected ${zones.length} rows, got ${rows.length}`);
        }
        // One destination, so each row holds exactly one element.
        return rows.map((row) => row.elements[0]);
      }
      if (!RETRYABLE_STATUSES.has(body.status ?? "")) {
        // REQUEST_DENIED, INVALID_REQUEST etc. Retrying will not help.
        throw new Error(`Distance Matrix returned ${body.status}`);
      }
      lastError = body.status ?? "unknown";
    }
    if (attempt < MAX_ATTEMPTS) await new Promise((r) => setTimeout(r, 2 ** attempt * 1000));
  }
  throw new Error(`Distance Matrix failed after ${MAX_ATTEMPTS} attempts: ${lastError}`);
}

async function insertRows(rows: Row[]): Promise<void> {
  const url = `${Deno.env.get("SUPABASE_URL")}/rest/v1/travel_time_observations?on_conflict=run_id,zone`;
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
  const resp = await fetch(url, {
    method: "POST",
    headers: {
      apikey: serviceKey,
      Authorization: `Bearer ${serviceKey}`,
      "Content-Type": "application/json",
      Prefer: "resolution=ignore-duplicates,return=minimal",
    },
    body: JSON.stringify(rows),
  });
  if (!resp.ok) throw new Error(`insert failed: ${resp.status} ${await resp.text()}`);
}

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

Deno.serve(async (req) => {
  if (!secretMatches(req.headers.get("x-logger-secret"), Deno.env.get("LOGGER_SECRET") ?? "")) {
    return json({ error: "unauthorized" }, 401);
  }
  const key = Deno.env.get("GOOGLE_MAPS_API_KEY")?.trim();
  if (!key) return json({ error: "GOOGLE_MAPS_API_KEY is not set" }, 500);

  // One timestamp per run: every zone in this run shares the same departure time.
  const now = runTime(new Date());
  const runId = `edge-${now.toISOString().replace(".000Z", "Z")}`;
  try {
    const rows: Row[] = [];
    for (const batch of batches(ZONES)) {
      const elements = await queryBatch(batch, key);
      batch.forEach((zone, i) => rows.push(buildRow(zone, elements[i], now, runId)));
    }
    await insertRows(rows);
    const ok = rows.filter((r) => r.element_status === "OK").length;
    console.log(`${runId}: ${ok}/${rows.length} zones OK`);
    // Fail the call only if nothing usable came back, as the Python logger did.
    return json({ run_id: runId, ok, total: rows.length }, ok > 0 ? 200 : 500);
  } catch (err) {
    const message = err instanceof Error ? err.message : "unknown error";
    console.error(`${runId}: ${message}`);
    return json({ run_id: runId, error: message }, 500);
  }
});
