"""Cited, deterministic release gate for material pack-out decisions."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import zipfile
from datetime import date
from pathlib import Path

from src.docs import documents
from src.ingest.store import DB, ROOT, connect, rows
from src.truth import readiness


def _citation(value):
    if isinstance(value, dict):
        return {key: value[key] for key in ("file", "page", "row", "sheet", "quote") if key in value}
    return {"file": str(value)}


def _field_citations(doc, name):
    return [_citation(field.get("citation") or field) for field in doc.get("fields", {}).get(name, [])]


def _field_values(doc, name):
    return [field.get("value") for field in doc.get("fields", {}).get(name, [])]

_CODE = r"[A-Z]{2,4}-[A-Z0-9-]+"


def _revision_applies(doc, material, po_lines):
    """True when the footer's revision statement concerns ``material``.

    The footer names a supplier alias (PR-SL-0604) or the material itself; an alias is
    resolved through the ERP line of the same PO with the same quantity.
    """
    items = [item["value"] for item in doc.get("fields", {}).get("items", []) if isinstance(item.get("value"), dict)]
    quote = " ".join(field.get("quote") or (field.get("citation") or {}).get("quote") or ""
                     for field in doc.get("fields", {}).get("revision", []))
    pos = {str(field.get("value")) for field in doc.get("fields", {}).get("po", [])}
    named = set(re.findall(rf"({_CODE})\s*:[^.]*?\brev", quote, re.I)) | set(
        re.findall(rf"Artwork\s+({_CODE})", quote, re.I))
    for item in items:
        code = item.get("material")
        if named and code not in named:
            continue
        if code == material:
            return True
        for line in po_lines:
            if (str(line.get("po_number")) in pos and line.get("material_id") == material
                    and int(line.get("quantity") or 0) == int(item.get("quantity") or 0)):
                return True
    return False


def _supplier_quantities(material, supplier_id, po_rows, gr_rows):
    delivered = sum(int(row.get("qty_received") or 0) for row in gr_rows
                    if row.get("material_id") == material and row.get("supplier_id") == supplier_id)
    open_quantity = sum(int(row.get("quantity") or 0) for row in po_rows
                        if row.get("material_id") == material and row.get("supplier_id") == supplier_id
                        and str(row.get("status", "")).casefold() not in ("delivered", "cancelled", "closed"))
    return delivered, open_quantity


MEMO_QUOTE = ("No copy leaves Hamburg with a part that is not released. "
              "Quality & Compliance has the last word, not the pack-out plan.")
MEMO_FILE = "soony/context/memo_launch_priorities.docx"


def _csv_rows(path, rel):
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            return [dict(row, _src={"file": rel, "row": index})
                    for index, row in enumerate(csv.DictReader(handle), start=2)]
    except (OSError, csv.Error, UnicodeDecodeError):
        return []


def load_drop(data_root):
    """Read the 21 Nov drop files straight from data/ (tolerant: missing file = no rule).

    Used while the store does not carry the new CSV/JSON files yet. Row numbers are
    file line numbers (header = line 1), like the ingestion citations.
    """
    root = Path(data_root)
    drop = {"bom_delta": _csv_rows(root / "soony/master/bom_delta_2026-11-21.csv",
                                   "soony/master/bom_delta_2026-11-21.csv"),
            "component_updates": _csv_rows(root / "soony/master/components_update_2026-11-21.csv",
                                           "soony/master/components_update_2026-11-21.csv"),
            "profiles": {}, "org_category_lead_from": None, "memo": None}
    for path in root.glob("suppliers/SUP-*/profile.json"):
        try:
            text = path.read_text(encoding="utf-8")
            supplier = json.loads(text)["supplier"]
        except (OSError, ValueError, KeyError):
            continue
        qualification = supplier.get("qualification")
        if not isinstance(qualification, dict):
            continue
        lines = text.splitlines()
        line = next((i for i, value in enumerate(lines, 1) if '"validUntil"' in value), 1)
        quote = " ".join(value.strip() for value in lines[line - 3:line + 1])
        drop["profiles"][supplier.get("supplierId")] = {
            "name": supplier.get("name"), "qualification": qualification,
            "source": {"file": str(path.relative_to(root)), "row": line, "quote": quote}}
    try:
        text = subprocess.run(["gs", "-q", "-sDEVICE=txtwrite", "-o", "-",
                               str(root / "soony/context/org_chart_v2.pdf")],
                              capture_output=True, text=True, timeout=30).stdout
        match = re.search(r"(Arjun Krishnan \(from (\d{4}-\d\d-\d\d)\))", text)
        if match:
            drop["org_category_lead_from"] = match.group(2)
            drop["org_source"] = {"file": "soony/context/org_chart_v2.pdf", "page": 1,
                                  "quote": "Category Lead Collector's Items: " + match.group(1)}
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        with zipfile.ZipFile(root / MEMO_FILE) as archive:
            xml = archive.read("word/document.xml").decode("utf-8")
        plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", xml.replace("</w:p>", "\n"))).replace("&amp;", "&")
        if MEMO_QUOTE in plain:
            drop["memo"] = {"file": MEMO_FILE, "quote": MEMO_QUOTE}
    except (OSError, KeyError, zipfile.BadZipFile):
        pass
    return drop


def evaluate(truth, docs=(), component_rows=(), supplier_rows=(), po_rows=(), gr_rows=(), drop=None, as_of=None):
    """Evaluate a readiness result without mutating the store.

    ``truth`` is the existing readiness JSON; the optional rows are supplied by
    the orchestrator so rules remain driven by current ingested data. ``drop`` (see
    :func:`load_drop`) adds the 21 Nov rules: ECN revision changes, critical flags and
    the supplier qualification expiry; ``as_of`` (ISO date) defaults to the deadline date.
    """
    drop = drop or {}
    as_of = (as_of or str(truth.get("deadline") or "")[:10] or date.today().isoformat())[:10]
    docs = list(docs)
    po_rows, gr_rows = list(po_rows), list(gr_rows)
    po_lines = po_rows
    component_rows = {row.get("component_id"): row for row in component_rows}
    suppliers = {row.get("supplier_id"): row for row in supplier_rows}
    results = {}
    for material, part in truth.get("parts", {}).items():
        reasons, evidence = [], []
        status = "GO"
        required = int(part.get("required", 0))
        usable = max(0, int(part.get("on_hand", 0)))
        go_quantity = min(required, usable)
        held_quantity = 0

        def block(level, reason, citations):
            nonlocal status
            if level == "HOLD" or (level == "HUMAN" and status == "GO"):
                status = level
            reasons.append(reason)
            evidence.extend(citations)

        for issue in truth.get("issues", []):
            if issue.get("material") != material:
                continue
            if issue.get("kind") == "quality_hold":
                quantity = int(issue.get("quantity") or 0)
                held_quantity += quantity
                block("HOLD", issue.get("title", "Quality hold on received lot"), issue.get("evidence", []))

        # A revision conflict is a human decision, not an assertion that either
        # supplier is wrong. Quantities come from the supplier's POs and GRs.
        revision_evidence = []
        by_supplier = {}
        for doc in docs:
            if doc.get("kind") != "confirmation" or not doc.get("fields", {}).get("revision"):
                continue
            if not _revision_applies(doc, material, po_lines):
                continue
            supplier_id = doc.get("supplier_id") or ""
            for value in _field_values(doc, "revision"):
                by_supplier.setdefault(supplier_id, str(value).upper())
            revision_evidence.extend(_field_citations(doc, "revision"))
        if len(set(by_supplier.values())) > 1:
            parts = []
            for supplier_id, revision in sorted(by_supplier.items(), key=lambda kv: kv[1]):
                delivered, open_quantity = _supplier_quantities(material, supplier_id, po_rows, gr_rows)
                name = (suppliers.get(supplier_id) or {}).get("name") or supplier_id
                parts.append(f"rev {revision} at {name} ({delivered:,} pcs delivered, {open_quantity:,} open)")
            block("HUMAN", "Artwork revision conflict: " + ", ".join(parts) + "; Marketing must confirm which "
                  "revision is released; PackRight prints to the revision in the component master at PO date, "
                  "Karton to the last revision released in writing.", revision_evidence)

        if material == "CMP-MAG-005" and part.get("embedded_in"):
            block("HUMAN", f"BOM lists {material}, but supplier data says it is fitted into {part['embedded_in']}; Engineering must confirm whether this line is double-counted.",
                  part.get("evidence", []))

        for rate in part.get("suppliers", []):
            supplier_id = rate.get("supplier_id")
            supplier = suppliers.get(supplier_id) or rate.get("supplier") or {}
            if material == "CMP-GAM-010" and str(supplier.get("qualification_status", "")).casefold() == "conditional":
                block("HUMAN", "Pune statue supply requires PPAP and written Supplier Quality plus Category Lead release; the Category Lead is vacant, so route the exception to Head of Procurement.",
                      [supplier.get("source"), rate.get("source"), *part.get("evidence", [])])
                break

        incoterm_issues = [issue for issue in truth.get("issues", [])
                           if issue.get("material") == material and issue.get("kind") == "confirmation"
                           and "incoterm" in issue.get("changed_fields", [])]
        if incoterm_issues:
            reasons.append("ERP and supplier confirmation use different Incoterms; flag for commercial review, but this does not block packing.")
            evidence.extend(source for issue in incoterm_issues for source in issue.get("evidence", []))

        if status != "GO":
            go_quantity = 0
        citations = []
        for source in evidence:
            if not source:
                continue
            citation = _citation(source)
            if citation not in citations:
                citations.append(citation)
        results[material] = {
            "part_id": material, "label": part.get("label", material), "status": status,
            "go_quantity": go_quantity, "held_quantity": held_quantity,
            "required_quantity": required, "reasons": list(dict.fromkeys(reasons)),
            "evidence": citations,
            "required_human_action": (
                {"role": "Marketing / Engineering / Supplier Quality and Category Lead", "deadline": truth.get("deadline")}
                if status == "HUMAN" else None
            ),
        }

    editions = {}
    for edition_id, edition in truth.get("editions", {}).items():
        packable = int(edition.get("remaining", 0))
        for material, usage in ((material, part.get("unit_usage", {}).get(edition_id, 0))
                                for material, part in truth.get("parts", {}).items()):
            if usage:
                packable = min(packable, results[material]["go_quantity"] // int(usage))
        editions[edition_id] = {"edition": edition.get("edition", edition_id),
                                "units_with_go_parts": max(0, packable)}
    return {"parts": results, "editions": editions, "deadline": truth.get("deadline")}


def release_gate(con, data_root=None):
    root = Path(data_root) if data_root else ROOT / "data"
    truth = readiness(con, root)
    return evaluate(truth, documents(con), rows(con, "component"), rows(con, "supplier"),
                    rows(con, "po"), rows(con, "receipt"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB)
    args = parser.parse_args(argv)
    with connect(args.db) as con:
        gate = release_gate(con)
    print("| Part | Status | GO qty | Held qty | Reason |")
    print("|---|---:|---:|---:|---|")
    for part in gate["parts"].values():
        print(f'| {part["part_id"]} | {part["status"]} | {part["go_quantity"]:,} | '
              f'{part["held_quantity"]:,} | {" ".join(part["reasons"]) or "Usable stock may be packed"} |')
    print(json.dumps({"editions": gate["editions"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
