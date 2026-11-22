"""Closed tool registry for the launch agents.

The handlers in this module are deliberately thin adapters.  Forecasts,
document facts, approval policy, and supplier actions remain owned by their
existing deterministic modules.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from bridge.live import PortalMirror
from src.chaser.agent import SupplierChaser
from src.chaser.models import Issue
from src.chaser.store import ChaserStore
from src.decide import choose as choose_options
from src.decide.expedite import choose as score_expedite
from src.decide.reliability import SupplierReliability
from src.decide.release_gate import release_gate
from src.docs import documents
from src.ingest.store import DB, ROOT, connect, rows
from src.truth import readiness
from src.truth.sensitivity import calibrate_supplier_lags, counterfactual


def _citation(source: dict | None) -> dict:
    if not source:
        return {}
    return {key: source[key] for key in ("file", "page", "row", "sheet", "quote") if key in source}


def _citations(items) -> list[dict]:
    result = []
    for item in items or []:
        citation = _citation(item if isinstance(item, dict) else None)
        if citation and citation not in result:
            result.append(citation)
    return result


def _result(value: Any, citations=()) -> dict:
    return {"value": value, "citations": _citations(citations)}


def _text(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


class _ToolContext:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.data_root = ROOT / "data"
        portal = PortalMirror(self.db_path.parent / "portal-sync", self.data_root)
        self.data_root = portal.current() or self.data_root

    def db(self):
        return connect(self.db_path)

    def truth(self, con):
        return readiness(con, self.data_root)

    def docs(self, con):
        return list(documents(con))


def _get_readiness(ctx, args):
    with ctx.db() as con:
        truth = ctx.truth(con)
    citations = [truth["source"], *(source for item in truth["issues"] for source in item.get("evidence", []))]
    return _result(truth, citations)


def _list_shortfalls(ctx, args):
    with ctx.db() as con:
        truth = ctx.truth(con)
    parts = [part for part in truth["parts"].values() if part["shortfall"] > 0 and not part["embedded_in"]]
    return _result(parts, [source for part in parts for source in part.get("evidence", [])])


def _release_gate_status(ctx, args):
    with ctx.db() as con:
        gate = release_gate(con, ctx.data_root)
    part_id = args.get("part_id")
    if part_id:
        value = gate["parts"].get(str(part_id))
        if value is None:
            raise ValueError(f"Unknown part_id: {part_id}")
        return _result(value, value.get("evidence", []))
    return _result(gate, [source for part in gate["parts"].values() for source in part.get("evidence", [])])


def _packplan(ctx, args):
    changes = args.get("changes") or {}
    if not isinstance(changes, dict):
        raise ValueError("changes must be an object")
    with ctx.db() as con:
        truth = ctx.truth(con)
    from src.decide.packplan import plan, summarize
    return _result(summarize(plan(truth, changes or None)), [truth["source"]])


def _whatif(ctx, args):
    changes = args.get("changes", {})
    with ctx.db() as con:
        truth = ctx.truth(con)
        first_shift = truth["shifts"][0][0] if truth["shifts"] else truth["deadline"]
        profiles = calibrate_supplier_lags(con, before=first_shift)
    return _result(counterfactual(truth, changes, lag_profiles=profiles), [truth["source"]])


def _supplier_history(ctx, args):
    supplier_id = str(args["supplier_id"])
    with ctx.db() as con:
        model = SupplierReliability(con)
    profile = model.profile(supplier_id)
    return _result(profile, profile.get("evidence", []))


def _search_documents(ctx, args):
    query = str(args.get("query", "")).strip().casefold()
    if not query:
        raise ValueError("query is required")
    supplier_id = args.get("supplier_id")
    hits = []
    with ctx.db() as con:
        docs = ctx.docs(con)
    for doc in docs:
        if supplier_id and doc.get("supplier_id") != supplier_id:
            continue
        for field_name, fields in doc.get("fields", {}).items():
            for field in fields:
                text = _text(field.get("value", "")).casefold()
                quote = str(field.get("quote", "")).casefold()
                if query in text or query in quote or query in doc.get("source", "").casefold():
                    hits.append({
                        "file": doc.get("source"),
                        "field": field_name,
                        "value": field.get("value"),
                        "citation": _citation(field.get("citation") or field),
                    })
    return _result(hits, [hit["citation"] for hit in hits])


def _get_document(ctx, args):
    filename = str(args["file"])
    with ctx.db() as con:
        docs = ctx.docs(con)
    matches = [doc for doc in docs if doc.get("source") == filename or Path(doc.get("source", "")).name == filename]
    if not matches:
        raise ValueError(f"document not found: {filename}")
    doc = matches[0]
    citations = [field.get("citation") or field for fields in doc.get("fields", {}).values() for field in fields]
    return _result(doc, citations)


def _list_shipments(ctx, args):
    with ctx.db() as con:
        values = [dict(row) for row in rows(con, "shipment")]
    return _result(values, [row.get("source") for row in values])


def _get_po(ctx, args):
    po_number = str(args["po_number"])
    with ctx.db() as con:
        values = [dict(row) for row in rows(con, "po") if str(row["po_number"]) == po_number]
    if not values:
        raise ValueError(f"PO not found: {po_number}")
    return _result(values, [row.get("source") for row in values])


def _compare_sources(ctx, args):
    material_id = str(args["material_id"])
    with ctx.db() as con:
        truth = ctx.truth(con)
        docs = ctx.docs(con)
        stock = [dict(row) for row in rows(con, "stock") if row["material_id"] == material_id]
        receipts = [dict(row) for row in rows(con, "receipt") if row["material_id"] == material_id]
    part = truth["parts"].get(material_id)
    related = [issue for issue in truth["issues"] if issue.get("material") == material_id]
    value = {"material": material_id, "truth": part, "stock": stock, "receipts": receipts, "issues": related,
             "documents": [doc for doc in docs if material_id.casefold() in _text(doc).casefold()]}
    citations = ([*part.get("evidence", [])] if part else []) + [row.get("source") for row in stock + receipts]
    citations += [source for issue in related for source in issue.get("evidence", [])]
    return _result(value, citations)


def _breakeven(ctx, args):
    option_id = str(args["option_id"])
    loss = args.get("loss_per_copy")
    with ctx.db() as con:
        truth = ctx.truth(con)
        options = choose_options(con, truth, ctx.data_root)
    option = next((item for item in options if item["id"] == option_id), None)
    if option is None:
        valid = [
            {"id": item["id"], "title": item.get("title"), "price": item.get("price"),
             "material": item.get("material")}
            for item in options
        ]
        raise ValueError(f"option not found: {option_id}; valid option_ids: {json.dumps(valid, ensure_ascii=False)}")
    quantity = truth["parts"].get(option.get("material"), {}).get("shortfall", 0)
    if not quantity:
        quantity = int((option.get("cost_of_waiting") or {}).get("units", 0))
    report = score_expedite(
        [{"label": "Wait", "cost_eur": 0}, {"label": option["title"], "cost_eur": option.get("price") or 0,
          "p_on_time": None, "evidence": option.get("evidence", [])}],
        loss, quantity,
    )
    return _result(report, option.get("evidence", []))


def _list_options(ctx, args):
    with ctx.db() as con:
        truth = ctx.truth(con)
        options = choose_options(con, truth, ctx.data_root)
    return _result([
        {"id": item["id"], "title": item.get("title"), "kind": item.get("kind"),
         "price": item.get("price"), "currency": item.get("currency"),
         "material": item.get("material"), "recommendation": item.get("recommendation")}
        for item in options
    ], [source for item in options for source in item.get("evidence", [])])


def _draft_email(ctx, args):
    issue_data = dict(args.get("issue") or {})
    issue_data["supplier_id"] = args["supplier_id"]
    with ctx.db() as con:
        if not issue_data.get("component"):
            shortfall_rows = []
            truth = ctx.truth(con)
            for material_id, part in truth["parts"].items():
                if part["shortfall"] > 0 and not part["embedded_in"]:
                    shortfall_rows.append((material_id, part["shortfall"]))
            issue_data["component"] = shortfall_rows[0][0] if shortfall_rows else "CMP-GAM-008"
        if not issue_data.get("po"):
            po_rows = [dict(row) for row in rows(con, "po")
                        if row["supplier_id"] == args["supplier_id"]
                        and row["material_id"] == issue_data["component"]]
            if po_rows:
                po_rows.sort(key=lambda row: str(row.get("requested_date") or ""), reverse=True)
                issue_data["po"] = po_rows[0]["po_number"]
        if not issue_data.get("what_we_need"):
            issue_data["what_we_need"] = (
                f"Provide a verifiable dated lot and quantity for {issue_data['component']} "
                "and confirm recovery options before the launch deadline."
            )
    if "deadline" not in issue_data:
        with ctx.db() as con:
            issue_data["deadline"] = ctx.truth(con)["deadline"]
    issue = Issue.from_dict(issue_data)
    store = ChaserStore(ctx.db_path)
    existing = next((thread for thread in store.list_threads()
                     if thread["supplier_id"] == issue.supplier_id
                     and thread["component"] == issue.component
                     and thread["po"] == issue.po
                     and thread["state"] in {"pending", "approved"}), None)
    if existing:
        return _result(existing)
    draft = SupplierChaser(store, data_root=ctx.data_root).draft(issue, args.get("tone"))
    return _result(draft)


def _send_email(ctx, args):
    if args.get("mode", "dry-run") != "dry-run":
        raise PermissionError("agent send_email is restricted to dry-run")
    result = SupplierChaser(ChaserStore(ctx.db_path), data_root=ctx.data_root).send(
        str(args["draft_id"]), mode="dry-run"
    )
    return _result(result)


def _parse_reply(ctx, args):
    result = SupplierChaser(ChaserStore(ctx.db_path), data_root=ctx.data_root).parse_reply(
        str(args["thread_id"]), str(args["text"])
    )
    return _result(result)


def _pending_decision(ctx, payload):
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    option_id = hashlib.sha256(encoded.encode()).hexdigest()[:16]
    payload = {**payload, "id": option_id, "status": "pending", "approval_required": True}
    with ctx.db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS decisions (
            id TEXT PRIMARY KEY, status TEXT NOT NULL, decided_at TEXT NOT NULL, payload TEXT NOT NULL
        )""")
        con.execute("INSERT OR REPLACE INTO decisions VALUES (?, 'pending', datetime('now'), ?)",
                    (option_id, json.dumps(payload, ensure_ascii=False)))
    return payload


