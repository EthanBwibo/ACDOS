"""Zone-to-zone travel times for pickup-to-pickup legs (#102, part of #23).

Google Distance Matrix gave every pair of the 28 pickup zones at two times on
one Monday-to-Thursday date, the query day Q (scripts/build_zone_matrix.py):
05:00, Layer 2's quietest weekday hour (off), and 18:00, its busiest (peak).
For any other weekday and hour, a leg is placed between the two by how
congested Layer 2 says its two zones are then:

    leg(o, d, wd, h) = off(o, d) + c * (peak(o, d) - off(o, d))
    c = (dL2_o + dL2_d) / (dpeak_o + dpeak_d)
    dL2_z   = L2(z, wd, h) - L2(z, Q, 05:00)
    dpeak_z = L2(z, Q, 18:00) - L2(z, Q, 05:00)

L2(z, wd, h) is Layer 2's zone-to-JKIA time (data/temporal_calibration.csv),
the only per-hour, per-day traffic data there is. c is 0 at Q 05:00 and 1 at
Q 18:00, so the two queried matrices come back exactly. It is pooled over the
two zones (a ratio of sums, not the mean of two ratios) because a zone whose
Layer 2 curve is nearly flat would make its own ratio unstable. Anchored on Q,
so a quieter day gets a lower c; above 1 (a morning peak heavier than the
evening one) it extrapolates.

Two places in the same zone are one point to the matrix (its diagonal is 0),
so their leg is the straight line at 30 km/h, the off-peak speed, slowed by
the zone's Layer 2 ratio to its own 05:00 value.

A third anchor (#106): the matrix queried at Q 07:30. Layer 2 measures zone to
JKIA, against Nairobi's inbound morning flow, so its morning rise is too mild
for cross-city legs: with only two anchors the model was 14% too fast at the
morning peak (#105). c still says how congested it is; the three matrices say
what that means for each pair. With c_m = c(o, d, Q, 07:30), where the morning
matrix sits for this pair, the leg runs through the three points:

    off + c / c_m * (morning - off)                       0 <= c <= c_m
    morning + (c - c_m) / (1 - c_m) * (peak - morning)    c_m < c <= 1
    off + c * (peak - off)                                c < 0 or c > 1

Each matrix comes back exactly at its query time, and the pieces meet at
c = 0, c_m and 1, so the leg is continuous in time. Outside [0, 1] it follows
the two-anchor line: the off-to-morning slope is steep where c_m is small and
would carry night hours (c below 0) far under the off-peak time. A pair whose
c_m is not strictly between 0 and 1 keeps the two-anchor line throughout.

Held-out queries (08:30, 12:30) are kept out of the model:
benchmarks/zone_matrix_check.py compares the model with them.
"""

import bisect
import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
ZONE_MATRIX_CSV = DATA_DIR / "zone_matrix.csv"
CALIBRATION_CSV = DATA_DIR / "temporal_calibration.csv"

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
HOURS_PER_WEEK = 7 * 24
OFF_PEAK, EVENING_PEAK, MORNING_PEAK = "off_peak", "evening_peak", "morning_peak"
# Straight-line speed within a zone at the off-peak hour: the haversine
# stand-in's 30 km/h (app/solver/instances.py).
SAME_ZONE_KMH = 30.0


class Calibration:
    """Layer 2: zone-to-JKIA seconds per zone, weekday and hour, linear between
    its sampled hours (0, 2, 5, ...). The interpolation runs round the week, so
    Monday 23:00 lies between Monday 22:00 and Tuesday 00:00, and Sunday wraps
    to Monday."""

    def __init__(self, samples: dict[str, list[tuple[float, float]]]):
        # zone -> sorted (hour of the week, seconds), padded with the last
        # sample a week earlier and the first a week later.
        self._knots: dict[str, tuple[list[float], list[float]]] = {}
        for zone, points in samples.items():
            points = sorted(points)
            padded = (
                [(points[-1][0] - HOURS_PER_WEEK, points[-1][1])]
                + points
                + [(points[0][0] + HOURS_PER_WEEK, points[0][1])]
            )
            self._knots[zone] = ([h for h, _ in padded], [s for _, s in padded])

    @property
    def zones(self) -> list[str]:
        return list(self._knots)

    def seconds(self, zone: str, weekday: int, hour: float) -> float:
        hours, values = self._knots[zone]
        t = (weekday * 24 + hour) % HOURS_PER_WEEK
        k = bisect.bisect_right(hours, t)  # hours[k - 1] <= t < hours[k]
        h0, h1 = hours[k - 1], hours[k]
        return values[k - 1] + (t - h0) / (h1 - h0) * (values[k] - values[k - 1])


def load_calibration(path: Path = CALIBRATION_CSV) -> Calibration:
    samples: dict[str, list[tuple[float, float]]] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            weekday = WEEKDAYS.index(row["weekday"])
            samples.setdefault(row["zone"], []).append(
                (weekday * 24 + int(row["hour"]), float(row["travel_sec"]))
            )
    return Calibration(samples)


