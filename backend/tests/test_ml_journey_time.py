"""Random Forest journey time model and its validation (#103)."""

import csv
import random

import pytest

from app.ml import journey_time as jt
from benchmarks import rf_validation as rv

FAST = {"n_estimators": 10, "min_samples_leaf": 1, "random_state": 42, "n_jobs": 1}
CORRIDORS = {"A": "Road X", "B": "Road X", "C": "Road Y"}
BASE = {"A": 600, "B": 900, "C": 1500}


def write_trips(path, n=300, seed=1, corridors=CORRIDORS):
    rng = random.Random(seed)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pickup_zone", "route_corridor", "day_of_week", "hour_of_day",
                    "actual_duration_sec", "static_baseline_sec"])  # fmt: skip
        for _ in range(n):
            zone, weekday, hour = rng.choice("ABC"), rng.randrange(7), rng.randrange(24)
            w.writerow([zone, corridors[zone], jt.WEEKDAYS[weekday], hour,
                        BASE[zone] + 10 * hour + weekday, BASE[zone] + 115])  # fmt: skip
    return path


@pytest.fixture
def trips_csv(tmp_path):
    return write_trips(tmp_path / "trips.csv")


@pytest.fixture
def zones_csv(tmp_path):
    """Places for A, B and C, so training uses the app's own feature set."""
    path = tmp_path / "zones.csv"
    rows = [f"{z},{lat},{lon},{km}" for z, (lat, lon, km) in PLACES.items()]
    path.write_text("\n".join(["zone,lat,lon,straight_line_km", *rows]), encoding="utf-8")
    return path


def test_encoding_is_one_hot_zone_and_corridor_then_hour_and_weekday(trips_csv):
    encoding = jt.Encoding.from_trips(jt.load_trips(trips_csv))

    assert encoding.columns == [
        "zone=A", "zone=B", "zone=C", "corridor=Road X", "corridor=Road Y", "hour", "weekday",
    ]  # fmt: skip
    # Zone C on a Wednesday (2) at 07:00.
    assert encoding.encode([("C", 2, 7)]).tolist() == [[0, 0, 1, 0, 1, 7, 2]]


PLACES = {"A": (-1.30, 36.80, 15.0), "B": (-1.25, 36.85, 12.5), "C": (-1.35, 36.90, 6.0)}


def test_cyclic_features_replace_hour_and_weekday(trips_csv):
    encoding = jt.Encoding.from_trips(jt.load_trips(trips_csv), jt.Features(cyclic=True))

    assert encoding.columns[-4:] == ["hour_sin", "hour_cos", "weekday_sin", "weekday_cos"]
    assert "hour" not in encoding.columns
    # 06:00 is a quarter of the day round: sine 1, cosine 0. Monday is 0.
    row = encoding.encode([("C", 0, 6)])[0]
    assert row[-4:].tolist() == pytest.approx([1, 0, 0, 1], abs=1e-12)


def test_cyclic_features_put_midnight_next_to_23_00(trips_csv):
    encoding = jt.Encoding.from_trips(jt.load_trips(trips_csv), jt.Features(cyclic=True))
    late, midnight, noon = encoding.encode([("A", 0, 23), ("A", 0, 0), ("A", 0, 12)])

    assert sum((late - midnight) ** 2) < sum((noon - midnight) ** 2)


def test_spatial_features_are_the_zones_place(trips_csv):
    encoding = jt.Encoding.from_trips(jt.load_trips(trips_csv), jt.Features(spatial=True), PLACES)

    assert encoding.columns[-5:] == ["hour", "weekday", "lat", "lon", "km_to_jkia"]
    assert encoding.encode([("B", 3, 7)])[0][-5:].tolist() == [7, 3, -1.25, 36.85, 12.5]


def test_a_zone_without_a_place_is_refused(trips_csv):
    with pytest.raises(ValueError, match="no place in pickup_zones"):
        jt.Encoding.from_trips(
            jt.load_trips(trips_csv), jt.Features(spatial=True), {"A": PLACES["A"]}
        )


