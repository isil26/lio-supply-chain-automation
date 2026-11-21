"""Build or refresh the Soony SQLite snapshot and emit its ingestion diff."""

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from types import UnionType
from typing import Annotated, Union, get_args, get_origin
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from .models import Supplier
from .readers import DATASETS, SOURCES, Dataset, read_records

ROOT = Path(__file__).resolve().parents[2]
PROVENANCE = ("source", "source_sheet", "source_row")
SQL_TYPES = {str: "TEXT", date: "TEXT", datetime: "TEXT", int: "INTEGER",
             bool: "INTEGER", Decimal: "REAL"}
JOIN_COLUMNS = {
    "purchase_orders": ("po_number", "po_line"),
    "goods_receipts": ("po_number", "po_line"),
    "stock": ("material_id", "site", "snapshot_date"),
    "open_shipments": ("shipment_id",),
    "bom": ("parent_id",),
    "components": ("component_id",),
    "products": ("product_id",),
    "suppliers": ("supplier_id",),
    "supplier_components": ("component_id", "supplier_id"),
    "routes": ("route_id",),
    "packout_log": ("product_id", "date"),
}


@dataclass(frozen=True)
class InputFile:
    dataset: Dataset
    sha256: str
    body: bytes


def load_manifest(path: Path) -> dict[str, str] | None:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(state, dict):
        raise ValueError(f"{path}: expected a mapping of paths to SHA-256 hashes")
    for source, digest in state.items():
        path_key = PurePosixPath(source)
        if (path_key.is_absolute() or ".." in path_key.parts or path_key.as_posix() != source
                or not isinstance(digest, str) or len(digest) != 64
                or any(c not in "0123456789abcdefABCDEF" for c in digest)):
            raise ValueError(f"{path}: invalid path or SHA-256 hash for {source!r}")
    return {source: digest.lower() for source, digest in state.items()}


def load_inputs(data: Path, manifest: dict[str, str] | None) -> dict[str, InputFile]:
    data = data.resolve(strict=True)
    if not data.is_dir():
        raise ValueError(f"{data} is not a data directory")
    inputs = {}
    for dataset in SOURCES:
        if manifest is None:
            sources = [file.relative_to(data).as_posix() for file in data.glob(dataset.pattern)
                       if file.is_file()]
        else:
            sources = [source for source in manifest if dataset.matches(PurePosixPath(source))]
        for source in sorted(sources):
            file = data / source
            if not file.resolve().is_relative_to(data):
                raise ValueError(f"{source}: source resolves outside the data directory")
            body = file.read_bytes()
            digest = hashlib.sha256(body).hexdigest()
            if manifest is not None and manifest[source] != digest:
                raise ValueError(f"{source}: local SHA-256 differs from bridge state")
            inputs[source] = InputFile(dataset, digest if manifest is None else manifest[source], body)
    return inputs


def quoted(names: tuple[str, ...]) -> str:
    return ", ".join(f'"{name}"' for name in names)


