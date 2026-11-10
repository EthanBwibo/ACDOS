"""Random Forest journey time model: pickup zone to JKIA (#103, part of #23).

Trained on data/trip_records.csv (Layer 3: synthetic trips built from Layer 1
and Layer 2, see scripts/build_trip_records.py) with the features Chapter 3
names: pickup zone, hour of day, day of week and route corridor. The target
is the trip's duration in seconds. Two optional additions (#18), chosen by
cross-validation on trip_records (#19, benchmarks/rf_features.py): hour and
weekday as cyclic features, and the zone's position.

Training is deterministic (a fixed random_state) and takes seconds, so the
model is not kept in git: load_or_train() caches it in backend/models/
(gitignored) and retrains whenever the data, the hyperparameters or the
scikit-learn version change.

The solver needs a time at any minute, not per hour: predict_grid() makes
every (zone, weekday, hour) prediction in one call, and HourlyGrid
interpolates between them (see HourlyGrid for why the knots sit at h:30).
"""

import bisect
import csv
import hashlib
import json
import math
import random
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import RandomForestRegressor

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
TRIP_RECORDS_CSV = DATA_DIR / "trip_records.csv"
PICKUP_ZONES_CSV = DATA_DIR / "pickup_zones.csv"
MODEL_CACHE = Path(__file__).resolve().parents[2] / "models" / "journey_time.joblib"

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
HOURS_PER_WEEK = 7 * 24

# A starting point, not tuned (#14 tunes the solver, not the model).
HYPERPARAMETERS = {"n_estimators": 200, "min_samples_leaf": 5, "random_state": 42, "n_jobs": 1}


@dataclass(frozen=True)
class Features:
    """What the model sees besides one-hot zone and corridor (#18).

    cyclic: hour and weekday as a sine and cosine each, instead of plain
    numbers, so 23:00 sits next to 00:00 and Sunday next to Monday.
    spatial: the zone's latitude, longitude and straight-line km to JKIA
    (data/pickup_zones.csv), so zones near each other can share splits.
    """

    cyclic: bool = False
    spatial: bool = False


PLAIN = Features()  # #103's model, the "before" of #18/#19
FEATURE_SETS = {
    "plain": PLAIN,
    "cyclic": Features(cyclic=True),
    "spatial": Features(spatial=True),
    "cyclic_spatial": Features(cyclic=True, spatial=True),
}
# The set the app uses, chosen by 5-fold cross-validation on trip_records
# (docs/results/19-rf-features-cv). Changing it changes the RF fingerprint.
FEATURES = FEATURE_SETS["cyclic_spatial"]

Place = tuple[float, float, float]  # lat, lon, straight-line km to JKIA


def load_places(path: Path = PICKUP_ZONES_CSV) -> dict[str, Place]:
    with path.open(newline="", encoding="utf-8") as f:
        return {
            row["zone"]: (float(row["lat"]), float(row["lon"]), float(row["straight_line_km"]))
            for row in csv.DictReader(f)
        }


def cyclic(value: float, period: float) -> tuple[float, float]:
    """value on a circle of the given period, as (sine, cosine)."""
    angle = 2 * math.pi * value / period
    return math.sin(angle), math.cos(angle)


@dataclass(frozen=True)
class Trip:
    zone: str
    corridor: str
    weekday: int  # Monday 0
    hour: int  # 0 to 23
    duration_sec: float


def load_trips(path: Path = TRIP_RECORDS_CSV) -> list[Trip]:
    with path.open(newline="", encoding="utf-8") as f:
        return [
            Trip(
                zone=row["pickup_zone"],
                corridor=row["route_corridor"],
                weekday=WEEKDAYS.index(row["day_of_week"].lower()),
                hour=int(row["hour_of_day"]),
                duration_sec=float(row["actual_duration_sec"]),
            )
            for row in csv.DictReader(f)
        ]


