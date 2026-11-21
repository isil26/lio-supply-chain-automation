"""Incremental extraction, reconciliation and atomic JSONL publication."""

import fcntl
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from collections import Counter
from contextlib import closing
from pathlib import Path
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from src.ingest.readers import SOURCES
from src.ingest.store import FILE_KINDS, SHEET_KINDS, key

from .extract import PROVIDER_ERRORS, bind_note_filename, extract_file
from .media import LocalOCR, provider_cache_key
from .parsers import classify
from .reconcile import ERP
from .schema import Facts

ROOT = Path(__file__).resolve().parents[2]
VERSION = 2
PARSER_REVISIONS = {"notice": 3, "price_list": 2, "receiving": 4, "context": 1}
EXTENSIONS = {".pdf", ".xlsx", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".eml", ".txt", ".md"}


def source_paths(data):
    paths = {path for path in data.rglob("*") if path.suffix.lower() == ".eml"}
    for supplier in (data / "suppliers").glob("SUP-*"):
        for bucket in ("order_confirmations", "contracts", "notices"):
            paths.update((supplier / bucket).rglob("*"))
    for subdir in ("soony/receiving/DC-HAM", "soony/context", "soony/logistics"):
        paths.update((data / subdir).rglob("*"))
    paths.discard(data / "soony/context/onboarding_notes.md")
    return sorted(path for path in paths if path.is_file()
                  and not any(part.startswith(("~$", ".")) for part in path.relative_to(data).parts)
                  and path.resolve().is_relative_to(data)
                  and not (path.suffix.lower() in {".csv", ".tsv", ".txt"}
                           and any(key(path.stem).startswith(prefix) for prefix in FILE_KINDS)))


def bind_source(value, source):
    """Remap evidence if two files with identical bytes are cached under different paths."""
    if isinstance(value, dict):
        return {key: source if key == "source_file" else bind_source(item, source) for key, item in value.items()}
    if isinstance(value, list):
        return [bind_source(item, source) for item in value]
    return value


def bind_activity(payload, source):
    for event in payload.get("activity", []):
        event["citation"]["file"] = source
        for key in ("input_ref", "output_ref"):
            if event[key]:
                event[key] = source + event[key][event[key].index("#page="):]


