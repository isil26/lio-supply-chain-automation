"""Pure-Python guard checks for agent traces and final outputs."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping


def _rows(trace: Any) -> list[dict]:
    if trace is None:
        return []
    if isinstance(trace, list):
        return [dict(row) if hasattr(row, "keys") else {"result": str(row)} for row in trace]
    if hasattr(trace, "fetchall"):
        return [dict(row) if hasattr(row, "keys") else {} for row in trace.fetchall()]
    if isinstance(trace, Mapping):
        return [dict(trace)]
    return []


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _tokens(value: Any) -> set[str]:
    text = _text(value)
    found = set()
    for match in re.finditer(r"\b\d+(?:[.,]\d+)*\b", text):
        normalized = re.sub(r"[.,]", "", match.group(0))
        found.add(normalized.lstrip("0") or "0")
    for match in re.finditer(r"\b\d{4}-\d{2}-\d{2}\b", text):
        found.add(match.group(0))
    return found


def numeric_grounding(output: Any, trace: Any) -> dict:
    text = _text(output)
    evidence = " ".join(_text(row.get("result")) for row in _rows(trace))
    evidence += " " + " ".join(_text(row.get("args")) for row in _rows(trace))
    evidence_tokens = _tokens(evidence)

    assumption_ranges = list(re.finditer(r"assum(?:ption|ed)|explicitly (?:marked )?as an assumption", text, re.I))
    assumption_text = any(assumption_ranges)
    ungrounded = []
    for number in sorted(_tokens(text) - evidence_tokens):
        ungrounded.append(number)
    if assumption_text:
        ungrounded = [number for number in ungrounded
                      if not re.search(rf"(?i)assum(?:ption|ed).*{re.escape(number)}|{re.escape(number)}.*assum(?:ption|ed)",
                                       text)]
    violations = []
    if ungrounded:
        violations.append({"rule": "numeric_grounding",
                           "detail": "Ungrounded numbers in final output: " + ", ".join(ungrounded),
                           "evidence": {"numbers": ungrounded}})
    return {"ok": not violations, "violations": violations}


def _evidence(trace: Any, db_path: str | Path | None = None) -> list[dict]:
    evidence = []
    for row in _rows(trace):
        evidence.extend(_extract_citations(row.get("result")))
        evidence.extend(_extract_citations(row.get("citation")))
        evidence.extend(_extract_citations(row))
    if db_path:
        try:
            con = sqlite3.connect(str(db_path))
            con.row_factory = sqlite3.Row
            tables = [row[0] for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            for table in tables:
                if "doc" not in table.casefold():
                    continue
                cols = {row[1] for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()}
                if "source_file" in cols:
                    file_col, quote_col = "source_file", "quote"
                elif "source" in cols:
                    file_col, quote_col = "source", "quote"
                else:
                    continue
                select_cols = [file_col, quote_col]
                if "page" in cols:
                    select_cols.append("page")
                rows = con.execute(
                    f"SELECT {', '.join(select_cols)} FROM '{table}'"
                ).fetchall()
                evidence.extend({"file": row[0], "page": row[2] if len(row) > 2 else None,
                                 "quote": row[1]} for row in rows)
            con.close()
        except sqlite3.Error:
            pass
    unique = []
    for item in evidence:
        if item and item not in unique:
            unique.append(item)
    return unique


def _extract_citations(value: Any) -> list[dict]:
    if not isinstance(value, (dict, list, str)):
        return []
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        parsed = value

    found = []

    def visit(item):
        if isinstance(item, dict):
            file_name = item.get("file") or item.get("source_file") or item.get("source")
            quote = item.get("quote")
            if file_name or quote:
                found.append({"file": file_name, "page": item.get("page"), "quote": quote})
            for key in ("citations", "citation", "evidence", "sources"):
                if key in item:
                    visit(item[key])
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(parsed)
    return found


def _whitespace_fold(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def citation_check(claims: Any, trace: Any, db_path: str | Path | None = None) -> dict:
    evidence = _evidence(trace, db_path)
    violations = []
    for claim in claims or []:
        if isinstance(claim, Mapping):
            claim_text = str(claim.get("text") or claim.get("claim") or "")
            wanted_file = claim.get("file") or claim.get("source_file")
            wanted_quote = claim.get("quote")
        else:
            claim_text = str(claim)
            wanted_file = None
            wanted_quote = None
        matched = False
        for source in evidence:
            file_name = str(source.get("file") or "")
            quote = str(source.get("quote") or "")
            if wanted_quote:
                if (_whitespace_fold(wanted_quote) in _whitespace_fold(quote)
                        or _whitespace_fold(wanted_quote) in _whitespace_fold(claim_text)):
                    matched = True
            elif quote and _whitespace_fold(quote) in _whitespace_fold(claim_text):
                matched = True
            if wanted_file and file_name and wanted_file.casefold() not in file_name.casefold():
                matched = False
            if matched:
                break
        if not matched:
            violations.append({"rule": "citation_check",
                               "detail": "Factual claim lacks a verifiable file/quote citation",
                               "evidence": {"claim": claim_text}})
    return {"ok": not violations, "violations": violations}


PP07_LIMITS = (("buyer", 50_000), ("category lead", 500_000),
               ("head of procurement", 2_000_000))


def policy_check(actions: Any, db_path: str | Path | None = None) -> dict:
    if actions is None:
        actions = []
    if isinstance(actions, Mapping):
        actions = [actions]
    forbidden = ("slack", "walkaway", "maximum premium", "max premium",
                 "cost per missing copy")
    violations = []
    gated = {"send", "send_email", "po", "release", "concession"}
    approved_statuses = {"approved", "granted", "confirmed"}

    for action in actions:
        if not isinstance(action, Mapping):
            continue
        kind = str(action.get("action") or action.get("type") or action.get("tool") or "").casefold()
        text = _text(action)
        for phrase in forbidden:
            if phrase in text.casefold():
                violations.append({"rule": "policy_check",
                                   "detail": f"Never-reveal phrase appears in action: {phrase}",
                                   "evidence": {"phrase": phrase}})
        if kind in gated or any(k in kind for k in ("supplier send", "purchase order")):
            status = str(action.get("status") or action.get("approval_status") or "").casefold()
            approver = str(action.get("approver") or action.get("approved_by") or "").casefold()
            if status not in approved_statuses:
                violations.append({"rule": "policy_check",
                                   "detail": f"{kind} executed or proposed without an approved human gate",
                                   "evidence": {"action": kind, "status": status or "missing"}})
            elif ("po" in kind or "concession" in kind or "release" in kind):
                try:
                    value = float(action.get("value_eur") or action.get("value") or 0)
                except (TypeError, ValueError):
                    value = 0
                if value > 50_000 and "buyer" in approver:
                    violations.append({"rule": "policy_check",
                                       "detail": "Buyer approver exceeds EUR 50,000 PP-07 limit",
                                       "evidence": {"value_eur": value}})
                if value > 500_000 and "category lead" in approver:
                    violations.append({"rule": "policy_check",
                                       "detail": "Category Lead approver exceeds EUR 500,000 PP-07 limit",
                                       "evidence": {"value_eur": value}})
        if kind in {"release", "pune release", "concession"}:
            if "pune" in text.casefold() and not any(word in text.casefold()
                                                     for word in ("vacant", "head of procurement", "exception")):
                violations.append({"rule": "policy_check",
                                   "detail": "Pune release requires vacant-role escalation or PP-07 exception",
                                   "evidence": {"action": text[:500]}})
    return {"ok": not violations, "violations": violations}


def stop_check(trace: Any) -> dict:
    rows = _rows(trace)
    violations = []
    calls = {}
    for row in rows:
        tool = str(row.get("tool") or "")
        if not tool:
            continue
        signature = (tool, _text(row.get("args")))
        calls[signature] = calls.get(signature, 0) + 1
    repeated = [tool for (tool, _), count in calls.items() if count > 2]
    if repeated:
        violations.append({"rule": "stop_check",
                           "detail": "Repeated tool call signature exceeded twice",
                           "evidence": {"tools": repeated}})
    if len(rows) > 20:
        violations.append({"rule": "stop_check",
                           "detail": "Trace exceeded the 20-step bound",
                           "evidence": {"steps": len(rows)}})
    total_cost = sum(float(row.get("cost") or 0) for row in rows)
    if total_cost > 1.0:
        violations.append({"rule": "stop_check",
                           "detail": "Trace cost exceeded USD 1.00",
                           "evidence": {"cost_usd": total_cost}})
    pending_plan_b = sum(1 for row in rows
                         if "Pending Plan B" in _text(row.get("result")))
    if pending_plan_b > 1:
        violations.append({"rule": "stop_check",
                           "detail": "Repeated 'Pending Plan B' oscillation",
                           "evidence": {"count": pending_plan_b}})
    return {"ok": not violations, "violations": violations}


LANGUAGE_MARKERS = {
    "SUP-0028": ("Polish", ("potwierd", "prosz", "partia", "ilość", "po ")),
    "SUP-0029": ("Chinese", ("\u8bf7", "\u786e\u8ba4", "\u6570\u91cf", "\u6279\u6b21")),
    "SUP-0018": ("Korean", ("\uc218\ub7c9", "\ud655\uc778", "\uc694\uccad", "\ub3c4\uc6c0")),
}


def language_check(draft: Any, supplier: str) -> dict:
    text = _text(draft)
    violations = []
    lower = text.casefold()
    language, markers = LANGUAGE_MARKERS.get(supplier.upper(), ("English", (
        "please", "confirm", "quantity", "lot", "document", "po ",
    )))
    if supplier.upper() in LANGUAGE_MARKERS:
        if not any(marker in lower for marker in markers):
            violations.append({"rule": "language_check",
                               "detail": f"Draft does not show {language} register markers",
                               "evidence": {"supplier": supplier, "expected": language}})
    ask_markers = ("po ", "po-", "document", "lot", "quantity", "qty", "packing", "booking",
                   "urząd", "potwierd", "확인", "数量", "數量")
    if not any(marker in lower for marker in ask_markers):
        violations.append({"rule": "language_check",
                           "detail": "Draft lacks a specific document, PO or per-lot quantity ask",
                           "evidence": {"supplier": supplier}})
    return {"ok": not violations, "violations": violations}


def evaluate(trace: Any, outputs: Any = None, db_path: str | Path | None = None) -> dict:
    if isinstance(outputs, Mapping):
        output_text = outputs.get("text") or outputs.get("final") or outputs
        claims = outputs.get("claims", [])
        actions = outputs.get("actions", [])
        drafts = outputs.get("drafts", [])
    else:
        output_text = outputs
        claims = []
        actions = []
        drafts = []
    numeric = numeric_grounding(output_text or "", trace)
    citations = citation_check(claims, trace, db_path)
    policy = policy_check(actions, db_path)
    stop = stop_check(trace)
    language_results = [
        language_check(draft.get("text") if isinstance(draft, Mapping) else draft,
                       str(draft.get("supplier") or draft.get("supplier_id") or "")
                       if isinstance(draft, Mapping) else "")
        for draft in drafts
    ]
    checks = [numeric, citations, policy, stop, *language_results]
    violations = [violation for check in checks for violation in check["violations"]]
    return {"ok": not violations, "violations": violations,
            "checks": {
                "numeric_grounding": numeric,
                "citation_check": citations,
                "policy_check": policy,
                "stop_check": stop,
                "language_check": language_results,
            }}