def _propose_option(ctx, args):
    payload = _pending_decision(ctx, {
        "kind": args["kind"], "title": args["title"], "recommendation": args["rationale"],
        "evidence": args.get("evidence", []),
    })
    return _result(payload, payload["evidence"])


def _escalate(ctx, args):
    with ctx.db() as con:
        truth = ctx.truth(con)
        options = choose_options(con, truth, ctx.data_root)
    signers = []
    for option in options:
        block = option.get("approval_block")
        if block:
            signers.extend(block.get("required_signers", []))
            signers.append(block.get("exception", {}))
    payload = {"role": args["role"], "reason": args["reason"], "evidence": args.get("evidence", []),
               "required_signers": signers, "status": "pending_human"}
    return _result(payload, payload["evidence"])


def _request_review(ctx, args):
    review = {"file": str(args["file"]), "reason": str(args["reason"])}
    with ctx.db() as con:
        current = con.execute("SELECT value FROM state WHERE key='documentReviews'").fetchone()
        reviews = json.loads(current[0]) if current else []
        if review not in reviews:
            reviews.append(review)
        con.execute("INSERT OR REPLACE INTO state(key, value) VALUES ('documentReviews', ?)",
                    (json.dumps(reviews, ensure_ascii=False),))
    return _result(review, [{"file": review["file"]}])


