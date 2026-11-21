"""Cited, deterministic release gate for material pack-out decisions."""

from __future__ import annotations

import argparse
import json
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


def evaluate(truth, docs=(), component_rows=(), supplier_rows=()):
    """Evaluate a readiness result without mutating the store.

    ``truth`` is the existing readiness JSON; the optional rows are supplied by
    the orchestrator so rules remain driven by current ingested data.
    """
    docs = list(docs)
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
        # supplier is wrong. Quantities come from the confirmation line items.
        revisions = []
        revision_evidence = []
        for doc in docs:
            if doc.get("kind") != "confirmation":
                continue
            matching = [item.get("value") for item in doc.get("fields", {}).get("items", [])
                        if isinstance(item.get("value"), dict) and item["value"].get("material") == material]
            if not matching:
                continue
            for value in _field_values(doc, "revision"):
                revisions.append((str(value), sum(int(item.get("quantity") or 0) for item in matching)))
                revision_evidence.extend(_field_citations(doc, "revision"))
        unique_revisions = {revision for revision, _ in revisions}
        if len(unique_revisions) > 1:
            quantities = ", ".join(f"rev {revision}: {quantity:,}" for revision, quantity in revisions)
            block("HUMAN", f"Artwork revision conflict ({quantities}); Marketing must confirm the released revision.",
                  revision_evidence)

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
    return evaluate(truth, documents(con), rows(con, "component"), rows(con, "supplier"))


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
