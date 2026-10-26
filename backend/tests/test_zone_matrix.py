"""Zone-to-zone travel times (#102, #106): the L2-blended matrix, its 07:30
anchor and the held-out check."""

import csv

import pytest

from app.ml import zone_matrix
from benchmarks.zone_matrix_check import check, errors

TUESDAY, SATURDAY, SUNDAY, MONDAY = 1, 5, 6, 0

# Layer 2 for three zones, sampled at 05:00 and 18:00 only, the same every day
# except Saturday. A rises 600 s from 05:00 to 18:00, B 200 s, C 100 s.
L2 = {
    "A": {5: 1000, 18: 1600},
    "B": {5: 500, 18: 700},
    "C": {5: 800, 18: 900},
}
# Saturday starts quieter (05:00 below Tuesday's) and peaks lower.
L2_SATURDAY = {"A": {5: 900, 18: 1300}, "B": {5: 450, 18: 650}, "C": {5: 750, 18: 850}}

# The query day is Tuesday 27 October 2026.
OFF = {("A", "B"): 600, ("B", "A"): 650, ("A", "C"): 900, ("C", "A"): 950, ("B", "C"): 400,
       ("C", "B"): 420}  # fmt: skip
PEAK = {("A", "B"): 1000, ("B", "A"): 1050, ("A", "C"): 1300, ("C", "A"): 1350,
        ("B", "C"): 600, ("C", "B"): 640}  # fmt: skip
MORNING = {("A", "B"): 720, ("B", "A"): 700, ("A", "C"): 1000, ("C", "A"): 1100,
           ("B", "C"): 500, ("C", "B"): 450}  # fmt: skip
# Held out at 08:30: 30 s slower than 07:30 everywhere.
HELD_0830 = {pair: sec + 30 for pair, sec in MORNING.items()}
# Every fixture L2 is linear from 05:00 to 18:00, so on Tuesday c = (h - 5) / 13
# for every pair, and c_m (07:30) = 2.5 / 13.
C_M = 2.5 / 13


def write_files(tmp_path, l2=L2, l2_saturday=L2_SATURDAY):
    calibration = tmp_path / "calibration.csv"
    with calibration.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["zone", "weekday", "hour", "travel_sec", "travel_min"])
        for day, name in enumerate(zone_matrix.WEEKDAYS):
            table = l2_saturday if day == SATURDAY else l2
            for zone, hours in table.items():
                for hour, sec in hours.items():
                    w.writerow([zone, name, hour, sec, round(sec / 60, 1)])
    matrix = tmp_path / "matrix.csv"
    with matrix.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["period", "departure_eat", "origin_zone", "dest_zone", "distance_m",
                    "duration_sec", "duration_in_traffic_sec", "queried_at_utc"])  # fmt: skip
        for period, when, table in [
            ("off_peak", "2026-10-27T05:00", OFF),
            ("evening_peak", "2026-10-27T18:00", PEAK),
            ("morning_peak", "2026-10-27T07:30", MORNING),
            ("held_out_0830", "2026-10-27T08:30", HELD_0830),
        ]:
            for zone in L2:
                w.writerow([period, when, zone, zone, 0, 0, 0, ""])
            for (o, d), sec in table.items():
                w.writerow([period, when, o, d, 1000, sec, sec, ""])
    return matrix, calibration


@pytest.fixture
def files(tmp_path):
    return write_files(tmp_path)


@pytest.fixture
def matrix(files):
    """#105's two-anchor model."""
    return zone_matrix.load(*files, morning_anchor=False)


@pytest.fixture
def anchored(files):
    """With the 07:30 anchor (#106)."""
    return zone_matrix.load(*files)


def test_the_queried_matrices_come_back_exactly(matrix):
    # c is 0 at the off-peak query (Tuesday 05:00) and 1 at the peak query
    # (Tuesday 18:00).
    assert matrix.congestion("A", "B", TUESDAY, 5) == 0
    assert matrix.congestion("A", "B", TUESDAY, 18) == 1
    assert matrix.leg("A", "B", TUESDAY, 5) == 600
    assert matrix.leg("A", "B", TUESDAY, 18) == 1000
    assert matrix.leg("B", "A", TUESDAY, 18) == 1050