@dataclass(frozen=True)
class Encoding:
    """How a (zone, weekday, hour) becomes a feature row: one-hot zone, one-hot
    corridor, then the time (hour and weekday, plain or cyclic), then the
    zone's place if spatial. One place for it, so training and prediction
    cannot drift apart."""

    zones: tuple[str, ...]  # sorted
    corridors: tuple[str, ...]  # sorted
    corridor_of: dict[str, str]
    features: Features = PLAIN
    places: dict[str, Place] | None = None  # only for spatial

    @classmethod
    def from_trips(
        cls, trips: list[Trip], features: Features = PLAIN, places: dict | None = None
    ) -> "Encoding":
        corridor_of: dict[str, str] = {}
        for t in trips:
            if corridor_of.setdefault(t.zone, t.corridor) != t.corridor:
                raise ValueError(f"{t.zone} has more than one route corridor")
        if features.spatial:
            missing = sorted(set(corridor_of) - set(places or {}))
            if missing:
                raise ValueError(f"no place in pickup_zones for {missing}")
        return cls(
            tuple(sorted(corridor_of)),
            tuple(sorted(set(corridor_of.values()))),
            corridor_of,
            features,
            places if features.spatial else None,
        )

    @property
    def columns(self) -> list[str]:
        time = (
            ["hour_sin", "hour_cos", "weekday_sin", "weekday_cos"]
            if self.features.cyclic
            else ["hour", "weekday"]
        )
        place = ["lat", "lon", "km_to_jkia"] if self.features.spatial else []
        return (
            [f"zone={z}" for z in self.zones]
            + [f"corridor={c}" for c in self.corridors]
            + time
            + place
        )

    def encode(self, cells: list[tuple[str, int, int]]) -> np.ndarray:
        """Feature rows for (zone, weekday, hour) cells, in columns' order."""
        return np.array([self._row(*cell) for cell in cells], dtype=float).reshape(
            len(cells), len(self.columns)
        )

    def _row(self, zone: str, weekday: int, hour: int) -> list[float]:
        one_hot = [float(z == zone) for z in self.zones] + [
            float(c == self.corridor_of[zone]) for c in self.corridors
        ]
        if self.features.cyclic:
            time = [*cyclic(hour, 24), *cyclic(weekday, 7)]
        else:
            time = [hour, weekday]
        place = list(self.places[zone]) if self.features.spatial else []
        return one_hot + time + place


@dataclass(frozen=True)
class JourneyTimeModel:
    forest: RandomForestRegressor
    encoding: Encoding
    key: str  # what it was trained from (cache_key)

    def predict(self, cells: list[tuple[str, int, int]]) -> list[float]:
        """Seconds to JKIA for each (zone, weekday, hour) cell."""
        return [float(s) for s in self.forest.predict(self.encoding.encode(cells))]


def fit(
    trips: list[Trip],
    hyperparameters: dict,
    key: str = "",
    features: Features = PLAIN,
    places: dict[str, Place] | None = None,
) -> JourneyTimeModel:
    encoding = Encoding.from_trips(trips, features, places)
    forest = RandomForestRegressor(**hyperparameters)
    forest.fit(
        encoding.encode([(t.zone, t.weekday, t.hour) for t in trips]),
        [t.duration_sec for t in trips],
    )
    return JourneyTimeModel(forest, encoding, key)


def cache_key(
    path: Path,
    hyperparameters: dict,
    features: Features = FEATURES,
    zones_path: Path = PICKUP_ZONES_CSV,
) -> str:
    """Changes whenever the training data, the hyperparameters, the feature
    set (and with spatial features, the zones file) or the scikit-learn
    version do."""
    digest = hashlib.sha256(path.read_bytes())
    digest.update(json.dumps(hyperparameters, sort_keys=True).encode())
    digest.update(json.dumps(asdict(features), sort_keys=True).encode())
    if features.spatial:
        digest.update(zones_path.read_bytes())
    digest.update(sklearn.__version__.encode())
    return digest.hexdigest()


def train(
    path: Path = TRIP_RECORDS_CSV,
    hyperparameters: dict = HYPERPARAMETERS,
    features: Features = FEATURES,
    zones_path: Path = PICKUP_ZONES_CSV,
) -> JourneyTimeModel:
    places = load_places(zones_path) if features.spatial else None
    key = cache_key(path, hyperparameters, features, zones_path)
    return fit(load_trips(path), hyperparameters, key, features, places)


