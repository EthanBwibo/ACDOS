"""The RF fingerprint the image build prints (#148)."""

from dataclasses import dataclass

from app.ml.fingerprint import fingerprint


@dataclass
class Encoding:
    zones: list[str]


class Model:
    """Stands in for JourneyTimeModel: a fixed time per cell, plus a nudge."""

    def __init__(self, zones: list[str], nudge: float = 0.0, nudged_cell=None):
        self.encoding = Encoding(zones)
        self.nudge, self.nudged_cell = nudge, nudged_cell

    def predict(self, cells):
        return [
            1000.0 + 10 * w + h + (self.nudge if cell == self.nudged_cell else 0.0)
            for cell in cells
            for _, w, h in [cell]
        ]


def test_one_cell_per_zone_weekday_and_hour():
    cells, digest = fingerprint(Model(["Karen", "Westlands"]))
    assert cells == 2 * 7 * 24
    assert len(digest) == 64 and int(digest, 16) >= 0


def test_the_same_predictions_give_the_same_fingerprint_whatever_the_zone_order():
    assert fingerprint(Model(["Karen", "Westlands"])) == fingerprint(Model(["Westlands", "Karen"]))


def test_any_change_to_one_prediction_changes_it():
    base = fingerprint(Model(["Karen", "Westlands"]))[1]
    tiny = fingerprint(Model(["Karen", "Westlands"], 1e-9, ("Westlands", 6, 23)))[1]
    assert tiny != base
