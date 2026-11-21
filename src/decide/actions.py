"""Operational recovery approvals projected from the live evidence and review records."""

from datetime import datetime, timedelta
import json
import re

from .inbound import POLICY


DAP_TOTAL = re.compile(r"\b(?:łącznie|total(?: of)?)\s+([\d \u00a0]+),(\d{2})\s+EUR\s+DAP\s+Hamburg\b", re.I)


def inbound_receiving_reviews(con, truth):
    """Keep the receiving dependencies visible while usable stock is short."""
    cutoff = datetime.fromisoformat(truth["deadline"])
    shifts = truth.get("shifts")
    final_shift = shifts[-1][0] if shifts else truth["deadline"]
    for lot in truth.get("inbound", []):
        part = truth.get("parts", {}).get(lot["material"], {})
        gap = round(part.get("required", 0) - part.get("on_hand", 0))
        if (gap <= 0 or lot["held"] or lot.get("missesPackout") or lot["quantity"] <= 0
                or not lot.get("earliest") or datetime.fromisoformat(lot["earliest"]) >= cutoff):
            continue
        if lot["id"] == "SHP-2026-04313" and (hold := part.get("revision_hold")):
            # Require a reply to an actual send on this supplier and component.
            # Another message from the same supplier (e.g. for art books) is not receipt evidence.
            reply = con.execute("""
                SELECT m.id,m.chase_id FROM messages m
                JOIN chases c ON c.id=m.chase_id
                JOIN messages sent ON sent.chase_id=c.id AND sent.side='out'
                  AND sent.external_id=json_extract(m.transport,'$.inReplyTo')
                WHERE m.side='in' AND json_extract(m.transport,'$.mode')='inbox'
                  AND json_extract(sent.transport,'$.status') IN ('smtp_accepted','gmail_sent')
                  AND c.supplier_id=? AND c.material=?
                  AND (instr(lower(sent.body),lower(?))>0 OR instr(lower(m.body),lower(?))>0)
                ORDER BY julianday(coalesce(json_extract(m.transport,'$.authoredAt'),m.time)) DESC,
                         m.id DESC LIMIT 1
            """, (lot["supplier"], lot["material"], lot["reference"], lot["reference"])).fetchone()
            yield dict(
                id=f"receive-{lot['id']}", priority=2, title="Verify receipt and release of rev-C sleeves",
                owner="Katrin Jansen",
                approver="Katrin Jansen for DC-HAM receiving. Quality & Compliance for release.",
                detail=f"Standard is {gap:,} sleeves short before this receipt. Check the signed delivery "
                       f"proof and Hamburg goods receipt for {lot['reference']} ({lot['quantity']:,.0f} sleeves), "
                       f"then verify lot, revision {hold['new_revision']} and Quality release. "
                       f"Keep the {hold['quantity']:,} rev-{hold['old_revision']} sleeves on hold under {hold['ecn']}.",
                dueAt=final_shift, evidence=next(iter(hold.get("evidence", [])), None),
                threadId=reply["chase_id"] if reply else None, replyId=reply["id"] if reply else None,
            )
        elif lot["id"] == "SHP-2026-04276":
            yield dict(
                id=f"receive-{lot['id']}", priority=3, title="Confirm pickup of Standard cases from CTA Hamburg",
                owner="Raj Patel", approver="Katrin Jansen, DC-HAM site lead (deputy Raj Patel)",
                detail=f"Standard needs {gap:,} cases beyond usable on-hand stock. The ERP reports "
                       f"{lot['quantity']:,.0f} cases available for pickup at CTA Hamburg ({lot['reference']}). "
                       "Check pickup, gate-out and the Hamburg goods receipt. If they are still at the terminal, "
                       "arrange release and an approved dock window.",
                dueAt=final_shift, evidence=next(iter(lot.get("evidence", [])), None),
            )


def recovery_reviews(con, truth, options, supplier_actions):
    """Expose the live launch reviews with their operating conditions."""
    cutoff = datetime.fromisoformat(truth["deadline"])
    approvals = [dict(review, status="awaiting_approval", policy=POLICY)
                 for review in inbound_receiving_reviews(con, truth)]
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
            if any(change["shipmentId"] == option["shipment_id"] for change in truth.get("shipmentChanges", [])):
                continue  # The live recovery action carries the revised plan.
            tracking = next((action for action in supplier_actions if action["case"] == "game_card"
                             and action.get("optionId") == option["id"] and action.get("replyId")), {})
            review.update(
                priority=0, title="Arrange a provisional Hamburg dock slot", owner="Katrin Jansen",
                approver="Katrin Jansen, DC-HAM site lead (deputy Raj Patel)",
                detail="Ask DC-HAM for a provisional unloading window for AWB 020-48113256 (28,000 game cards). "
                       "Obtain a verified forwarder contact, carrier ETA, customs documents and FRA-to-Hamburg transfer. "
                       "Confirm slot expiry and fees before booking. Allocate released cards to Collector’s Edition first.",
                dueAt=option.get("latest_action"),
                threadId=tracking.get("threadId"), replyId=tracking.get("replyId"),
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
            gap = truth.get("parts", {}).get(material, {}).get("shortfall")
            review.update(
                priority=1, title="Review the Karton art-book PO", owner="Paul Winter",
                approver="Paul Winter, Print & Packaging buyer. DC-HAM site lead confirms receiving.",
                detail=(f"Collector’s Edition needs {gap:,} more art books. " if gap is not None else "") +
                       (f"The last priced quote covered {quantity:,} art books. " if quantity else "") +
                       "Reconfirm the supplier hold and a usable Hamburg delivery window before placing the PO. "
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
            gap = truth.get("parts", {}).get(material, {}).get("shortfall")
            review.update(
                priority=4, title=f"Authorize a 100% sort of {hold['quantity']:,} quarantined statues",
                owner="Daniel Okafor",
                approver="Daniel Okafor, Supplier Quality Lead, and Category Lead or a documented PP-07 §6 exception.",
                detail="Approve the inspection plan and staffing to sort every quarantined unit. "
                       + (f"Collector’s Edition needs {gap:,} more released statues. " if gap is not None else "")
                       + "Quality & Compliance has the final release decision.",
                dueAt=cutoff.replace(hour=12, minute=0).isoformat(),
                evidence=next((source for source in hold.get("evidence", []) if source.get("page")), None),
            )
        else:
            continue
        if option["id"] not in present:
            review["detail"] = "The underlying option changed after this review was requested. Revalidate it before approving. " + review["detail"]
        approvals.append(review)
    return sorted(approvals, key=lambda review: review["priority"])
