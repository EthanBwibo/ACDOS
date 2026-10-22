"""The log-travel-times Edge Function carries the pickup zones as a constant
(zones.json), since it cannot read data/. This keeps the two from drifting."""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_edge_function_zones_match_pickup_zones_csv():
    with (ROOT / "data" / "pickup_zones.csv").open(newline="", encoding="utf-8") as f:
        expected = [
            {"zone": r["zone"].strip(), "lat": float(r["lat"]), "lon": float(r["lon"])}
            for r in csv.DictReader(f)
            if r["zone"].strip()
        ]
    zones_json = ROOT / "supabase" / "functions" / "log-travel-times" / "zones.json"

    assert json.loads(zones_json.read_text(encoding="utf-8")) == expected
