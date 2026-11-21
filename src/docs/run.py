"""CLI for the T2 document extraction pipeline."""

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .pipeline import ROOT, run_pipeline
from .providers import configured_clients
from .store import DEFAULT_JSONL, load_table


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--state", type=Path, default=ROOT / "bridge" / "state.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_JSONL)
    parser.add_argument("--sqlite", type=Path, help="Also load the JSONL into this SQLite database")
    args = parser.parse_args()
    vision, translator = configured_clients()
    stats = run_pipeline(args.data, args.state, args.output, vision=vision, translator=translator)
    if args.sqlite:
        with closing(sqlite3.connect(args.sqlite, timeout=30)) as connection:
            stats["sqlite_documents"] = load_table(connection, args.output)
    print(json.dumps(stats, sort_keys=True))
    return int(stats["errors"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
