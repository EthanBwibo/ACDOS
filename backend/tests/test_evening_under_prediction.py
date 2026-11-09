"""The evening under-prediction analysis (#202), by hand."""

import math

import pytest

from benchmarks import evening_under_prediction as e


def row(actual, rf=1000.0, static=1000.0, l2=1000.0, zone="A", hour=18, date="2026-11-04"):
    return {
        "run_id": "r1", "zone": zone, "hour": hour, "date": date, "band": "evening",
        "logged_at_eat": f"{date}T{hour}:07:00", "actual_sec": actual, "rf": rf,
        "static_baseline": static, "l2_reference": l2,
    }  # fmt: skip


def test_observed_multiplier_is_the_time_over_the_zones_baseline():
    assert e.observed_multiplier(row(1300, static=1000)) == pytest.approx(1.3)


def test_layer3_expectation_is_layer2_times_the_noises_mean():
    expected = 1.2 * math.exp(0.005)
    assert e.layer3_expected_multiplier(row(0.1, l2=1200, static=1000)) == pytest.approx(expected)


def test_multiplier_gap_is_observed_against_the_layer3_expectation():
    r = row(1320 * math.exp(0.005), l2=1200, static=1000)
    assert e.multiplier_gap([r]) == pytest.approx(10)


def test_under_predicted_means_more_than_10_percent_too_fast():
    assert e.is_under_predicted(row(1000, rf=899))
    assert not e.is_under_predicted(row(1000, rf=900))  # exactly 10% is not more
    assert not e.is_under_predicted(row(1000, rf=1200))  # too slow


def test_a_shortfall_of_exactly_the_buffer_is_absorbed():
    assert not e.still_late(row(1900, rf=1000), buffer_sec=900)
    assert e.still_late(row(1901, rf=1000), buffer_sec=900)


def test_still_late_can_use_another_model():
    r = row(2000, rf=1950, static=1000)
    assert not e.still_late(r, 900)
    assert e.still_late(r, 900, "static_baseline")


def test_zone_hour_rows_compare_one_zone_and_hour():
    rows = [row(1400, rf=1200, zone="A", hour=18), row(1000, zone="B", hour=18)]
    layer3 = [e.Layer3Trip("A", 18, 1.1), e.Layer3Trip("A", 18, 1.3), e.Layer3Trip("B", 18, 1.0)]
    layer3 += [e.Layer3Trip(z, h, 1.0) for z in "AB" for h in e.EVENING_HOURS if h != 18]
    rows += [row(1000, zone=z, hour=h) for z in "AB" for h in e.EVENING_HOURS if h != 18]

    cell = next(c for c in e.zone_hour_rows(rows, layer3) if (c["zone"], c["hour"]) == ("A", 18))

    assert (cell["n_logged"], cell["n_layer3"]) == (1, 2)
    assert cell["observed"] == 1.4
    assert cell["layer3"] == 1.2
    assert cell["rf_under_10_pct"] == 100.0


def test_with_section_replaces_an_earlier_copy():
    once = e.with_section("# Summary\n", f"{e.SECTION}\n\nfirst")
    twice = e.with_section(once, f"{e.SECTION}\n\nsecond")

    assert twice == f"# Summary\n\n{e.SECTION}\n\nsecond\n"
