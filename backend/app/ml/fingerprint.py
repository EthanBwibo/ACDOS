"""A fingerprint of the trained Random Forest, to check that a build trained
the same model as a local run (#148).

    python -m app.ml.fingerprint

trains the model (or loads the cache) and prints the SHA-256 of its
prediction for every zone x weekday x hour (the cells predict_grid uses), as
exact float64 values in a fixed order. Two builds with the same fingerprint
predict the same journey times everywhere the solver asks.

The fingerprint is of the predictions, not of the cache key: the key hashes
the raw bytes of data/trip_records.csv, which a Windows checkout stores with
CRLF line endings and a Linux image with LF, so the key differs between them
even when the model is the same. The key is printed too, for information.
"""

import hashlib
import struct

from app.ml import journey_time


def fingerprint(model: journey_time.JourneyTimeModel) -> tuple[int, str]:
    """(number of cells, SHA-256 of their predictions)."""
    cells = [
        (zone, weekday, hour)
        for zone in sorted(model.encoding.zones)
        for weekday in range(7)
        for hour in range(24)
    ]
    digest = hashlib.sha256()
    for (zone, weekday, hour), seconds in zip(cells, model.predict(cells), strict=True):
        digest.update(f"{zone}|{weekday}|{hour}|".encode())
        digest.update(struct.pack(">d", float(seconds)))
    return len(cells), digest.hexdigest()


def main() -> None:
    model = journey_time.load_or_train()
    cells, digest = fingerprint(model)
    print(f"rf cells: {cells}")
    print(f"rf cache key: {model.key}")
    print(f"rf fingerprint: {digest}")


if __name__ == "__main__":
    main()
