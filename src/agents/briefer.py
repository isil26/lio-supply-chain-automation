"""Grounded one-screen launch brief for Dr. Maren Vogt."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .harness import numeric_grounding, policy_check
from .knowledge import load_pack
from .llm_adapter import HTTPAdapter
from .runtime import Agent, Tool


BRIEFER_PROMPT = f"""You are Soony's Briefer for Dr. Maren Vogt.
Input contains only verifier-approved claims and tool-computed options. Return
plain business English (German only when requested), under 180 words, with:
headline; top 3 risks each with source file/page/quote citation; recommended
action and its exact tool price; PP-07 signer; what we do not know (cost per
missing copy); and the decision requested.
Copy every number exactly from the supplied tool results. Never calculate,
round, interpolate, or introduce a number. Do not turn an unknown into an
assumption. Cite every factual risk. If grounding fails, return
{{"status":"rejected","reason":"numeric grounding failed"}}.
{load_pack("planner")}"""


def briefer_agent(llm=None, db="store/soony.db") -> Agent:
    """Construct the briefer; it has no tools and cannot create new numbers."""
    return Agent("briefer", BRIEFER_PROMPT, [], llm=llm or HTTPAdapter(),
                 max_steps=2, budget_usd=0.30)


def validate_brief(text: str, tool_results: Any) -> dict:
    words = len(str(text).split())
    report = numeric_grounding(text, tool_results)
    actions = _tool_payloads(tool_results, {"propose_option", "escalate_to_human"})
    report["violations"].extend(policy_check(actions)["violations"])
    violations = list(report["violations"])
    if words >= 180:
        violations.append({"rule": "brief_length", "detail": f"Brief has {words} words; maximum is 179"})
    return {"ok": not violations, "violations": violations, "words": words}


def _tool_payloads(tool_results: Any, names: set[str]) -> list[dict]:
    """Extract only persisted decision/escalation payloads from tool results."""
    values = tool_results if isinstance(tool_results, list) else [tool_results]
    payloads = []
    for item in values:
        if not isinstance(item, dict):
            continue
        name = str(item.get("tool") or item.get("name") or "").casefold()
        if name in names:
            payload = item.get("result", item)
            if isinstance(payload, dict) and isinstance(payload.get("value"), dict):
                payload = payload["value"]
            if isinstance(payload, dict):
                payloads.append(payload)
    return payloads


def build_brief(claims: list[dict], options: list[dict], decision: str,
                signer: str, unknown: str = "Cost per missing copy is not known; ask Dr. Vogt.") -> str:
    """Render a deterministic fallback without deriving any numeric value."""
    risks = []
    for claim in claims[:3]:
        citation = claim.get("citation") or claim.get("source") or {}
        if isinstance(citation, dict):
            cite = " ".join(str(citation.get(k)) for k in ("file", "page", "quote") if citation.get(k))
        else:
            cite = str(citation)
        risks.append(f"- {claim.get('text', claim.get('claim', 'Unknown risk'))} [{cite}]")
    tool_options = _tool_payloads(options, {"propose_option"})
    tool_escalations = _tool_payloads(options, {"escalate_to_human"})
    action = tool_options[0] if tool_options else (options[0] if options else {})
    title = action.get("title", "No priced option is available")
    price = action.get("price", action.get("cost_eur", action.get("value_eur", "unknown")))
    signer_values = []
    for payload in tool_escalations:
        signer_values.extend(payload.get("required_signers", []))
        if payload.get("role"):
            signer_values.append(payload["role"])
    signer = ", ".join(str(value) for value in signer_values if value) or "unknown; route through PP-07"
    validation = validate_brief(
        f"RECOMMENDED ACTION: {title} — price {price}. SIGNER: {signer.replace('PP-07', 'policy route')}.",
        [*options],
    )
    if not validation["ok"]:
        return json.dumps({"status": "rejected", "reason": "brief validation failed",
                           "violations": validation["violations"]}, ensure_ascii=False)
    brief = "\n".join([
        f"HEADLINE: {decision}",
        "TOP RISKS:",
        *risks,
        f"RECOMMENDED ACTION: {title} — price {price}.",
        f"PP-07 SIGNER: {signer}.",
        f"WE DO NOT KNOW: {unknown}",
        "DECISION REQUESTED: Approve or reject the recommended action.",
    ])
    return brief


def _demo() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="art_book")
    parser.add_argument("--fake", action="store_true")
    args = parser.parse_args()
    if args.fake:
        claims = [{"text": "The receiving scan needs review.", "citation": {
            "file": "WZ-261116-473.jpg", "page": "1", "quote": "handwritten correction"}}]
        options = [{"title": "Review the receiving correction", "cost_eur": "unknown"}]
        print(build_brief(claims, options, "Collector's Edition readiness is blocked by verified evidence.",
                          "Dr. Vogt under PP-07"))
    else:
        result = briefer_agent().run(f"Prepare the {args.scenario} brief from the verified claims and options.")
        print(result.get("text", json.dumps(result, ensure_ascii=False)))
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
