"""Source-granular, transactional normalization into SQLite."""
import csv
import hashlib
import io
import json
import re
import sqlite3
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from zipfile import BadZipFile

from .run import ingest as ingest_erp, load_manifest
from .readers import ambiguous_slash_date, decode_csv

from openpyxl import load_workbook
from pydantic import BaseModel, ValidationError, create_model

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "store" / "soony.db"
ERP = {
    "po": "purchase_orders", "receipt": "goods_receipts", "stock": "stock", "shipment": "open_shipments",
    "packout": "packout_log", "bom": "bom", "component": "components", "supplier": "suppliers",
    "supply": "supplier_components", "route": "routes", "product": "products",
    "launch_status": "launch_status", "bom_change": "bom_changes", "component_change": "component_changes",
    "supply_change": "supplier_component_changes", "news": "news_items",
}

# A required field is marked with *. Other fields preserve unknown values as null.
SCHEMAS = {
    "site": "site_id* name* operator type country city lat:f lon:f",
    "port": "locode* name* country lat:f lon:f mode",
    "carrier": "carrier_id* name* city country modes",
    "launch": "edition* product_id* day_one_demand:i* pre_orders:i packed:i still_to_pack:i rate_per_hour:i* hours_needed:f hours_available:f*",
    "plan_inbound": "supplier material_id* quantity:f* mode reference* etd:d eta:d status note",
    "plan_part": "material_id* description per_standard:f per_collectors:f needed:f erp_stock:f due_before_launch:f cover:f status",
    "shift": "day* shift* hours:f* lines",
}
CASTS = {"i": int, "f": float, "d": date, "x": list[str]}
MODELS = {}
for kind, spec in SCHEMAS.items():
    fields = {}
    for field in spec.split():
        required = field.endswith("*")
        name, _, type_name = field.rstrip("*").partition(":")
        value_type = CASTS.get(type_name, str)
        fields[name] = (value_type, ...) if required else (value_type | None, None)
    MODELS[kind] = create_model(kind.title().replace("_", "") + "Row", **fields)

ALIASES = {
    "material_id": "part material sku item_code component_id material_number",
    "product_id": "product finished_good sku",
    "reference": "container_awb container awb tracking_reference",
    "etd": "departure_date scheduled_departure",
    "eta": "arrival_date expected_arrival",
    "note": "comment comments remarks",
    "pre_orders": "of_which_pre_orders preorders",
    "per_collectors": "per_collector_s",
    "needed": "needed_for_the_remaining_pack_out",
    "quantity": "qty units amount",
    "day_one_demand": "launch_demand demand target",
    "rate_per_hour": "units_per_hour hourly_rate",
    "hours_available": "available_hours",
}
FILE_KINDS = {"ports": "port", "sites": "site", "logistics_providers": "carrier"}
SHEET_KINDS = {"editions": "launch", "inbound": "plan_inbound", "parts": "plan_part", "shifts": "shift"}
STATUS = {"gl": "delivered", "lo": "cancelled", "in_transit": "in_transit", "arrived_at_port": "arrived_port", "in_delivery": "in_delivery"}


def connect(path=DB):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    con.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS files (source TEXT PRIMARY KEY, sha TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS records (
            source TEXT REFERENCES files(source) ON DELETE CASCADE, sheet TEXT NOT NULL,
            row_no INTEGER NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
            PRIMARY KEY (source, sheet, row_no)
        );
        CREATE INDEX IF NOT EXISTS records_kind ON records(kind);
        CREATE TABLE IF NOT EXISTS changes (
            id INTEGER PRIMARY KEY, time TEXT, source TEXT, action TEXT, detail TEXT
        );
        CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)
    return con


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def key(value):
    return re.sub(r"[^a-z0-9]+", "_", unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().lower()).strip("_")


def day(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    value = str(value).strip()
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d", "%Y%m%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"Unrecognized date {value!r}")


def number(value):
    value = str(value).replace(" ", "").replace("\u00a0", "")
    if "," in value and "." in value:
        return float(value.replace(",", "") if value.rfind(".") > value.rfind(",") else value.replace(".", "").replace(",", "."))
    if "," in value and re.fullmatch(r"-?\d{1,3}(,\d{3})+", value):
        return float(value.replace(",", ""))
    return float(value.replace(",", "."))


def names(field):
    return [field, *ALIASES.get(field, "").split()]


