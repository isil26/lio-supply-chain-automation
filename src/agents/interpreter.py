"""Supplier-reply interpreter with a bounded, citation-first agent path."""
from __future__ import annotations

import argparse
import json
import re

from pathlib import Path
from typing import Any

from .knowledge import load_pack
from .llm_adapter import HTTPAdapter
from src.chaser.llm import DeterministicFakeLLM
from .runtime import Agent, Tool
from .tools import all_tools


INTERPRETER_PROMPT = f"""You are Soony's Reply Interpreter.
Read one supplier reply and its thread. Use only parse_reply, search_documents,
supplier_history, escalate_to_human and request_review. Return only JSON with:
language, english_translation, commitment (strength one of none/date_only/date_and_quantity/documented,
date, quantity, document_ref), contradictions_with_known_facts, what_to_ask_next,
ladder_next (R0, R1, R2, R3, R4, or escalate), needs_human, and quotes.
Every non-null extracted date, quantity, or document_ref must have its exact
verbatim source substring in quotes. Do not infer a date or quantity from context.
An ETA-only answer is date_only; a quantity without a date is none. A booking,
packing-list, pallet, lot, truck, or forwarder reference is documented only when
the reply contains the reference. Mark unknown or contradictory facts for human
review. Never invent a translation, supplier fact, or commitment.
{load_pack("chaser")}"""

_ALLOWED = {"parse_reply", "search_documents", "supplier_history",
            "escalate_to_human", "request_review"}


def _registry(db_path: str | Path) -> list[Tool]:
    result = []
    for item in all_tools(db_path):
        if item["name"] in _ALLOWED:
            result.append(Tool(
                item["name"],
                lambda _handler=item["handler"], **kwargs: _handler(kwargs),
                item["input_schema"],
                needs_approval=item["needs_approval"],
                description=item["description"],
            ))
    return result


def interpreter_agent(llm=None, db="store/soony.db") -> Agent:
    """Construct the reply interpreter with only safe evidence tools."""
    return Agent("reply_interpreter", INTERPRETER_PROMPT, _registry(db), llm=llm or HTTPAdapter(),
                 max_steps=3, budget_usd=0.30)


def _language(text: str) -> str:
    if "[KO]" in text or re.search(r"[\uac00-\ud7af]", text):
        return "KO"
    if "[ZH]" in text or re.search(r"[\u4e00-\u9fff]", text):
        return "ZH"
    if "[PL]" in text or re.search(r"[ąćęłńóśźż]", text, re.I):
        return "PL"
    if "[DE]" in text or re.search(r"\b(?:der|die|das|nicht|Lieferung)\b", text, re.I):
        return "DE"
    return "EN"


def interpret_reply(text: str, known_facts: list[str] | None = None) -> dict[str, Any]:
    """Offline, conservative schema normalizer used by demos and regression tests."""
    parsed = DeterministicFakeLLM().parse_reply(text)
    date_quote = None
    date_match = re.search(
        r"\b(?:20\d{2}-\d{2}-\d{2}(?:[T ][0-9:.+\-]+)?|"
        r"Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", text, re.I)
    if date_match:
        date_quote = date_match.group(0)
    quantity_quote = None
    quantity_match = re.search(
        r"\b\d[\d,.]*\s*(?:pcs|pieces|units|items|ea|개|件|szt)\b", text, re.I)
    if quantity_match:
        quantity_quote = quantity_match.group(0)
    quantity = parsed.quantity
    if quantity_quote:
        quantity_value = re.match(r"[\d][\d\s,.]*", quantity_quote)
        if quantity_value:
            quantity = int(re.sub(r"[^\d]", "", quantity_value.group(0)))
    ref_match = re.search(
        r"\b(?:booking(?:\s+(?:number|no\.?|reference))?|packing\s+list|"
        r"bill\s+of\s+lading|awb|air\s+waybill|forwarder(?:\s+release)?|"
        r"truck\s+(?:plate|slot)|pallet(?:\s+label)?|lot\s+(?:number|id)|"
        r"reference\s+(?:number|no\.?))\b(?:[:# -]*[A-Z0-9][A-Z0-9./_-]*)?",
        text, re.I)
    document_ref = ref_match.group(0).strip() if ref_match else None
    strength = parsed.commitment_strength
    if strength == "document_or_booking_reference":
        strength = "documented"
    quotes = [q for q in (date_quote, quantity_quote, document_ref) if q]
    contradictions = []
    for fact in known_facts or []:
        if fact and fact.casefold() in text.casefold():
            contradictions.append(fact)
    ladder = "escalate" if parsed.needs_human and parsed.commitment_score == 0 else f"R{min(4, parsed.commitment_score + 1)}"
    return {
        "language": _language(text),
        "english_translation": text,
        "commitment": {
            "strength": strength,
            "date": parsed.new_eta,
            "quantity": quantity,
            "document_ref": document_ref,
        },
        "contradictions_with_known_facts": contradictions,
        "what_to_ask_next": parsed.what_to_ask_next,
        "ladder_next": ladder,
        "needs_human": bool(parsed.needs_human),
        "quotes": quotes,
    }


def _demo() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reply", nargs="?", default="[PL] Możemy zweryfikować 8 000 szt. z zapasu gotowego.")
    parser.add_argument("--fake", action="store_true")
    args = parser.parse_args()
    if args.fake:
        print(json.dumps(interpret_reply(args.reply), ensure_ascii=False, indent=2))
    else:
        result = interpreter_agent().run(args.reply)
        print(result.get("text", json.dumps(result, ensure_ascii=False)))
    return 0


if __name__ == "__main__":
    raise SystemExit(_demo())