def test_the_real_zones_all_have_a_place():
    zones = {t.zone for t in jt.load_trips()}

    assert zones <= set(jt.load_places())


def test_the_cache_key_follows_the_feature_set(trips_csv, tmp_path):
    zones = tmp_path / "zones.csv"
    zones.write_text("zone,lat,lon,straight_line_km\nA,0,0,1\n", encoding="utf-8")
    plain = jt.cache_key(trips_csv, FAST, jt.PLAIN, zones)
    spatial = jt.cache_key(trips_csv, FAST, jt.Features(spatial=True), zones)

    assert len({plain, spatial, jt.cache_key(trips_csv, FAST, jt.Features(cyclic=True))}) == 3
    zones.write_text("zone,lat,lon,straight_line_km\nA,0,0,2\n", encoding="utf-8")
    # The zones file matters only when the model uses it.
    assert jt.cache_key(trips_csv, FAST, jt.PLAIN, zones) == plain
    assert jt.cache_key(trips_csv, FAST, jt.Features(spatial=True), zones) != spatial


def test_split_trips_is_seeded_and_disjoint(trips_csv):
    trips = jt.load_trips(trips_csv)
    training, test = jt.split_trips(trips, 0.2, seed=42)

    assert (len(training), len(test)) == (240, 60)
    assert sorted(map(id, training + test)) == sorted(map(id, trips))
    assert jt.split_trips(trips, 0.2, seed=42) == (training, test)


def test_load_trips_reads_monday_as_0(trips_csv):
    trips = jt.load_trips(trips_csv)
    with trips_csv.open(encoding="utf-8") as f:
        first = next(csv.DictReader(f))
    assert trips[0].weekday == jt.WEEKDAYS.index(first["day_of_week"])
    assert jt.WEEKDAYS[0] == "monday"


def test_a_zone_on_two_corridors_is_refused(tmp_path):
    trips = jt.load_trips(write_trips(tmp_path / "t.csv"))
    trips.append(jt.Trip("A", "Road Y", 0, 0, 600))
    with pytest.raises(ValueError, match="more than one route corridor"):
        jt.Encoding.from_trips(trips)


def test_training_is_deterministic(trips_csv, zones_csv):
    cells = [(z, d, h) for z in "ABC" for d in (0, 6) for h in (3, 18)]
    first = jt.train(trips_csv, FAST, zones_path=zones_csv).predict(cells)
    assert jt.train(trips_csv, FAST, zones_path=zones_csv).predict(cells) == first


def test_the_cache_key_follows_data_hyperparameters_and_version(trips_csv, tmp_path, monkeypatch):
    key = jt.cache_key(trips_csv, FAST)

    assert jt.cache_key(trips_csv, dict(FAST)) == key
    assert jt.cache_key(trips_csv, {**FAST, "n_estimators": 11}) != key
    assert jt.cache_key(write_trips(tmp_path / "other.csv", seed=2), FAST) != key
    monkeypatch.setattr(jt.sklearn, "__version__", "0.0")
    assert jt.cache_key(trips_csv, FAST) != key


def test_load_or_train_trains_only_when_the_key_changes(
    trips_csv, zones_csv, tmp_path, monkeypatch
):
    cache = tmp_path / "models" / "model.joblib"
    trained = []
    real_train = jt.train

    def spy(path, hyperparameters, *rest):
        trained.append(hyperparameters)
        return real_train(path, hyperparameters, *rest)

    monkeypatch.setattr(jt, "train", spy)

    first = jt.load_or_train(trips_csv, FAST, cache, zones_path=zones_csv)
    again = jt.load_or_train(trips_csv, FAST, cache, zones_path=zones_csv)
    assert len(trained) == 1 and cache.exists()
    assert again.key == first.key
    assert again.predict([("A", 0, 5)]) == first.predict([("A", 0, 5)])

    jt.load_or_train(trips_csv, {**FAST, "n_estimators": 12}, cache, zones_path=zones_csv)
    assert len(trained) == 2
    # Another feature set is another model, even with the same data.
    jt.load_or_train(trips_csv, {**FAST, "n_estimators": 12}, cache, features=jt.PLAIN)
    assert len(trained) == 3


