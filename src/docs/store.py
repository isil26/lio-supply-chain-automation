"""Load document JSONL into SQLite and adapt the existing document reader."""

import json
from pathlib import Path

from .pipeline import ROOT, run_pipeline, serialize
from .providers import configured_clients

DEFAULT_JSONL = ROOT / "store" / "docs.jsonl"


def read_jsonl(path=DEFAULT_JSONL):
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def load_table(connection, path=DEFAULT_JSONL):
    """Replace the T2 table atomically, leaving the caller's transaction intact."""
    connection.execute("SAVEPOINT load_doc_extractions")
    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS doc_extractions (
                source TEXT PRIMARY KEY, sha TEXT, kind TEXT NOT NULL,
                supplier_id TEXT, error TEXT, payload TEXT NOT NULL
            )
        """)
        connection.execute("DELETE FROM doc_extractions")
        rows = read_jsonl(path)
        connection.executemany(
            "INSERT INTO doc_extractions VALUES (?, ?, ?, ?, ?, ?)",
            ((row["source"], row["sha"], row["kind"], row["supplier_id"], row["error"], serialize(row))
             for row in rows),
        )
        count = connection.execute("SELECT COUNT(*) FROM doc_extractions").fetchone()[0]
    except BaseException:
        connection.execute("ROLLBACK TO load_doc_extractions")
        raise
    finally:
        connection.execute("RELEASE load_doc_extractions")
    return count


def _has_table(connection, table):
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()


def documents(connection):
    """Yield the existing consumer shape, including its file-based citation alias."""
    if _has_table(connection, "doc_extractions"):
        rows = (json.loads(row[0]) for row in connection.execute(
            "SELECT payload FROM doc_extractions ORDER BY source"))
    elif _has_table(connection, "documents"):
        rows = (dict(json.loads(payload), source=source, error=error, sha=sha)
                for source, sha, error, payload in connection.execute(
                    "SELECT source, sha, error, payload FROM documents ORDER BY source"))
    else:
        return
    for doc in rows:
        for fields in doc["fields"].values():
            for field in fields:
                if "source_file" in field:
                    field["citation"] = {"file": field["source_file"], "page": field["page"], "quote": field["quote"]}
                    for key in ("sheet", "row", "column", "locator"):
                        if key in field:
                            field["citation"][key] = field[key]
        doc.setdefault("method", " + ".join(doc.get("methods", [])))
        yield doc


def extract(connection, root, *, output=None, use_models=True):
    """Run T2 and load results for callers passing an existing SQLite connection."""
    data = Path(root).resolve()
    repo = data.parent
    output = output or repo / "store" / "docs.jsonl"
    vision, translator = configured_clients() if use_models else (None, None)
    result = run_pipeline(data, repo / "bridge" / "state.json", output, vision=vision, translator=translator)
    load_table(connection, output)
    return result["documents"] - result["cache_hits"]


def reconcile_handwriting(connection, root):
    """Compatibility hook. Extraction and ERP reconciliation now run together."""
    return None
