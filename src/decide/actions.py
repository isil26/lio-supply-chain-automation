"""Operational recovery approvals projected from the live evidence and review records."""

from datetime import datetime, timedelta
import json
import re

from .inbound import POLICY


DAP_TOTAL = re.compile(r"\b(?:łącznie|total(?: of)?)\s+([\d \u00a0]+),(\d{2})\s+EUR\s+DAP\s+Hamburg\b", re.I)


def recovery_reviews(con, truth, options, supplier_actions):
    """Expose the three launch reviews with their operating conditions."""
    cutoff = datetime.fromisoformat(truth["deadline"])
    approvals = []
    pending = {option["id"]: option for option in options if option["status"] == "review"}
    present = {option["id"] for option in options}
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='decisions'").fetchone():
        for row in con.execute("SELECT id,payload FROM decisions WHERE status='review'"):
            if row["id"] not in present:
                pending[row["id"]] = json.loads(row["payload"])
    for option in pending.values():
        kind, material = option["kind"], option.get("material")
        review = {"id": option["id"], "status": "awaiting_approval", "policy": POLICY}
        if kind == "inbound" and option.get("shipment_id") == "SHP-2026-04311":
            review.update(
                priority=0, title="Arrange a provisional Hamburg dock slot", owner="Katrin Jansen",
                approver="Katrin Jansen, DC-HAM site lead (deputy Raj Patel)",
                detail="Ask DC-HAM for a provisional unloading window for AWB 020-48113256 (28,000 game cards). "
                       "Obtain a verified forwarder contact, carrier ETA, customs documents and FRA-to-Hamburg transfer. "
                       "Confirm slot expiry and fees before booking.",
                dueAt=option.get("latest_action"),
            )
        elif kind == "partial" and material == "CMP-GAM-008" and option.get("supplier_id") == "SUP-0028":
            offer = next((action for action in supplier_actions if action["case"] == "karton"
                          and action["kind"] in {"review_cover", "review_art_book_gap"}), None)
            quantity = offer.get("reportedUnits") if offer else None
            row = con.execute(
                "SELECT body FROM messages WHERE id=? AND chase_id=? AND side='in'",
                (offer["replyId"], offer["threadId"]),
            ).fetchone() if offer else None
            terms = DAP_TOTAL.search(row["body"]) if row else None
            total = int(re.sub(r"\D", "", terms[1])) + int(terms[2]) / 100 if terms else None
            review.update(
                priority=1, title="Review the Karton art-book PO", owner="Paul Winter",
                approver="Paul Winter, Print & Packaging buyer. DC-HAM site lead confirms receiving.",
                detail=(f"Supplier quote covers {quantity:,} art books. " if quantity else "") +
                       "Confirm net need from the latest pack-out and usable stock, the supplier hold, and a usable Hamburg delivery window. "
                       "The planning target allows four hours to load and nine hours on the road.",
                dueAt=(cutoff.replace(hour=9, minute=0) - timedelta(hours=13)).isoformat(),
                price=total,
                priceLabel="EUR DAP Hamburg" if total is not None else "Confirm delivered total",
                threadId=offer.get("threadId") if offer else None,
                replyId=offer.get("replyId") if offer else None,
            )
        elif kind == "quality" and material == "CMP-GAM-010":
            hold = next((issue for issue in truth["issues"] if issue.get("material") == material
                         and issue["kind"] == "quality_hold"), {})
            if not hold.get("quantity"):
                continue
            review.update(
                priority=2, title=f"Authorize a 100% sort of {hold['quantity']:,} quarantined statues",
                owner="Daniel Okafor",
                approver="Daniel Okafor, Supplier Quality Lead, and Category Lead or a documented PP-07 §6 exception.",
                detail="Approve the inspection plan and staffing to sort every quarantined unit. Verify the passing quantity "
                       "against the latest pack-out. Quality & Compliance has the final release decision.",
                dueAt=cutoff.replace(hour=12, minute=0).isoformat(),
                evidence=next((source for source in hold.get("evidence", []) if source.get("page")), None),
            )
        else:
            continue
        if option["id"] not in present:
            review["detail"] = "The underlying option changed after this review was requested. Revalidate it before approving. " + review["detail"]
        approvals.append(review)
    return sorted(approvals, key=lambda review: review["priority"])
