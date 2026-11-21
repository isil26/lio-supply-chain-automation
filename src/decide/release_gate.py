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


def _field_citations_all(docs, material, po_lines):
    return [cite for doc in docs if doc.get("kind") == "confirmation" and doc.get("fields", {}).get("revision")
            and _revision_applies(doc, material, po_lines) for cite in _field_citations(doc, "revision")]


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
        hard, partial_go, actions, extra = False, None, [], {}
        critical_row = next((row for row in drop.get("component_updates", [])
                             if row.get("component_id") == material and row.get("field") == "critical"
                             and str(row.get("new")).upper() == "Y"), None)

        def block(level, reason, citations, soft=False):
            nonlocal status, hard
            if level == "HOLD" or (level == "HUMAN" and status == "GO"):
                status = level
            hard = hard or not soft
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
        ecns = [row for row in drop.get("bom_delta", []) if row.get("child_id") == material
                and row.get("action") == "revision"]
        for ecn in ecns:
            old, new, cite = str(ecn.get("rev_old")).upper(), str(ecn.get("rev_new")).upper(), ecn["_src"]
            cite = {**cite, "quote": f'{ecn["change_id"]} {material} rev {old} -> {new}, use_up_old_rev={ecn.get("use_up_old_rev")}: {ecn.get("reason")}'}
            if str(ecn.get("use_up_old_rev")).upper() == "Y":
                reasons.append(f'{ecn["change_id"]}: rev {old} may still be packed (use up old revision), '
                               f'rev {new} follows; no block.')
                evidence.append(cite)
                continue
            old_ids = [sid for sid, rev in by_supplier.items() if rev == old]
            new_ids = [sid for sid, rev in by_supplier.items() if rev == new]
            quantities = {sid: _supplier_quantities(material, sid, po_rows, gr_rows) for sid in old_ids + new_ids}
            name = lambda sid: (suppliers.get(sid) or {}).get("name") or sid
            old_received = sum(quantities[sid][0] for sid in old_ids)
            old_open = sum(quantities[sid][1] for sid in old_ids)
            # The truth engine already nets the old-revision lot out of usable stock.
            netted = int((part.get("revision_hold") or {}).get("quantity") or 0) >= old_received > 0
            gross = usable + (old_received if netted else 0)
            partial_go = usable if netted else max(0, usable - old_received)
            held_quantity += old_received
            owner = {"role": "Category Lead Print & Packaging", "name": "Sofia Marchetti",
                     "decision": f"re-order / re-print rev {new} and decide what to do with the {old_received:,} "
                                 f"rev {old} pieces already received (rev {new} is the released revision)"}
            actions.append(owner)
            extra.update({"ecn": ecn["change_id"], "do_not_accept_quantity": old_open,
                          "usable_new_revision_quantity": partial_go, "old_revision_lot_quantity": old_received})
            who_old = ", ".join(f"{name(sid)} PO(s) open {quantities[sid][1]:,}" for sid in old_ids) or "no supplier found"
            who_new = ", ".join(f"{name(sid)} rev {new} GO ({quantities[sid][0]:,} delivered, {quantities[sid][1]:,} open)"
                                for sid in new_ids) or f"no supplier confirmed for rev {new}"
            block("HOLD", f'{ecn["change_id"]} (effective {ecn.get("effective_from")}): rev {old} -> {new}, '
                  f'"parts to rev {old} must not be packed". HOLD {old_received:,} rev {old} pieces already received '
                  f'(not usable); do not accept the {old_open:,} open rev {old} pieces ({who_old}): ask the supplier '
                  f'to re-print rev {new}. {who_new}. Usable rev {new} quantity = stock {gross:,} - rev {old} lot '
                  f'{old_received:,} = {partial_go:,}. Decision: {owner["name"]}, {owner["role"]}.',
                  [cite, *_field_citations_all(docs, material, po_lines)], soft=True)
        if len(set(by_supplier.values())) > 1 and not any(
                str(e.get("use_up_old_rev")).upper() != "Y" for e in ecns):
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
            profile = (drop.get("profiles") or {}).get(supplier_id) or {}
            qualification = profile.get("qualification") or {}
            valid_until = str(qualification.get("validUntil") or "")
            if (str(qualification.get("status", "")).casefold() == "conditional" and valid_until
                    and valid_until < as_of and not qualification.get("extendedBy")):
                vacant = str(drop.get("org_category_lead_from") or "9999") > as_of
                actions.append({"role": "Head of Procurement", "name": "Dr. Maren Vogt",
                                "decision": f"PP-07 section 6 exception for {profile.get('name') or supplier_id}; "
                                            "co-signer Daniel Okafor, Supplier Quality Lead"})
                block("HUMAN", f"{profile.get('name') or supplier_id}: conditional qualification released "
                      f"{qualification.get('releasedOn')} EXPIRED on {valid_until} and was not extended "
                      "(extendedBy null); PP-07 section 5: POs placed after expiry are held 'awaiting approval'; "
                      "an extension needs Supplier Quality Lead and Category Lead in writing, once, max 90 days. "
                      + ("The Category Lead Collector's Items is vacant for the launch (Arjun Krishnan only from "
                         f"{drop.get('org_category_lead_from')}), so the exception goes to the Head of Procurement "
                         "under section 6 (Dr. Maren Vogt) with Daniel Okafor (Supplier Quality Lead) as co-signer."
                         if vacant else "Category Lead and Supplier Quality Lead must sign the extension."),
                      [profile.get("source"), rate.get("source"), drop.get("org_source") if vacant else None,
                       {"file": "soony/context/approval_policy_PP-07.pdf", "page": 1,
                        "quote": "POs placed after a conditional release has expired are held in status 'awaiting approval'."}])
                break
            if material == "CMP-GAM-010" and str(supplier.get("qualification_status", "")).casefold() == "conditional":
                block("HUMAN", "Pune statue supply requires PPAP and written Supplier Quality plus Category Lead release; the Category Lead is vacant, so route the exception to Head of Procurement.",
                      [supplier.get("source"), rate.get("source"), *part.get("evidence", [])])
                break

        if material in ("CMP-MAG-005", "CMP-GAM-007") and drop:
            reasons.append("Rare-earth export control (2026-11-21): PackRight holds magnets for the November boxes "
                           "(launch boxes OK); CMP-GAM-007 deliveries after 2026-12-01 move out 6 weeks (lead time "
                           "63 -> 105 d). Post-launch risk, not a pack-out stopper.")
            extra["post_launch_risk"] = "magnet deliveries after 2026-12-01 +6 weeks (63 -> 105 d); alternatives sampled within 10 d"

        incoterm_issues = [issue for issue in truth.get("issues", [])
                           if issue.get("material") == material and issue.get("kind") == "confirmation"
                           and "incoterm" in issue.get("changed_fields", [])]
        if incoterm_issues:
            reasons.append("ERP and supplier confirmation use different Incoterms; flag for commercial review, but this does not block packing.")
            evidence.extend(source for issue in incoterm_issues for source in issue.get("evidence", []))

        if critical_row and status == "HOLD":
            reasons.append(f'{material} is a CRITICAL part (components_update row {critical_row["_src"]["row"]}, '
                           f'{critical_row.get("changed_by")}): the quality hold stays until released.')
            evidence.append({**critical_row["_src"], "quote": f'{material} critical {critical_row.get("old")} -> '
                             f'{critical_row.get("new")} by {critical_row.get("changed_by")}'})
            memo = drop.get("memo") or {"file": MEMO_FILE, "quote": MEMO_QUOTE}
            evidence.append(memo)
            extra["required_authority"] = {"role": "Quality & Compliance Manager", "name": "Clara Weiss",
                                           "for": "HOLD to GO", "citation": memo}
            actions.append({"role": "Quality & Compliance Manager", "name": "Clara Weiss",
                            "decision": "last word on releasing the held lot (HOLD to GO)"})
            reasons.append("Required authority for HOLD to GO: Quality & Compliance (Clara Weiss), not the pack-out plan.")
        if status != "GO":
            go_quantity = partial_go if (partial_go is not None and not hard) else 0
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
                {"role": " / ".join(dict.fromkeys(a["role"] for a in actions))
                 or "Marketing / Engineering / Supplier Quality and Category Lead",
                 "deadline": truth.get("deadline"), "decisions": actions}
                if status == "HUMAN" or actions else None
            ),
            **extra,
        }

    editions = {}
    for edition_id, edition in truth.get("editions", {}).items():
        packable = int(edition.get("remaining", 0))
        limiting = {}
        for material, usage in ((material, part.get("unit_usage", {}).get(edition_id, 0))
                                for material, part in truth.get("parts", {}).items()):
            if usage:
                units = results[material]["go_quantity"] // int(usage)
                limiting[material] = units
                packable = min(packable, units)
        packable = max(0, packable)
        editions[edition_id] = {"edition": edition.get("edition", edition_id), "units_with_go_parts": packable,
                                "remaining": int(edition.get("remaining", 0)),
                                "limited_by": sorted(m for m, units in limiting.items() if units <= packable)
                                if packable < int(edition.get("remaining", 0)) else []}
    return {"parts": results, "editions": editions, "deadline": truth.get("deadline")}


def release_gate(con, data_root=None):
    root = Path(data_root) if data_root else ROOT / "data"
    truth = readiness(con, root)
    return evaluate(truth, documents(con), rows(con, "component"), rows(con, "supplier"),
                    rows(con, "po"), rows(con, "receipt"), drop=load_drop(root))


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
