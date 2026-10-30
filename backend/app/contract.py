"""The backend's API contract, committed as docs/openapi.json (#122).

The Android client (#26) is written against this file. It is FastAPI's own
OpenAPI document for the app, written with stable output: sorted keys, fixed
indentation, a trailing newline, nothing taken from the environment. The
same code always gives the same bytes.

From backend/:
    python -m app.contract --write   regenerate docs/openapi.json
    python -m app.contract --check   exit 1 if it is stale

tests/test_contract.py fails when the committed file is stale, so CI's
pytest step catches a model changed without regenerating it.
"""

import argparse
import json
import sys
from pathlib import Path

from app.main import app

CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
REGENERATE = "cd backend && python -m app.contract --write, then commit docs/openapi.json"


def openapi_json() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def is_current() -> bool:
    # Text, not bytes: a Windows checkout may have CRLF line endings.
    return CONTRACT.exists() and CONTRACT.read_text(encoding="utf-8") == openapi_json()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate docs/openapi.json")
    mode.add_argument("--check", action="store_true", help="exit 1 if it is stale")
    args = parser.parse_args(argv)
    if args.write:
        CONTRACT.write_text(openapi_json(), encoding="utf-8", newline="\n")
        print(f"wrote {CONTRACT}")
        return 0
    if is_current():
        print(f"{CONTRACT} is current")
        return 0
    print(f"{CONTRACT} is stale: run {REGENERATE}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