def test_c_pools_the_two_zones(matrix):
    # Saturday 18:00: A has risen 1300 - 1000 = 300 s of its 600 s Tuesday
    # rise, B 650 - 500 = 150 s of its 200 s. Pooled: (300 + 150) / (600 + 200)
    # = 0.5625; the mean of the two ratios would be (0.5 + 0.75) / 2 = 0.625.
    # Measured from Tuesday 05:00, not Saturday's own quieter 05:00 (which
    # would give (400 + 200) / 800 = 0.75).
    # Leg 600 + 0.5625 * (1000 - 600) = 825.
    assert matrix.congestion("A", "B", SATURDAY, 18) == pytest.approx(0.5625)
    assert matrix.leg("A", "B", SATURDAY, 18) == pytest.approx(825)


def test_a_quieter_day_has_a_lower_c(matrix):
    # Anchored on the query day: Saturday's lighter evening gives c below 1.
    assert matrix.congestion("A", "B", SATURDAY, 18) < matrix.congestion("A", "B", TUESDAY, 18)


def test_calibration_interpolates_round_the_week(files):
    calibration = zone_matrix.load_calibration(files[1])

    # Tuesday 11:30, halfway from 05:00 (1000) to 18:00 (1600).
    assert calibration.seconds("A", TUESDAY, 11.5) == pytest.approx(1300)
    # Monday 23:00 lies between Monday 18:00 (1600) and Tuesday 05:00 (1000):
    # 5 of the 11 hours, so 1600 - 5/11 * 600.
    assert calibration.seconds("A", MONDAY, 23) == pytest.approx(1600 - 5 / 11 * 600)
    # Saturday 23:00 heads for Sunday 05:00, not Saturday's own: 1300 at 18:00,
    # 1000 next morning.
    assert calibration.seconds("A", SATURDAY, 23) == pytest.approx(1300 - 5 / 11 * 300)
    # Sunday 23:00 wraps to Monday 05:00.
    assert calibration.seconds("A", SUNDAY, 23) == pytest.approx(1600 - 5 / 11 * 600)
    # Monday 02:00 comes from Sunday 18:00.
    assert calibration.seconds("A", MONDAY, 2) == pytest.approx(1600 - 8 / 11 * 600)


def test_a_same_zone_leg_is_30_kmh_off_peak_slowed_by_layer_2(matrix):
    # 3 km at 30 km/h: 360 s at Tuesday 05:00. At 18:00 zone A's Layer 2 is
    # 1600 / 1000 of its 05:00 value: 576 s.
    assert matrix.same_zone("A", 3.0, TUESDAY, 5) == pytest.approx(360)
    assert matrix.same_zone("A", 3.0, TUESDAY, 18) == pytest.approx(576)
    with pytest.raises(ValueError):
        matrix.leg("A", "A", TUESDAY, 5)


def test_a_zone_not_busier_at_the_peak_is_refused(tmp_path):
    flat = dict(L2, C={5: 800, 18: 800})
    with pytest.raises(ValueError, match="not busier"):
        zone_matrix.load(*write_files(tmp_path, l2=flat))


def test_the_three_matrices_come_back_exactly_at_their_query_times(anchored):
    assert anchored.has_morning_anchor
    assert anchored.morning_congestion("A", "B") == pytest.approx(C_M)
    assert anchored.leg("A", "B", TUESDAY, 5) == 600
    assert anchored.leg("A", "B", TUESDAY, 7.5) == pytest.approx(720)
    assert anchored.leg("A", "B", TUESDAY, 18) == pytest.approx(1000)
    assert anchored.leg("C", "B", TUESDAY, 7.5) == pytest.approx(450)


def test_each_piece_by_hand(anchored):
    # Tuesday 06:15: c = 1.25 / 13, half of c_m: halfway from off (600) to
    # morning (720), 660.
    assert anchored.leg("A", "B", TUESDAY, 6.25) == pytest.approx(660)
    # Tuesday 12:45: c = 7.75 / 13, halfway from c_m to 1 ((7.75 - 2.5) /
    # (13 - 2.5)): halfway from morning (720) to peak (1000), 860.
    assert anchored.leg("A", "B", TUESDAY, 12.75) == pytest.approx(860)
    # Outside [0, 1], #105's line: Saturday 05:00, c = (-100 - 50) / 800 =
    # -0.1875, 600 - 0.1875 * 400 = 525 (the off-to-morning slope would give
    # 600 - 0.1875 / C_M * 120 = 483).
    assert anchored.leg("A", "B", SATURDAY, 5) == pytest.approx(525)
    assert anchored.leg_at("A", "B", 1.25) == pytest.approx(600 + 1.25 * 400)


