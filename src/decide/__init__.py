"""Generate sourced mitigation options and route approvals without booking spend."""
import hashlib
import json
import math
import re
from datetime import datetime, timedelta

from src.docs import documents
from src.ingest.store import now, rows
from src.truth import field_sources, simulate, value

POLICY = "soony/context/approval_policy_PP-07.pdf"
ORG = "soony/context/org_chart_procurement.pdf"


def policy_details(docs):
    policy = next((doc for doc in docs if doc["source"] == POLICY), None)
    clauses = policy["fields"].get("policy_clause", []) if policy else []
    owners = [item["value"] for item in clauses if "Approval limits" in item["value"]]
    limits = []
    if owners:
        for name, amount in re.findall(r"^([^\n<]+?)(?:[ \t]{2,}|[ \t]*\n)<[ \t]*([\d,]+)", owners[0], re.M):
            if not re.match(r"\d\.", name):
                limits.append((name.strip(), int(amount.replace(",", ""))))
    air = next((item for item in clauses if "air freight up to" in item["value"]), None)
    air_limit = re.search(r"air freight up to EUR ([\d,]+)", air["value"]) if air else None
    return limits, int(air_limit[1].replace(",", "")) if air_limit else None, [item["citation"] for item in clauses]


def choose(con, truth):
    docs = list(documents(con))
    po_limits, air_limit, clauses = policy_details(docs)
    org_source = {"file": ORG, "page": 1}
    launch_end = datetime.fromisoformat(truth["deadline"])
    shifts = [(datetime.fromisoformat(start), datetime.fromisoformat(end)) for start, end in truth["shifts"]]
    start = shifts[0][0] if shifts else launch_end
    buyer_lead = "Dr. Maren Vogt"
    decision_menu = []

    def option(kind, title, recommendation, price, threshold, impact, risk, evidence, **extra):
        item = {"kind": kind, "title": title, "recommendation": recommendation, "price": price, "currency": "EUR",
                "owner": buyer_lead, "threshold": threshold, "impact": impact, "risk": risk,
                "deadline": launch_end.isoformat(), "evidence": [*evidence, org_source], **extra}
        version = json.dumps(item, ensure_ascii=False, sort_keys=True)
        item["id"] = hashlib.sha256(version.encode()).hexdigest()[:16]
        decision_menu.append(item)
        return item

    ce = next((pid for pid in truth["editions"] if pid.endswith("-CE")), None)
    std = next((pid for pid in truth["editions"] if pid.endswith("-STD")), None)

    def estimate(part, quantity, arrive, freight_mode):
        if not shifts:
            return None
        independent = {pid: {k: row["unit_usage"][pid] for k, row in truth["parts"].items()
                       if pid in row["unit_usage"] and not row["embedded_in"]} for pid in truth["editions"]}
        stock = {k: row["on_hand"] for k, row in truth["parts"].items() if not row["embedded_in"]}
        inbound = [dict(row, earliest=datetime.fromisoformat(row["earliest"]) if row["earliest"] else None)
                   for row in truth["inbound"]]
        inbound.append({"earliest": arrive, "material": part, "quantity": quantity, "held": False, "mode": freight_mode})
        forecast = simulate(truth["editions"], independent, stock, inbound, shifts, trials=180)
        return {pid: {"medianDelta": forecast[pid]["p50"] - truth["editions"][pid]["p50"],
                      "baselineProbability": truth["editions"][pid]["probability"],
                      "scenarioProbability": forecast[pid]["probability"]} for pid in forecast}

    for doc in docs:
        for offer in doc["fields"].get("available_offer", []):
            detail = offer["value"]
            part = truth["parts"].get(detail.get("material"))
            if not part or not part["shortfall"]:
                continue
            supplier_rates = [r for r in part["suppliers"] if r["supplier_id"] in doc["source"] and r["currency"] == "EUR" and r["unit_price"] is not None]
            if not supplier_rates:
                continue
            rate = supplier_rates[0]
            qty = min(int(detail["quantity"]), part["shortfall"])
            handling = detail["load_hours"] + (value(doc, "road_hours") or 0)
            known_cost = round(qty * rate["unit_price"], 2)
            full_lot_units = int(detail["quantity"])
            full_lot_cost = round(full_lot_units * rate["unit_price"], 2)
            latest = launch_end - timedelta(hours=handling + 8)
            price_owner = next((name for name, limit in po_limits if known_cost < limit), "CPO and CFO jointly")
            if not po_limits:
                price_owner = "Confirm PO approver under PP-07"
            gain = estimate(part["material"], qty, start + timedelta(hours=handling), "road")
            option("partial", f'Secure {part["label"].split(" Grand Heist")[0].lower()} stock',
                   f'Request a hold and a written delivered quote for {qty:,} finished units from {rate["supplier"].get("name", "the supplier")}. Prepare a separate PO decision after the dock slot and total cost are confirmed.',
                   known_cost, f"{price_owner} by total PO value + DC-HAM site lead dock release",
                   f'{qty:,} units. {handling} h loading + driving, before receiving. ' +
                   (f'Median packed-unit change: {sum(row["medianDelta"] for row in gain.values()):+,} if authorized at the first shift start.'
                    if gain is not None else "Shift impact pending."),
                   f'If the supplier requires all {full_lot_units:,} units, materials total €{full_lot_cost:,.2f}. Confirm freight, pickup time and dock slot.',
                   [offer["citation"], *field_sources(doc, "road_hours"), rate["source"], *clauses],
                   latest_action=latest.isoformat(), request_only=True, price_label="Materials estimate",
                   full_lot_price=full_lot_cost, full_lot_units=full_lot_units, modeled_impact=gain, material=part["material"],
                   supplier_id=rate["supplier_id"])

    for issue in truth["issues"]:
        if issue["kind"] == "quality_hold" and truth["parts"].get(issue["material"], {}).get("shortfall"):
            part = truth["parts"][issue["material"]]
            option("quality", "Request a statue quality decision",
                   "Ask Supplier Quality to assess rework or a signed concession. Keep the lot quarantined until both approval roles sign.",
                   None, "Supplier Quality Lead + Category Lead under inspection report. Route vacant CE lead to Head of Procurement for a documented exception.",
                   f'{issue["quantity"]:,} units on hold, {part["shortfall"]:,} needed to close the material gap.',
                   "Defect rate requires inspection. Rework timing and price are unquoted.",
                   [*issue["evidence"], *clauses], request_only=True, material=part["material"], supplier_id=issue.get("supplier"))

    for part in sorted(truth["parts"].values(), key=lambda p: p["shortfall"], reverse=True):
        if not part["shortfall"] or not part["suppliers"]:
            continue
        evidence = [*part["evidence"], *clauses]
        lanes = list(rows(con, "route"))
        stock_candidates = [row for row in truth["inbound"] if row["material"] == part["material"] and row["mode"] == "sea" and row["quantity"]]
        if stock_candidates:
            sea = min((row for row in stock_candidates if row["earliest"]), key=lambda row: row["earliest"], default=None)
            if sea:
                air = [r["transit_days"] for r in lanes if r["mode"] == "air" and r["transit_days"] is not None]
                option("air", f'Quote an air split for {part["label"].split(" – ")[0].lower()}',
                       f'Ask for {part["shortfall"]:,} released units at origin and a door-to-door quote. Keep booked ocean stock where it is until a feasible split is confirmed.',
                       None, f"Category Lead within €{air_limit:,} cumulative monthly category spend, otherwise CPO + dock release" if air_limit else "Confirm the air-freight approver under PP-07",
                       f'Air linehaul floor {min(air):g} days plus clearance and truck. Earliest confirmed sea lane: {sea["earliest"][:10]}.'
                       if air else f'Earliest confirmed sea lane: {sea["earliest"][:10]}.',
                       "Loaded containers and held stock require release. Confirm a signed price and revised arrival before booking.",
                       [*evidence, *sea["evidence"]], request_only=True, material=part["material"], supplier_id=sea["supplier"])
        alternatives = [rate for rate in part["suppliers"] if rate["primary"] in (0, False, "N") and rate["supplier"].get("status") == "active"]
        for rate in alternatives:
            qty = max(part["shortfall"], math.ceil(rate["moq"] or 0))
            unit_price = rate["unit_price"]
            quote = f'{qty:,} units at {rate["currency"]} {unit_price:g} per unit' if unit_price is not None else f'{qty:,} units, price pending'
            lead = rate["lead_time_days"]
            option("alternate", f'Check {rate["supplier"]["name"]} stock',
                   "Request already-produced stock, qualification documents and a firm quote.",
                   round(qty * unit_price, 2) if rate["currency"] == "EUR" and unit_price is not None else None,
                   "Verify PPAP and written release with Supplier Quality and the Category Lead",
                   f'{quote}. Quoted production lead time {lead:g} days.' if lead else quote,
                   f'Supplier status is {rate["supplier"].get("qualification_status") or "unverified"}. Manufacturing lead time can miss launch.',
                   [rate["source"], rate["supplier"]["source"], *clauses], request_only=True,
                   material=part["material"], supplier_id=rate["supplier_id"])
    if ce and std:
        option("priority", "Confirm the pack-out priority",
               "Keep all shifts active. Ask Maren to confirm who receives scarce shared stock when both lines can run.",
               0, "Head of Procurement confirms allocation",
               f'CE-first median {truth["editions"][ce]["p50"]:,} CE and {truth["editions"][std]["p50"]:,} STD. '
               f'STD-first median {truth["editions"][ce]["std_first_p50"]:,} CE and {truth["editions"][std]["std_first_p50"]:,} STD.',
               "Allocation cannot create parts. Ask for the cost of a missing launch-day copy.",
               [truth["editions"][pid]["evidence"][0] for pid in (ce, std)], request_only=True)
    return decision_menu


def authorize(con, decision, action):
    if action not in {"approve", "review"}:
        raise ValueError("Unknown decision action")
    with con:
        con.execute("""CREATE TABLE IF NOT EXISTS decisions (
          id TEXT PRIMARY KEY, status TEXT NOT NULL, decided_at TEXT NOT NULL, payload TEXT NOT NULL
        )""")
        con.execute("BEGIN IMMEDIATE")
        existing = con.execute("SELECT status FROM decisions WHERE id=?", (decision["id"],)).fetchone()
        if existing and existing[0] == "approved":
            return "approved"
        status = "approved" if action == "approve" else "review"
        con.execute("INSERT OR REPLACE INTO decisions VALUES(?,?,?,?)",
                    (decision["id"], status, now(), json.dumps(decision, ensure_ascii=False)))
    return status


def decisions(con):
    table = con.execute("SELECT 1 FROM sqlite_master WHERE name='decisions'").fetchone()
    if not table:
        return {}
    return {row["id"]: row["status"] for row in con.execute("SELECT id,status FROM decisions")}