def load_or_train(
    path: Path = TRIP_RECORDS_CSV,
    hyperparameters: dict = HYPERPARAMETERS,
    cache: Path = MODEL_CACHE,
    features: Features = FEATURES,
    zones_path: Path = PICKUP_ZONES_CSV,
) -> JourneyTimeModel:
    """The cached model if it was trained from exactly this data, these
    hyperparameters, this feature set and this scikit-learn version;
    otherwise train and cache. The cache is only ever a file this function
    wrote."""
    key = cache_key(path, hyperparameters, features, zones_path)
    if cache.exists():
        cached = joblib.load(cache)
        if cached.key == key:
            return cached
    model = train(path, hyperparameters, features, zones_path)
    cache.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, cache)
    return model


def split_trips(
    trips: list[Trip], test_share: float = 0.2, seed: int = 42
) -> tuple[list[Trip], list[Trip]]:
    """(training, test): a seeded shuffle, the first test_share of it held
    back. The same split for every feature set, so they are compared on the
    same test trips (#19)."""
    shuffled = trips[:]
    random.Random(seed).shuffle(shuffled)
    n_test = round(len(trips) * test_share)
    return shuffled[n_test:], shuffled[:n_test]


def internal_check(
    path: Path = TRIP_RECORDS_CSV,
    hyperparameters: dict = HYPERPARAMETERS,
    test_share: float = 0.2,
    seed: int = 42,
    features: Features = FEATURES,
) -> dict[str, float]:
    """MAPE and MAE on a seeded share of trip_records held back from training.
    Synthetic against synthetic: a check that the model learned Layer 3, not a
    validation (that is benchmarks/rf_validation.py, on real observations)."""
    training, test = split_trips(load_trips(path), test_share, seed)
    places = load_places() if features.spatial else None
    model = fit(training, hyperparameters, features=features, places=places)
    predicted = model.predict([(t.zone, t.weekday, t.hour) for t in test])
    errors = [p - t.duration_sec for p, t in zip(predicted, test, strict=True)]
    return {
        "train_rows": len(training),
        "test_rows": len(test),
        "mape": statistics.mean(
            abs(e) / t.duration_sec * 100 for e, t in zip(errors, test, strict=True)
        ),
        "mae_sec": statistics.mean(abs(e) for e in errors),
    }


class HourlyGrid:
    """The model's prediction for every zone, weekday and hour, and a time at
    any minute by linear interpolation between them.

    Knots sit at h:30, not h:00. The model's hour feature h covers trips
    leaving from h:00 to h:59, so its prediction is that hour's average,
    best placed at the middle. Interpolating (rather than a step at each hour)
    keeps travel time continuous, so leaving later never arrives earlier
    unless the time falls faster than the clock, which the scheduling search
    relies on (#12). The interpolation runs round the week: Monday 23:45 lies
    between Monday 23:30 and Tuesday 00:30, and Sunday wraps to Monday.
    """

    def __init__(self, predictions: dict[tuple[str, int, int], float]):
        self._knots: dict[str, tuple[list[float], list[float]]] = {}
        for zone in {z for z, _, _ in predictions}:
            values = [predictions[(zone, k // 24, k % 24)] for k in range(HOURS_PER_WEEK)]
            # Knot k at hour k + 0.5 of the week, padded a week either side.
            hours = [k + 0.5 for k in range(-1, HOURS_PER_WEEK + 1)]
            self._knots[zone] = (hours, [values[-1]] + values + [values[0]])

    @property
    def zones(self) -> list[str]:
        return sorted(self._knots)

    def seconds(self, zone: str, weekday: int, hour: float) -> float:
        hours, values = self._knots[zone]
        t = (weekday * 24 + hour) % HOURS_PER_WEEK
        k = bisect.bisect_right(hours, t)  # hours[k - 1] <= t < hours[k]
        h0, h1 = hours[k - 1], hours[k]
        return values[k - 1] + (t - h0) / (h1 - h0) * (values[k] - values[k - 1])


def predict_grid(model: JourneyTimeModel) -> HourlyGrid:
    """Every zone x weekday x hour, in one predict() call."""
    cells = [
        (zone, weekday, hour)
        for zone in model.encoding.zones
        for weekday in range(7)
        for hour in range(24)
    ]
    return HourlyGrid(dict(zip(cells, model.predict(cells), strict=True)))