@dataclass(frozen=True)
class Query:
    """One queried matrix: when it departed and every pair's seconds in traffic."""

    weekday: int
    hour: float
    seconds: dict[tuple[str, str], float]


def load_queries(path: Path = ZONE_MATRIX_CSV) -> dict[str, Query]:
    """Each period of zone_matrix.csv (off_peak, evening_peak, morning_peak)."""
    found: dict[str, Query] = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            depart = datetime.fromisoformat(row["departure_eat"])
            query = found.setdefault(
                row["period"], Query(depart.weekday(), depart.hour + depart.minute / 60, {})
            )
            query.seconds[(row["origin_zone"], row["dest_zone"])] = float(
                row["duration_in_traffic_sec"]
            )
    return found


class ZoneMatrix:
    def __init__(
        self, off: Query, peak: Query, calibration: Calibration, morning: Query | None = None
    ):
        """Without morning, the two-anchor model of #105."""
        if off.weekday != peak.weekday or (morning and morning.weekday != off.weekday):
            raise ValueError("the anchor matrices must be from the same day")
        missing = {z for pair in off.seconds for z in pair} - set(calibration.zones)
        if missing:
            raise ValueError(f"zones without Layer 2 calibration: {sorted(missing)}")
        self.zones = sorted({o for o, _ in off.seconds})
        self._off, self._peak, self._l2 = off.seconds, peak.seconds, calibration
        q = off.weekday
        # L2 at the off-peak query time, and its rise to the peak query time.
        self._l2_off = {z: calibration.seconds(z, q, off.hour) for z in self.zones}
        self._l2_rise = {
            z: calibration.seconds(z, q, peak.hour) - self._l2_off[z] for z in self.zones
        }
        flat = [z for z, rise in self._l2_rise.items() if rise <= 0]
        if flat:
            # c would divide by zero or turn upside down.
            raise ValueError(f"Layer 2 is not busier at the peak query for {flat}")
        # Each pair's morning matrix and its c_m, for pairs where c_m is
        # strictly between 0 and 1; the others keep the two-anchor line.
        self._morning: dict[tuple[str, str], tuple[float, float]] = {}
        self.fallback_pairs: list[tuple[str, str]] = []
        self.has_morning_anchor = morning is not None
        if morning is not None:
            for o, d in off.seconds:
                if o == d:
                    continue
                c_m = self.congestion(o, d, q, morning.hour)
                if 0 < c_m < 1:
                    self._morning[(o, d)] = (morning.seconds[(o, d)], c_m)
                else:
                    self.fallback_pairs.append((o, d))

    def congestion(self, origin: str, dest: str, weekday: int, hour: float) -> float:
        """c: 0 at the off-peak query, 1 at the peak query, pooled over both zones."""
        risen = sum(self._l2.seconds(z, weekday, hour) - self._l2_off[z] for z in (origin, dest))
        return risen / (self._l2_rise[origin] + self._l2_rise[dest])

    def leg(self, origin: str, dest: str, weekday: int, hour: float) -> float:
        """Seconds from zone origin to another zone dest, leaving on weekday
        (Monday 0) at hour (0 to 24, fractional)."""
        if origin == dest:
            raise ValueError("same zone: use same_zone() with the distance between the points")
        return self.leg_at(origin, dest, self.congestion(origin, dest, weekday, hour))

    def leg_at(self, origin: str, dest: str, c: float) -> float:
        """Seconds from zone origin to another zone dest at congestion c."""
        off, peak = self._off[(origin, dest)], self._peak[(origin, dest)]
        anchor = self._morning.get((origin, dest))
        if anchor is None or c < 0 or c > 1:
            return off + c * (peak - off)
        morning, c_m = anchor
        if c <= c_m:
            return off + c / c_m * (morning - off)
        return morning + (c - c_m) / (1 - c_m) * (peak - morning)

    def morning_congestion(self, origin: str, dest: str) -> float | None:
        """c_m for a pair, or None when it keeps the two-anchor line."""
        anchor = self._morning.get((origin, dest))
        return None if anchor is None else anchor[1]

    def same_zone(self, zone: str, km: float, weekday: int, hour: float) -> float:
        """Seconds between two points km apart in one zone: 30 km/h at the
        off-peak query, slowed by the zone's Layer 2 ratio to that time."""
        ratio = self._l2.seconds(zone, weekday, hour) / self._l2_off[zone]
        return km / SAME_ZONE_KMH * 3600 * ratio


def load(
    matrix_path: Path = ZONE_MATRIX_CSV,
    calibration_path: Path = CALIBRATION_CSV,
    morning_anchor: bool = True,
) -> ZoneMatrix:
    """The model from the data: with the 07:30 anchor (#106) when the file has
    it and morning_anchor is True, else the two-anchor model (#105)."""
    queries = load_queries(matrix_path)
    morning = queries.get(MORNING_PEAK) if morning_anchor else None
    return ZoneMatrix(
        queries[OFF_PEAK], queries[EVENING_PEAK], load_calibration(calibration_path), morning
    )
