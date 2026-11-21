from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Issue:
    supplier_id: str
    component: str
    po: str
    what_we_need: str
    deadline: datetime
    max_price_premium_pct: float = 0.0
    proposed_price_premium_pct: float = 0.0

    @classmethod
    def from_dict(cls, payload: dict) -> "Issue":
        deadline = payload["deadline"]
        if isinstance(deadline, datetime):
            parsed = deadline
        else:
            parsed = datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
        supplier_id = str(payload["supplier_id"]).strip()
        component = str(payload["component"]).strip()
        po = str(payload["PO"] if "PO" in payload else payload["po"]).strip()
        what_we_need = str(payload["what_we_need"]).strip()
        if not supplier_id or not component or not po or not what_we_need:
            raise ValueError("supplier_id, component, PO, and what_we_need are required")
        return cls(
            supplier_id=supplier_id,
            component=component,
            po=po,
            what_we_need=what_we_need,
            deadline=parsed,
            max_price_premium_pct=float(payload.get("max_price_premium_pct", 0.0)),
            proposed_price_premium_pct=float(payload.get("proposed_price_premium_pct", 0.0)),
        )


@dataclass(frozen=True)
class Supplier:
    supplier_id: str
    name: str
    contact_name: str
    contact_email: str
    preferred_language: str
    phone: str = ""


@dataclass(frozen=True)
class ReplyParse:
    status: str
    new_eta: str | None
    quantity: int | None
    confidence: float
    needs_human: bool
    commitment_strength: str = "none"
    commitment_score: int = 0
    what_to_ask_next: str = "Ask for a confirmed quantity and ETA."
