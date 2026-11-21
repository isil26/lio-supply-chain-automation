"""Inbound expedite options: get freight that lands before the cut-off onto the lines.

The readiness forecast adds a random post-arrival handling delay to every
inbound shipment (unloading, customs, put-away; see ``LAG_HOURS``). When a
shipment lands only hours before the last shift ends, that delay alone decides
whether its parts reach pack-out. This module finds those shipments and models
what a pre-booked dock slot with pre-cleared customs would change.

Every number comes from paired counterfactual runs of the readiness model:
the same seed and trials, with only the handling delay of one shipment capped.
The cap is an assumption to confirm with the site lead and forwarder, not a
quote. Nothing is sent; the draft goes to a human for review.
"""
import re
from datetime import datetime

from src.ingest.store import rows
from src.truth import MODEL_RUNS
from src.truth.sensitivity import counterfactual

POLICY = "soony/context/approval_policy_PP-07.pdf"
# Assumed handling time with a booked dock slot and customs cleared in advance.
EXPEDITED_HANDLING_HOURS = 4
# Report expected changes of at least one copy. An option needs a median gain,
# the statistic the dashboard reports, so tail-only gains stay off the menu.
MIN_GAIN = 1.0
ARRIVED = {"arrived_port", "arrived", "at_port", "discharged"}


def site_lead(docs, site):
    """Return (lead, deputy, citation) for a site from the PP-07 receiving-site clause."""
    policy = next((doc for doc in docs if doc["source"] == POLICY), None)
    for clause in (policy or {}).get("fields", {}).get("policy_clause", []):
        if "Receiving site" not in clause["value"]:
            continue
        for line in clause["citation"].get("quote", clause["value"]).splitlines():
            if site and line.strip().startswith(site):
                cells = [cell.strip() for cell in re.split(r"\s{2,}", line.strip()) if cell.strip()]
                if len(cells) >= 2:
                    return cells[1], cells[2] if len(cells) > 2 else None, clause["citation"]
        return None, None, clause["citation"]
    return None, None, None


def _shipment_rows(con):
    """ERP shipment rows win over tracker rows for status and carrier."""
    best = {}
    for row in rows(con, "shipment"):
        erp = "erp/" in row["source"]["file"]
        current = best.get(row["shipment_id"])
        if current is None or (erp and "erp/" not in current["source"]["file"]):
            best[row["shipment_id"]] = row
    return best


def _metrics(result):
    return {pid: (row["p50"], row["expected_packed"], row["probability"]) for pid, row in result["editions"].items()}


