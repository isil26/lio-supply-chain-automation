"""Deterministic event triage with an optional ambiguous-event LLM pass."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from src.llm.client import LLMCallError, LLMClient

LAUNCH_ISO = "2026-11-22T20:00:00+01:00"
LOW_SCORE = 35
HIGH_SCORE = 65
LIVE_COST_USD = 0.0

CATEGORIES = ("logistics", "supplier", "customer_request", "news", "noise")
DECISIONS = ("ignore", "watch", "act", "escalate")

_CATEGORY_TERMS = {
    "logistics": (
        "port", "hafen", "港", "항", "shipment", "ship ", "carrier", "flight",
        "customs", "zoll", "douane", "dock", "landing", "ETA", "ETD", "air lot",
        "typhoon", "strike", "canceled", "cancelled", "cancellation", "truck",
    ),
    "supplier": (
        "supplier", "lieferant", "lieferanten", "供应商", "공급", "supplier id",
        "PPAP", "quality hold", "AQL", "inspection", "insolven", "price list",
        "export restriction", "rare-earth", "seltene erde", "letter", "notice",
        "artwork", "sleeve", "rev b", "revision",
    ),
    "customer_request": (
        "customer", "retailer", "kunde", "零售商", "소매", "region", "order",
        "requested", "move", "reallocate", "allocation",
    ),
    "news": (
        "news", "market", "industry", "restriction", "typhoon", "rumour",
        "rumor", "outage", "strike", "newsletter",
    ),
}

_NOISE_TERMS = (
    "irrelevant", "newsletter", "marketing roundup", "duplicate", "重复",
    "kopie", "copy of", "already received", "already processed",
)

_MATERIALITY_TERMS = (
    ("game card", "CMP-GAM-001", "game-card"),
    ("art book", "CMP-GAM-008"),
    ("statue", "CMP-GAM-010"),
    ("sleeve", "CMP-GAM-004"),
    ("case", "CMP-GAM-006"),
    ("magnet", "CMP-MAG-005"),
    ("pin", "CMP-GAM-005"),
)


def _event_text(event: dict[str, Any]) -> str:
    parts = [
        str(event.get("title") or ""),
        str(event.get("text") or event.get("summary") or ""),
        " ".join(str(x) for x in event.get("changed_files") or []),
    ]
    return "\n".join(part for part in parts if part)


def _truth_text(truth_summary: Any) -> str:
    if truth_summary is None:
        return ""
    if isinstance(truth_summary, str):
        return truth_summary
    return json.dumps(truth_summary, ensure_ascii=False, sort_keys=True, default=str)


def _supplier_ids(event: dict[str, Any]) -> list[str]:
    text = _event_text(event)
    return sorted(set(re.findall(r"SUP-\d{4}", text.upper())))


def deterministic_pass(event: dict[str, Any], truth_summary: Any = None) -> dict[str, Any]:
    text = _event_text(event)
    lower = text.casefold()
    truth = _truth_text(truth_summary)

    category = "noise"
    category_scores = {}
    for name, terms in _CATEGORY_TERMS.items():
        category_scores[name] = sum(1 for term in terms if term.casefold() in lower)
    if category_scores:
        ranked = sorted(category_scores, key=lambda name: category_scores[name], reverse=True)
        if category_scores[ranked[0]] > 0:
            category = ranked[0]
    if any(term.casefold() in lower for term in _NOISE_TERMS):
        category = "noise"

    score = 0
    factors: list[str] = []
    if category == "noise":
        score += 0
    elif category == "logistics":
        score += 28
        factors.append("logistics update")
    elif category == "supplier":
        score += 25
        factors.append("supplier update")
    elif category == "customer_request":
        score += 18
        factors.append("customer request")
    elif category == "news":
        score += 12
        factors.append("news event")

    material_hits = sorted({
        term
        for aliases in _MATERIALITY_TERMS
        for term in aliases
        if term.casefold() in lower
    })
    if material_hits:
        score += 12
        factors.append("launch component: " + ", ".join(material_hits))
    if re.search(r"\bSUP-\d{4}\b", text.upper()):
        score += 8
        factors.append("identified supplier")
    if re.search(r"\b20\d{2}-\d{2}-\d{2}\b|\b\d{1,2}[/.]\d{1,2}[/.]20\d{2}\b", text):
        score += 12
        factors.append("explicit date")
    if re.search(r"\b\d[\d,.]*\s*(?:pcs?|pieces|copies|units)\b", lower):
        score += 8
        factors.append("explicit quantity")
    if re.search(r"before launch|by launch|before 20:00|by 20:00|Sunday|deadline", lower):
        score += 18
        factors.append("launch deadline")
    if re.search(r"hold|block|cancel|strike|delay|detain|insolven|restriction|export ban|short.?ship", lower):
        score += 18
        factors.append("critical disruption")
    if re.search(r"approval|approver|sign.?off|PPAP|category lead|head of procurement", lower):
        score += 15
        factors.append("approval or release gate")
    if re.search(r"single.?source|sole source|single source", lower):
        score += 15
        factors.append("single-source dependency")

    truth_lower = truth.casefold()
    for label in (x for x in ("art book", "statue", "game card", "sleeve", "case", "magnet", "pin")
                  if x in lower and x in truth_lower):
        score += 10
        factors.append("matches current truth summary")

    if "2026-11-22" in text or "22.11.2026" in text or "launch" in lower:
        score += 8
    if re.search(r"\b(?:PPAP|release letter)\b", text, re.I):
        score = min(score, 75)

    score = min(100, score)
    if category == "news":
        score = max(score, 15)
    if category == "noise":
        score = 5

    if score >= 80:
        decision = "escalate"
    elif score >= 50:
        decision = "act"
    elif score >= 20:
        decision = "watch"
    else:
        decision = "ignore"

    evidence = _evidence_quotes(text)
    return {
        "category": category,
        "materiality": score,
        "decision": decision,
        "reason": "; ".join(factors) if factors else "No launch-relevant signal found",
        "evidence": evidence,
    }


def _evidence_quotes(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    quotes = []
    for sentence in sentences:
        clean = " ".join(sentence.split())
        if clean:
            quotes.append(clean[:240])
    return quotes[:3]


def _llm_pass(event: dict[str, Any], truth_summary: Any,
               deterministic: dict[str, Any]) -> dict[str, Any]:
    client = LLMClient(call_budget=1)
    if not client.configured():
        return deterministic

    event_text = _event_text(event)
    source_text = event_text + "\nTRUTH:\n" + _truth_text(truth_summary)
    schema = {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": list(CATEGORIES)},
            "materiality": {"type": "integer", "minimum": 0, "maximum": 100},
            "decision": {"type": "string", "enum": list(DECISIONS)},
            "reason": {"type": "string", "minLength": 1},
            "evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        },
        "required": ["category", "materiality", "decision", "reason", "evidence"],
        "additionalProperties": False,
    }
    prompt = (
        "You are triaging an inbound Soony launch event. "
        "The launch is 2026-11-22T20:00:00+01:00. "
        "Judge whether it touches a component gap, first stop, ship date, approval limit, "
        "single-source supplier or quality hold. Prefer ignore for duplicate/noise, watch for "
        "uncertain low-impact updates, act for time-bound launch action, and escalate for "
        "critical or approval-gated disruption.\n"
        f"EVENT:\n{event_text}\nTRUTH SUMMARY:\n{_truth_text(truth_summary)}\n"
        f"DETERMINISTIC FALLBACK: {json.dumps(deterministic, ensure_ascii=False)}"
    )
    try:
        result = client.complete_json(
            "triage_event", schema, prompt,
            source_text=source_text, validate_quotes=False,
        )
    except LLMCallError:
        return deterministic

    folded_source = " ".join(source_text.split()).casefold()
    valid_quotes = []
    for quote in result["evidence"]:
        folded_quote = " ".join(str(quote).split()).casefold()
        if folded_quote and folded_quote in folded_source:
            valid_quotes.append(str(quote))
    if not valid_quotes:
        return deterministic
    result["evidence"] = valid_quotes[:3]
    return result


def ensure_event_decisions(db_path: str | Path) -> sqlite3.Connection:
    db_path = str(db_path)
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS event_decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event TEXT NOT NULL,
        category TEXT NOT NULL,
        score INTEGER NOT NULL,
        decision TEXT NOT NULL,
        reason TEXT NOT NULL,
        evidence TEXT NOT NULL,
        ts TEXT NOT NULL
    )""")
    con.commit()
    return con