def normalize(kind, raw, warnings=None):
    output = {}
    for name in MODELS[kind].model_fields:
        value = next((raw[k] for k in names(name) if k in raw and raw[k] is not None and str(raw[k]).strip()), None)
        if value is None or str(value).strip() in {"—", "-", "N/A"}:
            continue
        fmt = next(field.rstrip("*").partition(":")[2] for field in SCHEMAS[kind].split() if field.split(":")[0].rstrip("*") == name)
        if fmt == "d":
            original = value
            value = day(value)
            if warnings is not None and isinstance(original, str) and ambiguous_slash_date(original.strip()):
                warnings.append(f"{name}: ambiguous slash date {original}; interpreted as {value.isoformat()}")
        elif fmt in {"f", "i"}:
            value = number(value)
        elif fmt == "x":
            value = [item.strip() for item in re.split(r"[|,;\n]+", str(value)) if item.strip()]
        else:
            value = str(value).strip()
        if name == "status" and kind in {"po", "shipment", "plan_inbound"}:
            value = STATUS.get(key(value), key(value))
        output[name] = value
    return MODELS[kind].model_validate(output).model_dump(mode="json")


def csv_rows(body):
    decoded = decode_csv(body)
    lines = decoded.splitlines()
    if not lines:
        return
    delimiter = max((",", ";", "\t", "|"), key=lines[0].count)
    reader = csv.reader(io.StringIO(decoded), delimiter=delimiter)
    headers = next(reader, [])
    last = reader.line_num
    for row in reader:
        yield last + 1, dict(zip(map(key, headers), row))
        last = reader.line_num


def workbook_rows(body):
    with io.BytesIO(body) as stream:
        book = load_workbook(stream, read_only=True, data_only=True)
        try:
            for sheet in book:
                kind = SHEET_KINDS.get(key(sheet.title))
                if not kind:
                    continue
                mandatory = [name for name, field in MODELS[kind].model_fields.items() if field.is_required()]
                headers = None
                for num, row in enumerate(sheet.values, 1):
                    if not any(value is not None for value in row):
                        continue
                    if headers is None:
                        candidate = [key(cell) if cell is not None else "" for cell in row]
                        if all(set(names(name)).intersection(candidate) for name in mandatory):
                            headers = candidate
                        continue
                    raw = dict(zip(headers, row))
                    if kind == "shift" and not raw.get("day"):
                        continue
                    yield sheet.title, num, kind, raw
        finally:
            book.close()


def parse(source, body, warnings=None):
    path = Path(source)
    if path.suffix.lower() == ".xlsx":
        candidates = workbook_rows(body)
    elif path.suffix.lower() in {".csv", ".tsv", ".txt"}:
        kind = next((kind for prefix, kind in FILE_KINDS.items() if key(path.stem).startswith(prefix)), None)
        if not kind:
            return []
        candidates = (("", num, kind, raw) for num, raw in csv_rows(body))
    else:
        return []
    normalized = []
    for sheet, num, kind, raw in candidates:
        if not any(value is not None and str(value).strip() for value in raw.values()):
            continue
        try:
            row_warnings = []
            normalized.append((sheet, num, kind, normalize(kind, raw, row_warnings)))
            if warnings is not None:
                warnings.extend(f"{sheet or 'CSV'} row {num}, {warning}" for warning in row_warnings)
        except (ValidationError, ValueError) as exc:
            raise ValueError(f"{sheet or 'CSV'} row {num}: {exc}") from exc
    if path.suffix.lower() in {".csv", ".tsv", ".txt"} and not normalized:
        raise ValueError("CSV has no data rows")
    return normalized


def change(con, source, action, detail):
    event = {"time": now(), "source": source, "action": action, "detail": detail}
    con.execute("INSERT INTO changes(time,source,action,detail) VALUES(:time,:source,:action,:detail)",
                dict(event, detail=json.dumps(detail, ensure_ascii=False)))
    return event


