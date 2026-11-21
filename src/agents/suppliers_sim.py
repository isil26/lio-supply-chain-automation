"""Deterministic external-world simulator for supplier demo exchanges."""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .llm_adapter import Adapter, FakeLLM, HTTPAdapter


@dataclass(frozen=True)
class SupplierPersona:
    supplier_id: str
    name: str
    language_marker: str
    register: str
    behaviour: str
    hidden_ground_truth: dict[str, Any]


PERSONAS: dict[str, SupplierPersona] = {
    "SUP-0010": SupplierPersona(
        "SUP-0010", "Hwaseong", "[KO]",
        "formal, vague, late",
        "Hwaseong: vague and late",
        {
            "true_capacity": "launch allocation is not reserved",
            "true_eta": "after the requested launch date",
            "documents": ["order confirmation", "late-delivery history"],
            "private_risk": "50% of historical lines were late",
        },
    ),
    "SUP-0011": SupplierPersona(
        "SUP-0011", "Boise", "[EN]",
        "terse, practical",
        "Boise: terse, hides EXW/DDP issue",
        {
            "true_capacity": "dock-held game-card lot can be released",
            "true_eta": "forwarder-dependent",
            "documents": ["forwarder release"],
            "private_risk": "EXW Boise, not DDP Hamburg",
            "lot": "020-48113304",
        },
    ),
    "SUP-0018": SupplierPersona(
        "SUP-0018", "Pune", "[EN]",
        "formal, deflecting",
        "Pune: needs PPAP, deflects",
        {
            "true_capacity": "statue lot is conditional",
            "true_eta": "release-dependent",
            "documents": ["PPAP", "Supplier Quality release", "Category Lead release"],
            "private_risk": "the lot failed AQL and internal release is required",
        },
    ),
    "SUP-0019": SupplierPersona(
        "SUP-0019", "Dongguan", "[ZH]",
        "polite, non-committal",
        "Dongguan: single source, polite but non-committal",
        {
            "true_capacity": "steel-case single source",
            "true_eta": "70-day lead; post-launch risk",
            "documents": ["order confirmation"],
            "private_risk": "lead is 70 days and no alternate source exists",
        },
    ),
    "SUP-0028": SupplierPersona(
        "SUP-0028", "Karton Nowak", "[PL]",
        "helpful, capacity-limited",
        "Karton: helpful but capacity-limited after downtime",
        {
            "true_capacity": "only finished stock is immediately available",
            "true_eta": "express stock requires a pallet and truck slot",
            "documents": ["pallet label", "truck slot"],
            "private_risk": "downtime 21.11 14:00 to 23.11 06:00",
        },
    ),
    "SUP-0029": SupplierPersona(
        "SUP-0029", "PackRight", "[ZH]",
        "precise, slow",
        "PackRight: precise but slow",
        {
            "true_capacity": "lid magnets are fitted at the box supplier",
            "true_eta": "confirmation is slow",
            "documents": ["Annex B", "lot packing list"],
            "private_risk": "CMP-MAG-005 is an included box assembly, not separate stock",
        },
    ),
}


def _specific_ask(email_text: str) -> bool:
    text = email_text.lower()
    markers = (
        "packing list", "booking", "pallet", "lot", "document",
        "forwarder", "truck", "po ", "po-", "quantity", "pcs",
        "ppap", "annex", "release", "dated", "ship date",
        "4500", "020-", "reference",
    )
    return any(marker in text for marker in markers) or bool(
        re.search(r"\b\d{4,}[\s/-]\d*\b", email_text)
    )