def test_the_pieces_meet(anchored):
    for c in (0.0, C_M, 1.0):
        below, above = anchored.leg_at("A", "B", c - 1e-9), anchored.leg_at("A", "B", c + 1e-9)
        assert above == pytest.approx(below, abs=1e-5)


def test_a_pair_whose_c_m_is_not_inside_0_1_keeps_the_two_anchor_line(files, matrix):
    queries = zone_matrix.load_queries(files[0])
    # A "morning" matrix queried at 05:00 has c_m = 0 for every pair.
    at_off_peak = zone_matrix.Query(TUESDAY, 5.0, queries["morning_peak"].seconds)
    fallback = zone_matrix.ZoneMatrix(
        queries["off_peak"], queries["evening_peak"], zone_matrix.load_calibration(files[1]),
        at_off_peak,
    )  # fmt: skip

    assert len(fallback.fallback_pairs) == 6
    assert fallback.morning_congestion("A", "B") is None
    for hour in (6.25, 7.5, 12.75):
        assert fallback.leg("A", "B", TUESDAY, hour) == matrix.leg("A", "B", TUESDAY, hour)


def test_without_the_morning_anchor_it_is_the_two_anchor_model(matrix):
    for hour in (2, 6.25, 7.5, 12.75, 20):
        c = matrix.congestion("A", "B", TUESDAY, hour)
        assert matrix.leg("A", "B", TUESDAY, hour) == pytest.approx(600 + c * 400)
    assert matrix.fallback_pairs == []
    assert not matrix.has_morning_anchor


def test_the_held_out_check_skips_the_diagonal_and_scores_each_model(files, matrix, anchored):
    models = {"three_anchor": anchored, "two_anchor": matrix}
    rows = check(models, zone_matrix.load_queries(files[0]), "held_out_0830")

    assert len(rows) == 6
    a_to_b = next(r for r in rows if (r["origin_zone"], r["dest_zone"]) == ("A", "B"))
    # Tuesday 08:30: c = 3.5 / 13. Two anchors: 600 + 3.5/13 * 400 = 707.7.
    # Three: 720 + (3.5/13 - 2.5/13) / (1 - 2.5/13) * 280 = 720 + 280 / 10.5
    # = 746.7. The single matrices are copied as they are.
    assert a_to_b["c"] == pytest.approx(3.5 / 13, abs=1e-4)
    assert a_to_b["two_anchor"] == pytest.approx(600 + 3.5 / 13 * 400, abs=0.05)
    assert a_to_b["three_anchor"] == pytest.approx(720 + 280 / 10.5, abs=0.05)
    assert (a_to_b["off_peak_only"], a_to_b["morning_peak_only"]) == (600, 720)
    assert a_to_b["actual_sec"] == 750

    off = errors(rows, "off_peak_only")
    # Off-peak against the 08:30 matrix: A-B -150/750, B-A -80/730, A-C
    # -130/1030, C-A -180/1130, B-C -130/530, C-B -60/480.
    pe = [-150 / 750, -80 / 730, -130 / 1030, -180 / 1130, -130 / 530, -60 / 480]
    assert off["mpe"] == pytest.approx(100 * sum(pe) / 6)
    assert off["mape"] == pytest.approx(-off["mpe"])
    assert off["mae_sec"] == pytest.approx((150 + 80 + 130 + 180 + 130 + 60) / 6)


def test_rechecking_105_never_scores_the_held_out_matrix_against_itself(files, matrix):
    # #105's check: 07:30 held out from the two-anchor model, so there is no
    # morning_peak_only column (it would be the answer itself).
    rows = check({"two_anchor": matrix}, zone_matrix.load_queries(files[0]), "morning_peak")

    assert "morning_peak_only" not in rows[0]
    assert {"off_peak_only", "evening_peak_only"} <= set(rows[0])


def test_the_real_matrix_covers_the_28_zones_and_stays_positive():
    matrix = zone_matrix.load()

    with zone_matrix.DATA_DIR.joinpath("pickup_zones.csv").open(encoding="utf-8") as f:
        assert matrix.zones == sorted(row["zone"] for row in csv.DictReader(f))
    legs = [
        matrix.leg(o, d, day, hour)
        for o in matrix.zones
        for d in matrix.zones
        if o != d
        for day in range(7)
        for hour in range(24)
    ]
    assert len(legs) == 28 * 27 * 7 * 24
    assert min(legs) > 0
