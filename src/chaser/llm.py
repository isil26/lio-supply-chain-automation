import re
from datetime import datetime
from typing import Protocol

from .models import ReplyParse


class LLMClient(Protocol):
    def parse_reply(self, text: str) -> ReplyParse:
        ...


class DeterministicFakeLLM:
    """Offline parser used by demos and tests; no network or credentials."""

    def parse_reply(self, text: str) -> ReplyParse:
        lowered = text.lower()
        quantity = None
        quantity_match = re.search(r"(\d[\d,.]*)\s*(?:pcs|pieces|units|items|ea|개|件|szt)\b", lowered)
        if quantity_match:
            quantity = int(re.sub(r"[,.]", "", quantity_match.group(1)))

        new_eta = None
        weekday_match = re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lowered)
        if weekday_match:
            new_eta = weekday_match.group(1).title()
        iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+\-]+)?)\b", text)
        if iso_match:
            new_eta = iso_match.group(1).replace(" ", "T")

        uncertain = any(word in lowered for word in ("maybe", "possible", "unclear", "expected", "approximately"))
        if "cannot" in lowered or "unable" in lowered or "cancel" in lowered:
            status = "blocked"
        elif "shipped" in lowered or "dispatched" in lowered or "sent" in lowered:
            status = "shipped"
        elif "confirmed" in lowered or "accept" in lowered:
            status = "confirmed"
        elif "delay" in lowered or "late" in lowered or "will miss" in lowered:
            status = "delayed"
        else:
            status = "needs_clarification"

        if uncertain:
            status = "unconfirmed"
            confidence = 0.55
        else:
            confidence = 0.85 if status in {"shipped", "confirmed", "delayed", "blocked"} else 0.45
        needs_human = status in {"blocked", "delayed", "needs_clarification", "unconfirmed"} or confidence < 0.6

        document_ref = re.search(
            r"\b(?:booking(?:\s+(?:number|no\.?|reference))?|packing\s+list|bill\s+of\s+lading|"
            r"awb|air\s+waybill|forwarder(?:\s+release)?|truck\s+(?:plate|slot)|"
            r"pallet(?:\s+label)?|lot\s+(?:number|id)|reference\s+(?:number|no\.?))\b",
            lowered,
        )
        if document_ref:
            commitment_strength = "document_or_booking_reference"
            commitment_score = 3
            what_to_ask_next = "No further supplier evidence is needed; route the reference for verification."
        elif new_eta and quantity is not None:
            commitment_strength = "date_and_quantity"
            commitment_score = 2
            what_to_ask_next = "Ask for the packing list or booking reference to verify the commitment."
        elif new_eta:
            commitment_strength = "date_only"
            commitment_score = 1
            what_to_ask_next = "Ask for the confirmed per-lot quantity and a packing list or booking reference."
        else:
            commitment_strength = "none"
            commitment_score = 0
            what_to_ask_next = "Ask for a confirmed quantity, ETA, and verifiable document or booking reference."
        return ReplyParse(status=status, new_eta=new_eta, quantity=quantity,
                          confidence=confidence, needs_human=needs_human,
                          commitment_strength=commitment_strength,
                          commitment_score=commitment_score,
                          what_to_ask_next=what_to_ask_next)