def test_the_app_uses_the_feature_set_cross_validation_chose():
    assert jt.FEATURES == jt.FEATURE_SETS["cyclic_spatial"]  # docs/results/19-rf-features-cv


def test_predict_grid_covers_every_zone_weekday_and_hour(trips_csv, zones_csv):
    model = jt.train(trips_csv, FAST, zones_path=zones_csv)
    grid = jt.predict_grid(model)

    assert grid.zones == ["A", "B", "C"]
    # At a knot (h:30) the grid gives the model's own prediction for hour h.
    assert grid.seconds("B", 3, 17.5) == model.predict([("B", 3, 17)])[0]


# Predictions that make each knot easy to read: 100 x weekday + hour.
def grid_of_knots():
    return jt.HourlyGrid({("A", d, h): 100 * d + h for d in range(7) for h in range(24)})


def test_hourly_grid_puts_knots_at_half_past():
    grid = grid_of_knots()

    assert grid.seconds("A", 1, 7.5) == 107  # Tuesday hour 7, at 07:30
    assert grid.seconds("A", 1, 8.0) == pytest.approx(107.5)  # halfway to 08:30
    assert grid.seconds("A", 1, 7.75) == pytest.approx(107.25)


def test_hourly_grid_runs_round_the_week():
    grid = grid_of_knots()

    # Monday 23:45: a quarter of the way from Monday 23:30 (23) to Tuesday
    # 00:30 (100).
    assert grid.seconds("A", 0, 23.75) == pytest.approx(23 + 0.25 * 77)
    # Sunday 23:45 heads for Monday 00:30 (0), from Sunday 23:30 (623).
    assert grid.seconds("A", 6, 23.75) == pytest.approx(623 - 0.25 * 623)
    # Monday 00:10 comes from Sunday 23:30: 40 of the 60 minutes to 00:30.
    assert grid.seconds("A", 0, 10 / 60) == pytest.approx(623 - 40 / 60 * 623)


def test_the_real_model_stays_within_the_training_range():
    trips = jt.load_trips()
    model = jt.train()
    cells = [(z, d, h) for z in model.encoding.zones for d in range(7) for h in range(24)]
    predicted = model.predict(cells)

    assert len(model.encoding.zones) == 28 and len(model.encoding.corridors) == 6
    durations = [t.duration_sec for t in trips]
    assert min(durations) <= min(predicted) and max(predicted) <= max(durations)


# --- Validation (benchmarks/rf_validation.py) ---


@pytest.mark.parametrize(
    ("hour", "expected"),
    [(0, "night"), (4.99, "night"), (5, "morning"), (9.99, "morning"), (10, "midday"),
     (16, "evening"), (20.99, "evening"), (21, "night"), (23.5, "night")],
)  # fmt: skip
def test_hour_bands(hour, expected):
    assert rv.band(hour) == expected


def row(run, actual, rf, baseline=100.0, l2=100.0):
    return {"run_id": run, "actual_sec": actual, "rf": rf, "static_baseline": baseline,
            "l2_reference": l2, "band": "morning"}  # fmt: skip


def test_metrics_by_hand():
    # Errors -15%, +10%, -5%: MAPE 10, MAE 10 s, signed -3.33%, and one of the
    # three more than 10% too fast.
    rows = [row("r1", 100, 85), row("r1", 100, 110), row("r2", 100, 95)]
    m = rv.metrics(rows, "rf")

    assert m["mape"] == pytest.approx(10)
    assert m["mae_sec"] == pytest.approx(10)
    assert m["mpe"] == pytest.approx(-10 / 3)
    assert m["under_10_pct"] == pytest.approx(100 / 3)


def test_exactly_10_percent_too_fast_is_not_counted_as_under_predicted():
    assert rv.metrics([row("r", 100, 90)], "rf")["under_10_pct"] == 0


def test_too_slow_is_not_under_predicted():
    # 20% too slow: a van leaving early, not the risk this share measures.
    assert rv.metrics([row("r", 100, 120)], "rf")["under_10_pct"] == 0