def inbound_options(con, truth, docs, *, trials=None, hours=EXPEDITED_HANDLING_HOURS):
    """Return option kwargs for shipments whose dock handling decides pack-out.

    Each item matches the ``option(...)`` signature in ``src.decide.choose``.
    """
    if not truth.get("shifts"):
        return []
    trials = trials or truth.get("model", {}).get("runs", MODEL_RUNS)
    last_slot = min(datetime.fromisoformat(truth["shifts"][-1][1]), datetime.fromisoformat(truth["deadline"]))
    lead, deputy, policy_citation = site_lead(docs, truth.get("site"))
    shipments = _shipment_rows(con)
    carriers = {row["carrier_id"]: row for row in rows(con, "carrier")}
    labels = {pid: row.get("edition", pid) for pid, row in truth["editions"].items()}

    baseline = _metrics(counterfactual(truth, {}, trials=trials))
    found = []
    for item in truth["inbound"]:
        part = truth["parts"].get(item["material"])
        if (not part or part.get("embedded_in") or item["held"] or item["quantity"] <= 0
                or not item["earliest"] or datetime.fromisoformat(item["earliest"]) >= last_slot):
            continue
        scenario = _metrics(counterfactual(truth, {"handling_hours": {item["id"]: hours}}, trials=trials))
        gains = {pid: (scenario[pid][0] - baseline[pid][0], scenario[pid][1] - baseline[pid][1]) for pid in baseline}
        if max(median for median, _ in gains.values()) <= 0:
            continue
        found.append((item, part, scenario, gains))

    options = []
    for item, part, scenario, gains in sorted(found, key=lambda f: -sum(g for _, g in f[3].values())):
        row = shipments.get(item["id"], {})
        carrier = carriers.get(row.get("carrier_id"), {})
        forwarder = carrier.get("name") or "the forwarder"
        landed = row.get("status") in ARRIVED
        component = part["label"].split(" – ")[0]
        ref = item.get("reference") or item["id"]
        lands = datetime.fromisoformat(item["earliest"])
        when = lands.strftime("%a %d %b %H:%M")
        owner = lead or "Site lead (confirm under PP-07 §3)"

        if landed:
            title = f"Book pickup of {component} at the terminal"
            action = (f"Book a truck with {forwarder} to collect {item['quantity']:,.0f} units ({ref}) now"
                      f"{' (' + row['note'] + ')' if row.get('note') else ''}, and reserve a {truth.get('site', 'DC')} "
                      f"dock slot so unloading takes under {hours} h.")
        else:
            title = f"Pre-book dock slot for the {component} {item['mode']} lot"
            action = (f"Ask {forwarder} to pre-clear customs for {ref} ({item['quantity']:,.0f} units, "
                      f"earliest {when}) and reserve a {truth.get('site', 'DC')} dock slot so the lot is "
                      f"unloaded within {hours} h of arrival.")
        median = ", ".join(f"{labels[pid]} {baseline[pid][0]:,} → {scenario[pid][0]:,}" for pid in sorted(gains))
        expected = ", ".join(f"{labels[pid]} {gains[pid][1]:+,.0f}" for pid in sorted(gains) if abs(gains[pid][1]) >= MIN_GAIN)
        draft_to = [name for name in (forwarder if carrier else None, lead) if name]
        options.append(dict(
            kind="inbound", title=title, recommendation=action, price=None,
            threshold=(f"PP-07 §3: dock slot released by the site lead ({owner}"
                       f"{', deputy ' + deputy if deputy else ''}). Forwarder expedite fees are unquoted."),
            impact=(f"Median packed copies if handling stays within {hours} h: {median}. "
                    f"Expected change: {expected}. Same seed and {trials} trials."),
            risk=(f"Handling within {hours} h is an assumption to confirm with {owner} and {forwarder}. "
                  "The forecast already assumes the lot lands on time; a late landing removes this gain."),
            evidence=[*item.get("evidence", ()),*([carrier["source"]] if carrier else []),
                      *([policy_citation] if policy_citation else [])],
            owner=owner, request_only=True, price_label="Fee unquoted",
            material=item["material"], supplier_id=item.get("supplier"), shipment_id=item["id"],
            latest_action=lands.isoformat(),
            modeled_impact={pid: {"medianDelta": gains[pid][0], "expectedDelta": round(gains[pid][1], 1),
                                  "baselineProbability": baseline[pid][2], "scenarioProbability": scenario[pid][2]}
                            for pid in gains},
            draft={
                "to": draft_to,
                "subject": f"{ref}: dock slot and customs for launch-critical {component}",
                "body": (f"Hello,\n\n{ref} carries {item['quantity']:,.0f} {component} units for the launch "
                         f"pack-out at {truth.get('site', 'our DC')}, which closes {last_slot.strftime('%a %d %b %H:%M')}. "
                         + (f"The shipment is available for pick-up. Please book collection today. "
                            if landed else f"Its earliest arrival is {when}. Please pre-clear customs before arrival. ")
                         + f"We need the goods unloaded within {hours} h of arrival. Please confirm the slot "
                         "and any expedite fee before booking.\n\nThank you"),
                "status": "draft — human review before sending",
            },
        ))
    return options