def _store_decision(db_path: str | Path, event: dict[str, Any],
                    decision: dict[str, Any]) -> None:
    con = ensure_event_decisions(db_path)
    try:
        con.execute(
            """INSERT INTO event_decisions
               (event, category, score, decision, reason, evidence, ts)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                json.dumps(event, ensure_ascii=False, sort_keys=True, default=str),
                decision["category"],
                int(decision["materiality"]),
                decision["decision"],
                decision["reason"],
                json.dumps(decision["evidence"], ensure_ascii=False),
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            ),
        )
        con.commit()
    finally:
        con.close()


def classify_event(event: dict[str, Any], truth_summary: Any = None,
                   db_path: str | Path = "store/soony.db") -> dict[str, Any]:
    if not isinstance(event, dict):
        raise TypeError("event must be a JSON object")
    deterministic = deterministic_pass(event, truth_summary)
    if LOW_SCORE <= int(deterministic["materiality"]) <= HIGH_SCORE:
        result = _llm_pass(event, truth_summary, deterministic)
    else:
        result = deterministic
    _store_decision(db_path, event, result)
    return result


def dashboard_decisions(db_path: str | Path = "store/soony.db",
                        limit: int = 100) -> list[dict[str, Any]]:
    con = ensure_event_decisions(db_path)
    try:
        rows = con.execute(
            "SELECT * FROM event_decisions ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["event"] = json.loads(item["event"])
            item["evidence"] = json.loads(item["evidence"])
            item["score"] = item.pop("score")
            result.append(item)
        return result
    finally:
        con.close()


def _eval() -> int:
    event_dir = Path("tests/agent_eval/events")
    events = sorted(event_dir.glob("*.json"))
    if not events:
        print("No synthetic events found")
        return 1

    category_correct: dict[str, int] = {}
    category_total: dict[str, int] = {}
    confusion = {"ignore": {"ignore": 0, "act": 0, "other": 0},
                 "act": {"ignore": 0, "act": 0, "other": 0}}
    overall_correct = 0
    for path in events:
        fixture = json.loads(path.read_text(encoding="utf-8"))
        if not fixture.get("synthetic"):
            raise RuntimeError(f"{path} is not marked synthetic")
        actual = classify_event(fixture, truth_summary=None, db_path=":memory:")
        expected_category = fixture["expected_category"]
        expected_decision = fixture["expected_decision"]
        category_total[expected_category] = category_total.get(expected_category, 0) + 1
        category_correct[expected_category] = category_correct.get(expected_category, 0)
        if actual["category"] == expected_category:
            category_correct[expected_category] += 1
        if actual["decision"] == expected_decision:
            overall_correct += 1

        actual_decision = actual["decision"]
        if actual_decision in {"ignore"}:
            actual_bucket = "ignore"
        elif actual_decision in {"act", "escalate"}:
            actual_bucket = "act"
        else:
            actual_bucket = "other"
        expected_bucket = "ignore" if expected_decision == "ignore" else (
            "act" if expected_decision in {"act", "escalate"} else "other"
        )
        confusion.setdefault(expected_bucket, {"ignore": 0, "act": 0, "other": 0})
        confusion[expected_bucket][actual_bucket] += 1

    print(f"events={len(events)}")
    print(f"decision_accuracy={overall_correct / len(events):.3f}")
    for category in CATEGORIES:
        total = category_total.get(category, 0)
        if total:
            print(f"category_accuracy.{category}={category_correct[category] / total:.3f}")
    print("ignore_vs_act_confusion=" + json.dumps(confusion, sort_keys=True))
    print(f"cost_usd={LIVE_COST_USD:.4f}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="T67 event materiality triage")
    parser.add_argument("--eval", action="store_true", help="Run synthetic event evaluation")
    args = parser.parse_args()
    if args.eval:
        return _eval()
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