def ingest(con, root, state=None):
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(root)
    database = Path(con.execute("PRAGMA database_list").fetchone()[2])
    state = state or (database.parent / ".absent-manifest")
    report = ingest_erp(root, state, database)
    erp_changes = {item["source"]: item for item in report["files"]}
    erp_sources = {row[0] for row in con.execute("SELECT source FROM ingest_files")}
    manifest = load_manifest(state)
    events = []
    rejections = []
    with con:
        con.execute("BEGIN IMMEDIATE")
        previous = dict(con.execute("SELECT source,sha FROM files"))
        supplemental_warnings = get_state(con, "sourceChecks", {}).get("supplementalWarnings", {})
        present = set()
        for path in sorted(root.rglob("*")):
            if not path.is_file() or any(part.startswith(".") for part in path.relative_to(root).parts):
                continue
            source = path.relative_to(root).as_posix()
            if manifest is not None and source not in manifest:
                continue
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError(f"{source}: path outside data directory")
            present.add(source)
            body = path.read_bytes()
            digest = hashlib.sha256(body).hexdigest()
            if manifest is not None and digest != manifest[source]:
                raise ValueError(f"{source}: local SHA-256 differs from bridge state")
            if previous.get(source) == digest:
                continue
            warnings = []
            try:
                rows = parse(source, body, warnings)
                if not rows and source not in erp_sources and con.execute(
                    "SELECT 1 FROM records WHERE source=? LIMIT 1", (source,)
                ).fetchone():
                    raise ValueError("No recognized rows after a schema change")
            except (ValueError, OSError, KeyError, BadZipFile) as exc:
                detail = {"error": str(exc)[:1200], "sha": digest}
                last = con.execute("SELECT action,detail FROM changes WHERE source=? ORDER BY id DESC LIMIT 1", (source,)).fetchone()
                if not last or last["action"] != "error" or json.loads(last["detail"]) != detail:
                    events.append(change(con, source, "error", detail))
                rejections.append({"source": source, "action": "error", "detail": detail})
                continue
            supplemental_warnings.pop(source, None)
            if warnings:
                supplemental_warnings[source] = warnings
            before = {(row["sheet"], row["row_no"]): json.loads(row["payload"]) for row in
                      con.execute("SELECT sheet,row_no,payload FROM records WHERE source=?", (source,))}
            after = {(sheet, num): data for sheet, num, _, data in rows}
            con.execute("INSERT INTO files VALUES(?,?) ON CONFLICT(source) DO UPDATE SET sha=excluded.sha", (source, digest))
            con.execute("DELETE FROM records WHERE source=?", (source,))
            con.executemany("INSERT INTO records VALUES(?,?,?,?,?)",
                            [(source, sheet, num, kind, json.dumps(data, ensure_ascii=False)) for sheet, num, kind, data in rows])
            revisions = [
                {"sheet": pos[0], "row": pos[1], "fields": {name: {"before": before[pos].get(name), "after": value}
                 for name, value in after[pos].items() if before[pos].get(name) != value}}
                for pos in sorted(before.keys() & after.keys()) if before[pos] != after[pos]
            ]
            events.append(change(con, source, "changed" if source in previous else "added", {
                "row_count": len(rows), "rows_added": len(after.keys() - before.keys()),
                "rows_removed": len(before.keys() - after.keys()), "rows_changed": len(revisions), "examples": revisions[:5],
                **({"typed_rows_before": erp_changes[source]["rows_before"], "typed_rows_after": erp_changes[source]["rows_after"]}
                   if source in erp_changes else {}),
            }))
        for source in sorted(previous.keys() - present):
            supplemental_warnings.pop(source, None)
            count = con.execute("SELECT COUNT(*) FROM records WHERE source=?", (source,)).fetchone()[0]
            con.execute("DELETE FROM files WHERE source=?", (source,))
            events.append(change(con, source, "removed", {"rows_removed": count}))
        save_state(con, "sourceChecks", {"filesSeen": len(present), "rejections": rejections,
                                         "supplementalWarnings": supplemental_warnings,
                                         "warnings": {**report["warnings"], **supplemental_warnings}})
    return events


def rows(con, kind):
    if kind in ERP:
        table = ERP[kind]
        for row in con.execute(f"SELECT * FROM {table} ORDER BY source,source_sheet,source_row"):
            item = dict(row)
            item["source"] = {"file": item.pop("source"), "sheet": item.pop("source_sheet"), "row": item.pop("source_row")}
            if kind == "shipment":
                item["supplier"] = item.get("supplier_name")
                for field in ("po_numbers", "material_ids"):
                    item[field] = item[field].split("|") if item[field] else None
            yield item
        return
    for row in con.execute("SELECT * FROM records WHERE kind=? ORDER BY source,sheet,row_no", (kind,)):
        item = json.loads(row["payload"])
        item["source"] = {"file": row["source"], "sheet": row["sheet"], "row": row["row_no"]}
        yield item


def save_state(con, key_name, value):
    con.execute("INSERT INTO state VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key_name, json.dumps(value, ensure_ascii=False)))


def get_state(con, key_name, default=None):
    row = con.execute("SELECT value FROM state WHERE key=?", (key_name,)).fetchone()
    return json.loads(row[0]) if row else default