def _template_reply(persona: SupplierPersona, email_text: str, turn: int) -> tuple[str, str | None]:
    marker = persona.language_marker
    specific = _specific_ask(email_text)

    if persona.supplier_id == "SUP-0010":
        if turn == 1:
            text = "We received the request. We are checking the current allocation and will come back."
        elif specific:
            text = "We cannot confirm a dated ship date from the existing request. A named allocation and packing-list reference are required."
        else:
            text = "The Korean plant still needs internal confirmation; no firm date is available."
    elif persona.supplier_id == "SUP-0011":
        if turn == 1:
            text = "Received. We are checking the reference and release details."
        elif specific and "020-" in email_text:
            text = "Lot 020-48113304 is the reference under review. Forwarder release must be confirmed before a dock slot is committed."
        else:
            text = "No dated commitment yet. Send the exact lot reference and requested quantity."
    elif persona.supplier_id == "SUP-0018":
        if turn == 1:
            text = "We received your statue request. Our quality and commercial teams must review it."
        elif specific:
            text = "A quantity and ship date remain conditional until the required quality release is complete."
        else:
            text = "We are coordinating the review, but cannot treat the lot as released."
    elif persona.supplier_id == "SUP-0019":
        if turn == 1:
            text = "Thank you for your message. We will review the order and current plant schedule."
        elif specific:
            text = "We can confirm the 70-day lead for a specified lot, but a launch-date commitment requires a dated release."
        else:
            text = "Our plant is checking the request. We do not have a firm launch-week commitment."
    elif persona.supplier_id == "SUP-0028":
        if turn == 1:
            text = "Dziękujemy za wiadomość. Sprawdzamy gotową produkcję i możliwość transportu."
        elif specific and any(word in email_text.lower() for word in ("pallet", "lot", "8000", "8,000")):
            text = "Możemy zweryfikować 8 000 szt. z zapasu gotowego; potwierdzenie etykiety palety i slotu ciężarówki będzie wymagane."
        else:
            text = "Sprawdzamy limit gotowego zapasu. Nie potwierdzamy terminu bez numeru lotu i ilości."
    else:
        if turn == 1:
            text = "我们已收到请求，正在核对生产和包装记录。"
        elif specific and any(word in email_text.lower() for word in ("annex", "magnet", "packing", "lot", "quantity")):
            text = "指定批次和数量需要与包装清单核对。我们会先确认已装配的部件及批次文件，不在此确认发货日期。"
        else:
            text = "此事需要进一步核实。请提供批次和具体数量。"

    attachment = None
    if turn > 1:
        if persona.supplier_id == "SUP-0011" and "forwarder" in email_text.lower():
            attachment = "forwarder-release.txt"
        elif persona.supplier_id == "SUP-0028" and "pallet" in email_text.lower():
            attachment = "pallet-label.txt"
        elif persona.supplier_id == "SUP-0029" and ("annex" in email_text.lower() or "packing" in email_text.lower()):
            attachment = "Annex-B.txt"

    return f"{marker} {text}", attachment


class SupplierSim:
    """Tool-less external-world supplier with private state and an optional LLM adapter."""

    def __init__(self, llm: Adapter | None = None):
        self.llm = llm
        self.turns: dict[str, int] = {}

    def persona(self, supplier_id: str) -> SupplierPersona:
        try:
            return PERSONAS[supplier_id]
        except KeyError as exc:
            raise ValueError(f"unknown supplier: {supplier_id}") from exc

    def reply(self, supplier_id: str, email_text: str, now: datetime | str | None = None) -> dict[str, Any]:
        persona = self.persona(supplier_id)
        turn = self.turns.get(supplier_id, 0) + 1
        self.turns[supplier_id] = turn

        adapter = self.llm
        text, attachment = _template_reply(persona, email_text, turn)

        if adapter is not None and not isinstance(adapter, FakeLLM):
            prompt = (
                f"You are {persona.name}, supplier {supplier_id}. "
                f"Behaviour: {persona.behaviour}. Register: {persona.register}. "
                "Keep the reply short. Never reveal more than asked. "
                "Commit to a date only if the buyer asks for a named document or a per-lot quantity. "
                "Never reveal the private ground truth on the first reply."
            )
            try:
                response = adapter.chat(
                    [{"role": "user", "content": email_text}],
                    tools=(),
                    system=prompt,
                    model=None,
                )
                llm_text = str(response.get("text", "")).strip()
                if llm_text:
                    text = llm_text
            except Exception:
                pass

        if not text.startswith(persona.language_marker):
            text = f"{persona.language_marker} {text}"

        if turn == 1:
            hidden_values = [
                str(value)
                for value in persona.hidden_ground_truth.values()
                if isinstance(value, str)
            ]
            if any(value.lower() in text.lower() for value in hidden_values):
                text, attachment = _template_reply(persona, email_text, turn)
                if not text.startswith(persona.language_marker):
                    text = f"{persona.language_marker} {text}"

        return {
            "supplier_id": supplier_id,
            "text": text,
            "attachment": attachment,
            "attachment_name": attachment,
            "turn": turn,
        }


def reply(supplier_id: str, email_text: str, now: datetime | str | None = None,
          llm: Adapter | None = None) -> dict[str, Any]:
    return SupplierSim(llm=llm).reply(supplier_id, email_text, now)


def _demo() -> int:
    sim = SupplierSim(llm=FakeLLM([]))
    for supplier_id in PERSONAS:
        persona = sim.persona(supplier_id)
        first = "Please confirm whether you can support the launch and share the earliest status."
        second = "Please provide the named lot, packing list or booking reference and exact quantity."
        print(f"{supplier_id} {persona.name}")
        print(sim.reply(supplier_id, first, datetime.now())["text"])
        print(sim.reply(supplier_id, second, datetime.now())["text"])
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    raise SystemExit(_demo() if args.demo else parser.print_help())