def _schema(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def all_tools(db_path=DB) -> list[dict]:
    ctx = _ToolContext(db_path)
    text = {"type": "string"}
    tools = [
        ("get_readiness", "Compute the deterministic cited readiness forecast; use first for a launch overview.", _schema({},), _get_readiness, False),
        ("list_shortfalls", "List components whose deterministic required quantity exceeds usable stock/inbound; use to identify every current gap.", _schema({}), _list_shortfalls, False),
        ("release_gate_status", "Read-only cited release gate: which parts may go in the box now (GO), are held (HOLD, e.g. quarantined lot) or need a named human decision (HUMAN, e.g. conflicting revisions), with quantities per revision. Use for what may be packed and who must decide; one part_id optional.", _schema({"part_id": text}), _release_gate_status, False),
        ("packplan", "Read-only exact pack-out plan: which edition (CE/STD) and line packs what, baselines, Pareto frontier, and what-if changes such as {\"changes\":{\"part_arrives_earlier\":{\"CMP-GAM-001\":12}}} (hours earlier), release_quarantined or restore_stock ({part: units}). Use for how many units each edition can pack and what an earlier arrival changes; quote only units from its result.", _schema({"changes": {"type": "object"}}), _packplan, False),
        ("whatif", "Replay a readiness scenario without mutating state; example changes={\"release_lot\":\"...\"}.", _schema({"changes": {"type": "object"}}, ("changes",)), _whatif, False),
        ("supplier_history", "Return calibrated lateness and source evidence for one real SUP-#### supplier, e.g. SUP-0028.", _schema({"supplier_id": text}, ("supplier_id",)), _supplier_history, False),
        ("search_documents", "Search extracted facts and exact citations. Query distinctive terms such as a PO, material, notice filename, AQL, inspection, or release; do not use only 'launch'.", _schema({"query": text, "supplier_id": text}), _search_documents, False),
        ("get_document", "Open one extracted document by exact filename or basename and return all quoted fields; use after search_documents.", _schema({"file": text}, ("file",)), _get_document, False),
        ("list_shipments", "List normalized shipment rows with source citations when an inbound ETA or tracker contradiction matters.", _schema({}), _list_shipments, False),
        ("get_po", "Return normalized PO lines and source citations for a real PO number, e.g. 4500318768.", _schema({"po_number": text}, ("po_number",)), _get_po, False),
        ("compare_sources", "Compare SAP, receipts, notices and reconciled truth for one material, e.g. CMP-GAM-008.", _schema({"material_id": text}, ("material_id",)), _compare_sources, False),
        ("list_options", "List current deterministic Plan B options with their real option IDs; call before breakeven.", _schema({}), _list_options, False),
        ("breakeven", "Calculate deterministic expedite break-even sensitivity; loss_per_copy stays null when Dr. Vogt has not supplied it.", _schema({"option_id": text, "loss_per_copy": {"type": ["number", "null"]}}, ("option_id",)), _breakeven, False),
        ("draft_email", "Create exactly one guarded, approval-required supplier-language draft per supplier/component/PO issue. Supply real SUP-#### and issue fields; example supplier_id=SUP-0028.", _schema({
            "supplier_id": text,
            "issue": {"type": "object", "properties": {
                "component": text, "po": text, "what_we_need": text,
                "supplier_id": text,
            }},
            "tone": text,
        }, ("supplier_id", "issue")), _draft_email, False),
        ("send_email", "Attempt only a dry-run for a previously approved draft; never send real email and never bypass the human gate.", _schema({"draft_id": text, "mode": text}, ("draft_id",)), _send_email, True),
        ("parse_reply", "Parse a supplier reply and advance the persisted R0-R4 ladder using the cited thread id.", _schema({"thread_id": text, "text": text}, ("thread_id", "text")), _parse_reply, False),
        ("propose_option", "Persist one pending Plan B option for human approval; it is not an execution or commitment.", _schema({"kind": text, "title": text, "rationale": text, "evidence": {"type": "array"}}, ("kind", "title", "rationale")), _propose_option, True),
        ("escalate_to_human", "Route a cited issue to the PP-07 human signer; use for quality holds, vacant roles, and unknown facts.", _schema({"role": text, "reason": text, "evidence": {"type": "array"}}, ("role", "reason")), _escalate, True),
        ("request_review", "Persist a human document-review request when a new or unsupported format/fact prevents a safe conclusion.", _schema({"file": text, "reason": text}, ("file", "reason")), _request_review, True),
    ]
    return [{"name": name, "description": description, "input_schema": schema,
             "handler": lambda args, fn=handler: fn(ctx, args), "needs_approval": approval}
            for name, description, schema, handler, approval in tools]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--list", action="store_true", help="print names and JSON schemas")
    args = parser.parse_args(argv)
    if not args.list:
        parser.error("use --list")
    for tool in all_tools(args.db):
        print(json.dumps({key: tool[key] for key in ("name", "description", "input_schema", "needs_approval")},
                         ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