def create_schema(db: sqlite3.Connection) -> None:
    for dataset in DATASETS:
        table = dataset.table
        fields = []
        for name, field in dataset.model.model_fields.items():
            annotation = field.annotation
            while get_origin(annotation) in (Annotated, Union, UnionType):
                annotation = get_args(annotation)[0]
            column_type = SQL_TYPES[annotation]
            nullable = "" if not field.is_required() else " NOT NULL"
            fields.append(f'"{name}" {column_type}{nullable}')
        columns = ", ".join(fields)
        db.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                {columns},
                source TEXT NOT NULL,
                source_sheet TEXT NOT NULL,
                source_row INTEGER NOT NULL,
                PRIMARY KEY (source, source_sheet, source_row)
            ) STRICT
        """)
        if table == "open_shipments" and "quantity" not in {
            row[1] for row in db.execute("PRAGMA table_info(open_shipments)")
        }:
            db.execute("ALTER TABLE open_shipments ADD COLUMN quantity REAL")
        db.execute(f"CREATE INDEX IF NOT EXISTS {table}_lookup ON {table} "
                   f"({quoted(JOIN_COLUMNS[table])})")
    db.execute("""
        CREATE TABLE IF NOT EXISTS ingest_files (
            source TEXT PRIMARY KEY,
            table_name TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            row_count INTEGER NOT NULL
        ) STRICT
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS ingest_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            bridge_manifest TEXT,
            summary TEXT NOT NULL
        ) STRICT
    """)


def sqlite_value(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def build_rows(
    inputs: dict[str, InputFile],
) -> tuple[dict[str, list[tuple]], dict[str, int], dict[str, list[str]]]:
    rows = {dataset.table: [] for dataset in DATASETS}
    counts = {}
    warnings = defaultdict(list)
    supplier_names: dict[str, set[str]] = defaultdict(set)
    # The tracker supplies names in place of IDs. Load profiles first.
    sources = sorted(inputs, key=lambda source: (inputs[source].dataset.table != "suppliers", source))
    for source in sources:
        entry = inputs[source]
        resolved_names = {name: next(iter(ids)) for name, ids in supplier_names.items() if len(ids) == 1}
        table_rows = rows[entry.dataset.table]
        start = len(table_rows)
        try:
            for record in read_records(source, entry.body, entry.dataset, resolved_names):
                if record.warnings:
                    warnings[source].extend(record.warnings)
                if isinstance(record.value, Supplier):
                    for name in (record.value.name, record.value.legal_name):
                        if name:
                            supplier_names[" ".join(name.casefold().split())].add(record.value.supplier_id)
                values = tuple(sqlite_value(value) for value in record.value.model_dump().values())
                table_rows.append((*values, source, record.sheet, record.row))
        except (ValueError, ParseError, BadZipFile, KeyError, IndexError, StopIteration) as exc:
            raise ValueError(f"{source}: {exc}") from exc
        counts[source] = len(table_rows) - start
        if not counts[source] and Path(source).suffix == ".csv":
            raise ValueError(f"{source}: CSV has no data rows")
    return rows, counts, dict(warnings)


def hash_diff(before: dict[str, str], after: dict[str, str]) -> list[dict]:
    changes = []
    for source in sorted(before.keys() | after.keys()):
        old, new = before.get(source), after.get(source)
        if old == new:
            continue
        change = "added" if old is None else "removed" if new is None else "modified"
        changes.append({"source": source, "change": change,
                        "sha256_before": old, "sha256_after": new})
    return changes


def replace_rows(db: sqlite3.Connection, rows: dict[str, list[tuple]]) -> dict:
    summaries = {}
    for dataset in DATASETS:
        table = dataset.table
        columns = (*dataset.model.model_fields, *PROVENANCE)
        # Exclude the row position so an inserted line does not turn every later
        # record into a removal/addition in the summary.
        before = Counter(db.execute(f"SELECT {quoted(columns[:-1])} FROM {table}"))
        after = Counter(row[:-1] for row in rows[table])
        placeholders = ", ".join("?" for _ in columns)
        db.execute(f"DELETE FROM {table}")
        db.executemany(f"INSERT INTO {table} ({quoted(columns)}) VALUES ({placeholders})", rows[table])
        summaries[table] = {"rows": len(rows[table]), "added": sum((after - before).values()),
                            "removed": sum((before - after).values())}
    return summaries


def ingest(data: Path, state: Path, database: Path) -> dict:
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, timeout=30)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        manifest = load_manifest(state)
        inputs = load_inputs(data, manifest)
        create_schema(db)
        prior = db.execute("SELECT bridge_manifest, last_summary FROM ingest_state WHERE id = 1").fetchone()
        previous_manifest = json.loads(prior[0]) if prior and prior[0] is not None else None
        previous_files = {
            source: (table, digest, count) for source, table, digest, count
            in db.execute("SELECT source, table_name, sha256, row_count FROM ingest_files")
        }
        current_hashes = {source: entry.sha256 for source, entry in inputs.items()}
        changes = hash_diff({source: entry[1] for source, entry in previous_files.items()},
                            current_hashes)
        if changes or prior is None:
            rows, counts, warnings = build_rows(inputs)
            tables = replace_rows(db, rows)
            db.execute("DELETE FROM ingest_files")
            db.executemany("INSERT INTO ingest_files VALUES (?, ?, ?, ?)", (
                (source, entry.dataset.table, entry.sha256, counts[source])
                for source, entry in inputs.items()
            ))
        else:
            warnings = json.loads(prior[1]).get("warnings", {})
            counts = {source: entry[2] for source, entry in previous_files.items()}
            tables = {
                dataset.table: {"rows": db.execute(f"SELECT count(*) FROM {dataset.table}").fetchone()[0],
                                "added": 0, "removed": 0}
                for dataset in DATASETS
            }
        for file in changes:
            source = file["source"]
            previous = previous_files.get(source)
            file["table"] = inputs[source].dataset.table if source in inputs else previous[0]
            file["rows_before"] = previous[2] if previous else 0
            file["rows_after"] = counts.get(source, 0)
        summary = {
            "hash_source": "bridge/state.json" if manifest is not None else "local files",
            "files": changes,
            "tables": tables,
            "warnings": warnings,
            "bridge_files": hash_diff(previous_manifest or {}, manifest) if manifest is not None else None,
        }
        db.execute("INSERT OR REPLACE INTO ingest_state VALUES (1, ?, ?)", (
            json.dumps(manifest) if manifest is not None else None,
            json.dumps(summary),
        ))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--state", type=Path, default=ROOT / "bridge" / "state.json")
    parser.add_argument("--db", type=Path, default=ROOT / "store" / "soony.db")
    args = parser.parse_args()
    try:
        summary = ingest(args.data, args.state, args.db)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"ingest: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
