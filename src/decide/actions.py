"""Operational recovery approvals projected from the live evidence and review records."""

from datetime import datetime, timedelta
import re

from .inbound import POLICY


DAP_TOTAL = re.compile(r"\b(?:łącznie|total(?: of)?)\s+([\d \u00a0]+),(\d{2})\s+EUR\s+DAP\s+Hamburg\b", re.I)


def recovery_reviews(con, truth, options, supplier_actions):
    """Expose the three launch reviews with their operating conditions."""
    cutoff = datetime.fromisoformat(truth["deadline"])
    approvals = []
    for option in options:
        if option["status"] != "review":
            continue
        kind, material = option["kind"], option.get("material")
        review = {"id": option["id"], "status": "awaiting_approval", "policy": POLICY}
        if kind == "inbound" and option.get("shipment_id") == "SHP-2026-04311":
            review.update(
                priority=0, title="Arrange a provisional Hamburg dock slot", owner="Katrin Jansen",
                approver="Katrin Jansen, DC-HAM site lead (deputy Raj Patel)",
                detail="Ask DC-HAM for a provisional unloading window for AWB 020-48113256 (28,000 game cards). "
                       "Confirm the carrier ETA, customs documents, FRA-to-Hamburg transfer, slot expiry and fees before booking.",
                dueAt=option.get("latest_action"),
            )
        elif kind == "partial" and material == "CMP-GAM-008" and option.get("supplier_id") == "SUP-0028":
            offer = next((action for action in supplier_actions if action["kind"] == "review_cover"
                          and action.get("optionId") == option["id"]), None)
            quantity = truth["parts"][material]["shortfall"]
            row = con.execute(
                "SELECT body FROM messages WHERE id=? AND chase_id=? AND side='in'",
                (offer["replyId"], offer["threadId"]),
            ).fetchone() if offer else None
            terms = DAP_TOTAL.search(row["body"]) if row else None
            total = int(re.sub(r"\D", "", terms[1])) + int(terms[2]) / 100 if terms else None
            review.update(
                priority=1, title=f"Approve Karton PO for {quantity:,} art books", owner="Paul Winter",
                approver="Paul Winter, Print & Packaging buyer. DC-HAM site lead confirms receiving.",
                detail=("Confirm the supplier hold and a usable Hamburg delivery window, then authorize the buyer to issue the PO. "
                        "The planning target allows four hours to load and nine hours on the road."),
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
            needed = truth["parts"][material]["shortfall"]
            review.update(
                priority=2, title=f"Authorize a 100% sort of {hold['quantity']:,} quarantined statues",
                owner="Daniel Okafor",
                approver="Daniel Okafor, Supplier Quality Lead, and Category Lead or a documented PP-07 §6 exception.",
                detail=(f"Approve the inspection plan and staffing to recover at least {needed:,} passing units. "
                        "Keep the lot quarantined until Quality verifies the sort results and the required signers record a release."),
                dueAt=cutoff.replace(hour=12, minute=0).isoformat(),
                evidence=next((source for source in hold.get("evidence", []) if source.get("page")), None),
            )
        else:
            continue
        approvals.append(review)
    return sorted(approvals, key=lambda review: review["priority"])