def serialize(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def extract_cached(path, source, manifest_hash, db, ocr, vision, translator):
    kind = classify(source)
    supplier = re.search(r"\bSUP-\d{4}(?=\b|_)", source)
    doc = {"source": source, "kind": kind, "supplier_id": supplier[0] if supplier else None,
           "sha": None, "fields": {}, "error": None, "pages": 0, "methods": [], "warnings": []}
    try:
        actual = digest(path)
        # The bridge manifest is a snapshot of the last sync. A local or in-flight
        # change must use its actual digest so it cannot poison the manifest's cache entry.
        sha = manifest_hash if actual == manifest_hash else actual
        doc["sha"] = sha
        if manifest_hash and manifest_hash != actual:
            doc["bridge_sha"] = manifest_hash
        options = [VERSION, kind, path.suffix.lower(), provider_cache_key(vision if kind == "receiving" else None),
                   provider_cache_key(translator if kind in {"notice", "contract", "price_list"} else None),
                   bool(ocr.tesseract), ocr.tessflags]
        if kind in PARSER_REVISIONS:
            options.append(PARSER_REVISIONS[kind])
        options = serialize(options)
        cached = db.execute("SELECT payload FROM extraction WHERE sha=? AND options=?", (sha, options)).fetchone()
        if cached:
            doc.update(bind_source(json.loads(cached[0]), source))
            bind_activity(doc, source)
            return doc, True

        activity = []
        supported = path.suffix.lower() in EXTENSIONS
        fields, pages, methods, warnings = (
            extract_file(path, source, kind, ocr, vision, translator, activity) if supported else ({}, 0, (), [])
        )
        if digest(path) != sha:
            doc["error"] = "File changed during extraction. Retry after bridge sync."
            return doc, False
        payload = {"fields": fields, "pages": pages, "methods": sorted(methods), "warnings": warnings,
                   "activity": activity}
        if supported and not methods:
            payload["error"] = "Document has no readable pages"
        if path.suffix.lower() == ".pdf" and kind == "confirmation" and re.match(r"OA\d{8}", path.stem, re.I) and not fields.get("items"):
            payload["error"] = "Order confirmation has no readable item rows"
        serialize(payload)
        doc.update(payload)
        if not doc["error"] and not warnings:
            db.execute("INSERT OR REPLACE INTO extraction VALUES (?, ?, ?)", (sha, options, serialize(payload)))
            db.commit()
    except (ImportError, LookupError, ParseError, BadZipFile, *PROVIDER_ERRORS) as exc:
        doc["error"] = f"Extraction failed ({type(exc).__name__})"
    return doc, False


def publish(rows, output):
    contents = "".join(f"{serialize(row)}\n" for row in rows).encode("utf-8")
    if output.exists() and output.read_bytes() == contents:
        return
    with tempfile.NamedTemporaryFile(mode="wb", dir=output.parent, prefix=".docs-", delete=False) as stream:
        pending = Path(stream.name)
        try:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            os.replace(pending, output)
        finally:
            pending.unlink(missing_ok=True)


def run_pipeline(data, state, output, *, vision=None, translator=None):
    data, state, output = Path(data).resolve(), Path(state), Path(output)
    if not data.is_dir():
        raise FileNotFoundError(f"Data directory is unavailable: {data}")
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = output.with_suffix(output.suffix + ".lock")
    with lock.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        manifest = json.loads(state.read_text(encoding="utf-8")) if state.is_file() else None
        if manifest is not None and (not isinstance(manifest, dict) or any(
            not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha) for sha in manifest.values()
        )):
            raise ValueError("Bridge state must contain a JSON object of path-to-sha256 entries")
        with closing(sqlite3.connect(output.parent / "docs_cache.sqlite3", timeout=30)) as db, tempfile.TemporaryDirectory(
            prefix="soony-ocr-"
        ) as folder:
            db.execute("CREATE TABLE IF NOT EXISTS extraction (sha TEXT, options TEXT, payload TEXT, PRIMARY KEY (sha, options))")
            repo = ROOT if data == ROOT / "data" else data.parent
            ocr = LocalOCR(repo, Path(folder))
            rows = []
            hits = 0
            for path in source_paths(data):
                source = path.relative_to(data).as_posix()
                if manifest is not None and source not in manifest:
                    continue
                manifest_hash = manifest[source].lower() if manifest is not None else None
                doc, cached = extract_cached(path, source, manifest_hash, db, ocr, vision, translator)
                if doc["kind"] == "receiving":
                    facts = Facts(source)
                    facts.update(doc["fields"])
                    bind_note_filename(facts, source)
                    doc["fields"] = facts
                rows.append(doc)
                hits += cached
            erp = ERP(data, rows, manifest)
            for row in rows:
                erp.apply_verified_crops(row)
                row["mismatches"] = erp.flags(row)
                row["review_reasons"] = []
                suffix = Path(row["source"]).suffix.lower()
                fields = row["fields"]
                if suffix not in EXTENSIONS:
                    row["review_reasons"].append("unsupported document format")
                elif suffix == ".eml":
                    row["review_reasons"].append("verify email and any attachments before using them")
                elif row["kind"] == "confirmation" and not ({"items", "shipped", "balance", "dock_hold"} & fields.keys()):
                    row["review_reasons"].append("unparsed confirmation")
                elif row["kind"] == "notice" and not (
                    {"downtime", "available_offer", "capacity", "effective_at", "rush_cutoff",
                     "road_hours", "maximum_quantity", "offer_valid_hours"} & fields.keys()
                ):
                    row["review_reasons"].append("notice has no verified operational fields")
                elif row["kind"] == "price_list" and not fields.get("price_items"):
                    row["review_reasons"].append("unparsed price list")
                elif row["kind"] == "workbook" and not (
                    any(dataset.matches(Path(row["source"])) for dataset in SOURCES)
                    or any(key(item.get("sheet", "")) in SHEET_KINDS for item in fields.get("rows", []))
                ):
                    row["review_reasons"].append("unrecognized workbook layout")
                elif row["kind"] == "context" and not ({"policy_clause", "org_role"} & fields.keys()):
                    row["review_reasons"].append("unrecognized document layout")
                elif row["kind"] in {"contract", "inspection", "workbook"} and not fields:
                    row["review_reasons"].append("unrecognized document layout")
                row["review_reasons"].extend(row["warnings"])
                if row["kind"] == "receiving":
                    if not row["fields"].get("items"):
                        row["review_reasons"].append("missing_item_quantities")
                    if row["fields"].get("handwriting_candidate") and not row["fields"].get("handwritten_correction"):
                        row["review_reasons"].append("unverified_handwriting")
            publish(rows, output)
    return {
        "documents": len(rows),
        "by_kind": dict(Counter(row["kind"] for row in rows)),
        "cache_hits": hits,
        "errors": sum(bool(row["error"]) for row in rows),
        "warnings": sum(bool(row["warnings"]) for row in rows),
        "needs_review": sum(bool(row["review_reasons"]) for row in rows),
        "mismatches": sum(len(row["mismatches"]) for row in rows),
    }
