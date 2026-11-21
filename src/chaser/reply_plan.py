"""Turn a matched supplier message into a reviewable shipment scenario."""

from datetime import datetime, timedelta
import re

from src.truth import MODEL_RUNS
from src.truth.sensitivity import counterfactual


ETA = re.compile(
    r"^\s*(?:revised\s+)?ETA\s*[:=]\s*(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2}))\s*$",
    re.I | re.M,
)
PRICE_PENDING = re.compile(r"\b(?:freight|delivered|delivery)\s+(?:price|cost|quote)\s+(?:to\s+follow|pending)\b", re.I)
HOLD = re.compile(r"\b(?:can|will)\s+hold\s+(\d{1,3}(?:,\d{3})+|\d+)\b", re.I)


def matching_offers(options, thread):
    return [option for option in options if option.get("kind") == "partial"
            and option.get("supplier_id") == thread["supplier_id"] and option.get("material") == thread["material"]]


def matching_shipments(truth, thread):
    return [
        shipment for shipment in truth.get("inbound", [])
        if shipment.get("material") == thread["material"]
        and shipment.get("supplier") == thread["supplier_id"]
        and shipment.get("earliest") and shipment["quantity"] > 0 and not shipment["held"]
    ]


def cited_reference(body, shipment):
    for reference in (shipment["id"], shipment.get("reference")):
        if reference and (match := re.search(rf"(?<![\w-]){re.escape(reference)}(?![\w-])", body, re.I)):
            return match[0]
    return None


def plan_reply(truth, thread, body, *, options=(), simulated=False):
    shipments = matching_shipments(truth, thread)
    matches = [(shipment, quote) for shipment in shipments if (quote := cited_reference(body, shipment))]
    dates = list(ETA.finditer(body))
    offers = matching_offers(options, thread)
    holds = list(HOLD.finditer(body))
    context = {"simulated": simulated}
    next_action = "Ask the supplier to clarify what they can commit to. The reply did not establish a usable update."
    if len(offers) == 1:
        next_action = "Ask the supplier to confirm the quantity, hold expiry and written delivered price."
        if len(holds) == 1 and (quantity := int(holds[0][1].replace(",", ""))) > 0:
            active = offers[0]
            requested = thread["qty"]
            action = "Confirm the hold expiry and request the written delivered price, pickup and dock slot. A separate PO decision remains outstanding."
            if quantity < requested:
                action = f"Request the delivered quote and review alternate stock for the remaining {requested - quantity:,} units. A separate PO decision remains outstanding."
            evidence = [holds[0][0]]
            if pending := PRICE_PENDING.search(body):
                evidence.append(pending[0])
            return dict(context, offerId=active["id"], holdUnits=quantity, holdRequested=requested,
                        beforeState="Awaiting stock hold and delivered quote",
                        afterState=f"Supplier reports a hold for {quantity:,} units. Delivered price pending.",
                        materialEstimate=active.get("price"), evidence=evidence, nextAction=action)
    elif shipments:
        next_action = "Ask the supplier to confirm the shipment reference and revised arrival time with a time zone."
    if len(matches) != 1 or len(dates) != 1 or not truth.get("shifts"):
        return dict(context, nextAction=next_action)
    try:
        when = datetime.fromisoformat(dates[0][1])
    except ValueError:
        return dict(context, nextAction=next_action)

    shipment, reference_quote = matches[0]
    trials = truth.get("model", {}).get("runs", MODEL_RUNS)
    baseline = counterfactual(truth, {}, trials=trials)["editions"]
    revised = counterfactual(truth, {"shipment_earliest": {shipment["id"]: when.isoformat()}},
                             trials=trials)["editions"]
    last_shift = datetime.fromisoformat(truth["shifts"][-1][1])
    if when >= last_shift:
        next_action = "Escalate to Procurement and review alternate stock or freight. This lot misses the final packing shift in the supplier's scenario."
    elif any(after[key] < baseline[pid][key] for pid, after in revised.items()
             for key in ("p50", "p90", "probability")):
        next_action = "Ask the forwarder for a confirmed dock slot and review recovery options for the lower pack-out."
    else:
        next_action = "Verify the revised arrival with the forwarder and confirm the receiving slot."
    return dict(context, shipmentId=shipment["id"], previousEta=shipment["earliest"], reportedEta=when.isoformat(),
                evidence=[reference_quote, dates[0][0].strip()], nextAction=next_action,
                editions=[{
                    "title": truth["editions"][pid].get("edition", pid),
                    "before": baseline[pid]["p50"], "after": after["p50"],
                    "upperBefore": baseline[pid]["p90"], "upperAfter": after["p90"],
                    "pBefore": baseline[pid]["probability"], "pAfter": after["probability"],
                } for pid, after in revised.items()])


def demo_reply(truth, thread, options=()):
    offers = matching_offers(options, thread)
    if len(offers) == 1:
        quantity = min(thread["qty"], offers[0]["full_lot_units"])
        if quantity > 0:
            return f"We can hold {quantity:,}, freight price to follow."
    if truth.get("shifts"):
        final_shift = datetime.fromisoformat(truth["shifts"][-1][1])
        for shipment in matching_shipments(truth, thread):
            if datetime.fromisoformat(shipment["earliest"]) < final_shift:
                late = (final_shift + timedelta(hours=3)).isoformat(timespec="minutes")
                return f"Shipment {shipment['id']} was delayed.\nRevised ETA: {late}\nPlease update your plans."
    return "Stock may be available. Our forwarder has yet to confirm the shipment and arrival time."
