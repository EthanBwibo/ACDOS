import assert from "node:assert/strict";

import { batches, buildRow, runTime, secretMatches } from "./logic.ts";
import zones from "./zones.json" with { type: "json" };

const ZONE = { zone: "South B, Nairobi", lat: -1.310341, lon: 36.833737 };
// 03:42:29 UTC on Tuesday 20 October 2026 is 06:42:29 in Nairobi.
const NOW = new Date("2026-10-20T03:42:29Z");

Deno.test("28 zones go out in a batch of 25 and a batch of 3", () => {
  assert.equal(zones.length, 28);
  assert.deepEqual(batches(zones).map((b) => b.length), [25, 3]);
});

Deno.test("an OK element becomes a row like the Python logger's", () => {
  const el = {
    status: "OK",
    distance: { value: 13268 },
    duration: { value: 1001 },
    duration_in_traffic: { value: 849 },
  };

  assert.deepEqual(buildRow(ZONE, el, NOW, "edge-x"), {
    logged_at_utc: "2026-10-20T03:42:29Z",
    logged_at_eat: "2026-10-20T06:42:29",
    day_of_week: "Tuesday",
    hour_eat: 6,
    minute_eat: 42,
    zone: "South B, Nairobi",
    origin_lat: -1.310341,
    origin_lon: 36.833737,
    element_status: "OK",
    distance_m: 13268,
    duration_sec: 1001,
    duration_in_traffic_sec: 849,
    run_id: "edge-x",
  });
});

Deno.test("a failed element keeps its status and leaves the numbers empty", () => {
  const row = buildRow(ZONE, { status: "ZERO_RESULTS" }, NOW, "edge-x");

  assert.equal(row.element_status, "ZERO_RESULTS");
  assert.equal(row.distance_m, null);
  assert.equal(row.duration_sec, null);
  assert.equal(row.duration_in_traffic_sec, null);
});

Deno.test("EAT crosses midnight into the next day", () => {
  // 22:30 UTC Sunday is 01:30 Monday in Nairobi.
  const row = buildRow(ZONE, { status: "OK" }, new Date("2026-10-25T22:30:00Z"), "edge-x");

  assert.equal(row.logged_at_eat, "2026-10-26T01:30:00");
  assert.equal(row.day_of_week, "Monday");
  assert.equal(row.hour_eat, 1);
});

Deno.test("run time drops the milliseconds", () => {
  assert.equal(runTime(new Date("2026-10-20T03:42:29.987Z")).toISOString(), "2026-10-20T03:42:29.000Z");
});

Deno.test("the secret must match exactly", () => {
  assert.equal(secretMatches("s3cret", "s3cret"), true);
  assert.equal(secretMatches("s3creT", "s3cret"), false);
  assert.equal(secretMatches("s3cret-and-more", "s3cret"), false);
  assert.equal(secretMatches("s3c", "s3cret"), false);
  assert.equal(secretMatches(null, "s3cret"), false);
  // An unset LOGGER_SECRET must not let an empty header through.
  assert.equal(secretMatches("", ""), false);
});