def test_the_bootstrap_resamples_whole_runs():
    # Run a: 28 observations 10% off. Run b: one observation 50% off. Any
    # resample of runs has MAPE 10 (a, a), 50 (b, b) or (280 + 50) / 29 (a, b);
    # resampling single observations would give other values.
    rows = [row("a", 100, 110) for _ in range(28)] + [row("b", 100, 150)]
    low, high = rv.cluster_bootstrap(rows, rv.mape_of("rf"), resamples=200, seed=1)

    possible = {10.0, 50.0, round(330 / 29, 9)}
    assert round(low, 9) in possible and round(high, 9) in possible


def test_the_bootstrap_is_seeded():
    rows = [row(f"r{k}", 100, 100 + k) for k in range(40)]
    first = rv.cluster_bootstrap(rows, rv.mape_of("rf"), resamples=200, seed=1)

    assert rv.cluster_bootstrap(rows, rv.mape_of("rf"), resamples=200, seed=1) == first
    assert rv.cluster_bootstrap(rows, rv.mape_of("rf"), resamples=200, seed=2) != first


def test_rf_minus_baseline_is_below_0_when_the_rf_is_better():
    rows = [row("r", 100, 105, baseline=120)]
    assert rv.rf_minus_baseline(rows) == pytest.approx(5 - 20)


def test_relative_improvement_by_hand():
    # Baseline 20% off, RF 5% off: the RF removes three quarters of the error.
    assert rv.relative_improvement([row("r", 100, 105, baseline=120)]) == pytest.approx(75)


def test_rf_minus_l2_is_above_0_when_layer_2_is_better():
    assert rv.rf_minus_l2([row("r", 100, 110, l2=104)]) == pytest.approx(10 - 4)


@pytest.mark.parametrize(
    ("point", "low", "expected"),
    [(20, 15, "yes"), (20, 14.9, "point estimate only"), (15, 10, "point estimate only"),
     (14.9, 10, "no")],
)  # fmt: skip
def test_nfr3_is_met_only_if_the_whole_interval_clears_it(point, low, expected):
    assert rv.nfr3_verdict(point, low) == expected


def test_a_row_without_a_traffic_time_is_left_out_and_counted(tmp_path):
    path = tmp_path / "obs.csv"
    path.write_text(
        "logged_at_utc,logged_at_eat,day_of_week,hour_eat,minute_eat,zone,distance_m,"
        "duration_sec,duration_in_traffic_sec,run_id\n"
        '2026-10-31T15:07:01Z,2026-10-31T18:07:01,Saturday,18,7,"A",1,2744,,run1\n'
        '2026-10-31T15:07:01Z,2026-10-31T18:07:01,Saturday,18,7,"B",1,900,950,run1\n',
        encoding="utf-8",
    )

    assert [o.zone for o in rv.load_observations(path)] == ["B"]
    assert rv.count_without_traffic_time(path) == 1


def test_observations_use_the_weekday_and_the_minute(tmp_path):
    path = tmp_path / "obs.csv"
    path.write_text(
        "logged_at_utc,logged_at_eat,day_of_week,hour_eat,minute_eat,zone,distance_m,"
        "duration_sec,duration_in_traffic_sec,run_id\n"
        '2026-10-27T04:45:00Z,2026-10-27T07:45:00,Tuesday,7,45,"A",1,1,640,run1\n',
        encoding="utf-8",
    )
    [obs] = rv.load_observations(path)
    assert (obs.weekday, obs.hour, obs.actual_sec) == (1, 7.75, 640)

    [predicted] = rv.predict([obs], grid_of_knots(), {"A": 500.0, "B": 900.0}, _FlatL2())
    # Tuesday 07:45: a quarter of the way from 07:30 (107) to 08:30 (108).
    assert predicted["rf"] == pytest.approx(107.25, abs=0.05)
    assert predicted["static_baseline"] == 500
    assert predicted["band"] == "morning"


class _FlatL2:
    def seconds(self, zone, weekday, hour):
        return 600.0
