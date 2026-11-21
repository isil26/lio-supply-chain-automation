"""Evidence reconciliation and a shift-constrained launch forecast."""
import math
import random
import re
from collections import defaultdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from src.docs import documents
from src.ingest.store import day, rows

LOCAL = ZoneInfo("Europe/Berlin")
MODEL_RUNS = 500
LAG_HOURS = {"air": (3, 8, 20), "sea": (2, 6, 18), "road": (0, 3, 8)}
SLOT = timedelta(minutes=30)
CANCELLED = {"cancelled", "canceled", "closed", "delivered", "received"}


def value(document, name, default=None):
    items = document["fields"].get(name, [])
    return items[0]["value"] if items else default


def field_sources(document, name):
    return [entry["citation"] for entry in document["fields"].get(name, [])]


def local(date_text, hour=0):
    return datetime.combine(day(date_text), time(hour), LOCAL)


def shipment_time(shipment, route_map, shift_start):
    mode = shipment.get("mode") or "road"
    route = route_map.get(shipment.get("route_id")) or next(
        (row for row in route_map.values() if row["mode"] == mode and
         row["origin"] == shipment.get("origin") and row["destination"] == shipment.get("destination")), {}
    )
    feed_dates = [local(eta, 12) for eta in shipment["etas"] if eta]
    if not feed_dates:
        return None, route
    advertised = max(feed_dates)
    route_end = local(shipment["etd"]) + timedelta(days=route["transit_days"]) if shipment.get("etd") and route.get("transit_days") is not None else advertised
    status = shipment.get("status")
    if status == "in_delivery":
        return max(advertised, shift_start), route
    last_mile = next((row for row in route_map.values() if row["origin"] == shipment.get("destination")
                      and row["destination"] == shipment.get("dest_site") and row["mode"] == "road"), None)
    if status == "arrived_port" and shipment.get("updated_at"):
        advertised = max(advertised, datetime.fromisoformat(shipment["updated_at"]))
        route_end = advertised
    base = advertised if shipment.get("flight_evidence") else max(advertised, route_end)
    if last_mile:
        base += timedelta(days=last_mile["transit_days"])
    return max(base, shift_start), route


def simulate(editions, needs, stock, inbound, shifts, mode="ce_first", trials=MODEL_RUNS):
    rng = random.Random(1029)
    ids = sorted(editions, key=lambda pid: ("CE" not in pid) if mode == "ce_first" else ("STD" not in pid))
    totals = defaultdict(list)
    stoppages = defaultdict(lambda: defaultdict(int))
    for _ in range(trials):
        inventory = dict(stock)
        packed = {pid: editions[pid]["packed"] for pid in ids}
        schedule = sorted([
            (item["earliest"] + timedelta(hours=rng.triangular(low, high, most)), item["material"], item["quantity"])
            for item in inbound if item["earliest"] and not item["held"] and item["quantity"] > 0
            for low, most, high in [LAG_HOURS.get(item["mode"], (0, 4, 12))]
        ])
        next_arrival = 0
        first_stop = {}
        for start, end in shifts:
            cursor = start
            while cursor < end:
                while next_arrival < len(schedule) and schedule[next_arrival][0] <= cursor:
                    _, material, quantity = schedule[next_arrival]
                    inventory[material] = inventory.get(material, 0) + quantity
                    next_arrival += 1
                hours = (min(end, cursor + SLOT) - cursor).total_seconds() / 3600
                for pid in ids:
                    needed = editions[pid]["target"] - packed[pid]
                    if needed <= 0 or not needs[pid]:
                        continue
                    planned = min(needed, math.floor(editions[pid]["rate"] * hours))
                    caps = {part: math.floor(inventory.get(part, 0) / amount) for part, amount in needs[pid].items()}
                    units = max(0, min(planned, *caps.values()))
                    if units < planned and pid not in first_stop:
                        first_stop[pid] = min(caps, key=caps.get)
                    packed[pid] += units
                    for part, amount in needs[pid].items():
                        inventory[part] = inventory.get(part, 0) - units * amount
                cursor += SLOT
        for pid in ids:
            totals[pid].append(packed[pid])
            if pid in first_stop:
                stoppages[pid][first_stop[pid]] += 1

    def percentile(values, rank):
        return sorted(values)[round((len(values) - 1) * rank)]

    return {
        pid: {
            "probability": round(sum(val >= editions[pid]["target"] for val in vals) / trials, 3),
            "p10": percentile(vals, 0.10),
            "p50": percentile(vals, 0.50),
            "p90": percentile(vals, 0.90),
            "first_stop": max(stoppages[pid], key=stoppages[pid].get, default=None),
            "first_stop_trials": dict(stoppages[pid]),
        }
        for pid, vals in totals.items()
    }


def receipt_comparisons(booked, scanned):
    """Pair explicit PO lines, then reconcile identical quantities before inferring a mismatch."""
    unmatched = list(booked)
    unresolved = []
    for entry in scanned:
        line = entry["value"].get("line")
        matches = [row for row in unmatched if line is not None and line == row["po_line"]]
        if len(matches) == 1:
            unmatched.remove(matches[0])
            yield matches[0], entry
        else:
            unresolved.append(entry)

    ambiguous = []
    for entry in unresolved:
        if entry["value"].get("line") is not None:
            continue
        qty = entry["value"].get("quantity")
        matched = next((row for row in unmatched if qty == row["qty_received"]), None)
        if matched:
            unmatched.remove(matched)
            yield matched, entry
        else:
            ambiguous.append(entry)
    if len(ambiguous) == len(unmatched) == 1:
        yield unmatched[0], ambiguous[0]
    elif ambiguous and unmatched:
        # The scan has no line IDs. Compare the remaining rows as a group in the caller.
        yield unmatched, ambiguous


def readiness(con, data_root):
    tab = {table: list(rows(con, table)) for table in (
        "launch", "product", "shift", "site", "packout", "bom", "stock", "receipt", "shipment", "route",
        "po", "component", "supplier", "supply", "plan_part", "plan_inbound")}
    if not tab["launch"]:
        raise ValueError("No launch editions found. Check the workbook and sync status.")
    products = {row["product_id"]: row for row in tab["product"]}
    launch_date = max(products[row["product_id"]]["launch_date"] for row in tab["launch"])
    ctx = "soony/context/onboarding_notes.md"
    notes = (data_root / ctx).read_text() if (data_root / ctx).is_file() else ""
    launch_time = re.search(r"goes on sale[^\n]+?at (\d\d:\d\d)", notes, re.I)
    weekday = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    shifts = []
    plan_shifts = []
    for row in tab["shift"]:
        hours = re.findall(r"\d\d:\d\d", row["shift"])
        if len(hours) != 2 or row["day"].lower() not in weekday:
            continue
        shift_date = day(launch_date) - timedelta(days=(day(launch_date).weekday() - weekday.index(row["day"].lower())) % 7)
        start, end = [datetime.combine(shift_date, time.fromisoformat(hour), LOCAL) for hour in hours]
        plan_shifts.append((start, end))
    if not plan_shifts and not launch_time:
        raise ValueError("Launch cut-off is missing in onboarding notes and shift plan")
    deadline = datetime.combine(day(launch_date), time.fromisoformat(launch_time[1]), LOCAL) if launch_time else max(end for _, end in plan_shifts)
    shifts = sorted((start, min(end, deadline)) for start, end in plan_shifts if start < deadline)
    shift_start = shifts[0][0] if shifts else deadline
    site = next((site["site_id"] for site in tab["site"] if site["site_id"] in notes), None)
    site = site or max({row["site"] for row in tab["packout"]}, key=lambda ref: sum(row["site"] == ref for row in tab["packout"]), default=None)
    issues = []

    def issue(title, material, evidence, severity="high", kind=None, **details):
        issues.append(dict(title=title, material=material, evidence=evidence, severity=severity, kind=kind, **details))

    editions = {}
    for row in tab["launch"]:
        pid = row["product_id"]
        packout = [record for record in tab["packout"] if record["product_id"] == pid and record["site"] == site]
        packed = sum(record["units_packed"] for record in packout)
        if packed != row["packed"] or not packout:
            issue(f'{row["edition"]} pack-out log totals {packed:,} against workbook {row["packed"]}', None,
                  [row["source"], *[record["source"] for record in packout[-2:]]])
        packed = packed if packout else row["packed"] or 0
        editions[pid] = {"edition": row["edition"], "target": row["day_one_demand"], "packed": packed,
                         "remaining": max(0, row["day_one_demand"] - packed), "rate": row["rate_per_hour"],
                         "hours": row["hours_available"], "evidence": [row["source"], *[record["source"] for record in packout]]}

    needs = defaultdict(dict)
    bom_sources = defaultdict(list)
    embedded = {}
    for row in tab["supply"]:
        match = re.search(r"(?:fitted|installed|embedded|included)\b.*?\binto\s+(CMP-[A-Z0-9-]+)", row["note"] or "", re.I)
        if match and all(match[1] in {b["child_id"] for b in tab["bom"] if b["parent_id"] == pid}
                         for pid in editions if any(b["parent_id"] == pid and b["child_id"] == row["component_id"] for b in tab["bom"])):
            embedded[row["component_id"]] = (match[1], row["source"])
    for row in tab["bom"]:
        if row["parent_id"] in editions and (row["valid_from"] or "0001") <= launch_date <= (row["valid_to"] or "9999"):
            if row["qty_per"] <= 0:
                continue
            needs[row["parent_id"]][row["child_id"]] = row["qty_per"]
            bom_sources[row["child_id"]].append(row["source"])
    independent = {pid: {part: quantity for part, quantity in recipe.items() if part not in embedded}
                   for pid, recipe in needs.items()}
    if any(not independent.get(pid) for pid in editions):
        raise ValueError("Launch edition has no active BOM")

    snapshot = max((row["snapshot_date"] for row in tab["stock"] if row["site"] == site and row["snapshot_date"] <= launch_date), default="0001-01-01")
    stock_rows = [row for row in tab["stock"] if row["site"] == site and row["snapshot_date"] == snapshot]
    available, stock_sources = defaultdict(float), defaultdict(list)
    batches = {}
    seen_lots = set()
    for row in stock_rows:
        stock_sources[row["material_id"]].append(row["source"])
        if row["batch"]:
            lot = (row["batch"], row["material_id"], row["quantity"])
            if lot in seen_lots:
                continue
            seen_lots.add(lot)
            batches[row["batch"]] = row
        available[row["material_id"]] += row["quantity"]
    original = dict(available)
    site_receipts = [row for row in tab["receipt"] if row["plant"] == site]
    receipt_by_id = {row["gr_number"]: row for row in site_receipts}
    receipts = defaultdict(list)
    for row in site_receipts:
        if row["delivery_note"]:
            receipts[row["delivery_note"].upper()].append(row)
    suppliers = {row["supplier_id"]: row for row in tab["supplier"]}
    qualified = defaultdict(list)
    for row in tab["supply"]:
        qualified[row["component_id"]].append(dict(row, supplier=suppliers.get(row["supplier_id"], {})))

    docs = list(documents(con))
    translations, shipped, blocked, aliases = [], {}, {}, {}
    po_rows = {(row["po_number"], row["po_line"]): row for row in sorted(
        tab["po"], key=lambda p: "legacy" not in p["source"]["file"])}
    for doc in docs:
        for entry in doc["fields"].get("aliases", []):
            info = entry["value"]
            if isinstance(info, dict) and {"supplier_material", "material"} <= info.keys():
                aliases[info["supplier_material"]] = info["material"]

    adjusted_receipts = set()
    for doc in docs:
        part = value(doc, "material")
        if doc["kind"] == "inspection" and value(doc, "hold"):
            gr = value(doc, "receipt")
            batch, erp = batches.get(gr), receipt_by_id.get(gr)
            if batch and gr not in adjusted_receipts:
                part = batch["material_id"]
                available[part] -= batch["quantity"]
                adjusted_receipts.add(gr)
                evidence = [batch["source"], *field_sources(doc, "hold")]
                if erp:
                    evidence.append(erp["source"])
                stock_sources[part].extend(evidence[1:])
                issue(f'{int(batch["quantity"]):,} units recorded in SAP but placed on quality hold', part,
                      evidence, "critical", "quality_hold", quantity=int(batch["quantity"]), supplier=erp["supplier_id"] if erp else None)
        if doc["kind"] == "receiving":
            note, po = value(doc, "delivery_note"), value(doc, "po")
            cited = field_sources(doc, "delivery_note")
            booked = defaultdict(list)
            for receipt in receipts.get((note or "").upper(), []):
                if po is None or receipt["po_number"] == po:
                    booked[receipt["material_id"]].append(receipt)
            scanned = defaultdict(list)
            for entry in doc["fields"].get("items", []):
                item = entry["value"]
                if isinstance(item, dict) and type(item.get("quantity")) in {int, float}:
                    material = item.get("material")
                    scanned[aliases.get(material, material)].append(entry)
            for material, bookings in booked.items():
                for receipt, entry in receipt_comparisons(bookings, scanned[material]):
                    if isinstance(receipt, list):
                        issue(f"{note}: scan and SAP quantities could not be matched across multiple PO lines.",
                              material, [*cited, *[row["citation"] for row in entry],
                                         *[row["source"] for row in receipt]], "watch", "receipt")
                        continue
                    item = entry["value"]
                    qty = item["quantity"]
                    corrected = item.get("handwritten_quantity")
                    gr, erp_qty = receipt["gr_number"], receipt["qty_received"]
                    batch = batches.get(gr)
                    if (corrected == qty and batch and gr not in adjusted_receipts
                            and batch["quantity"] == erp_qty and 0 < corrected < erp_qty):
                        available[material] -= erp_qty - corrected
                        adjusted_receipts.add(gr)
                        evidence = [batch["source"], receipt["source"], entry["citation"]]
                        stock_sources[material].extend(evidence[1:])
                        issue(f'{note}: SAP booked {erp_qty:,.0f}, handwritten correction reads {corrected:,.0f}',
                              material, evidence, "critical", "handwriting", quantity=erp_qty - corrected,
                              supplier=receipt["supplier_id"])
                    elif qty != erp_qty:
                        issue(f'{note} scan shows {qty:,.0f} vs SAP receipt {erp_qty:,.0f}. Verify OCR and actual count.',
                              material, [*cited, entry["citation"], receipt["source"]], "watch", "receipt")
                if value(doc, "damage") and len(bookings) == 1:
                    receipt = bookings[0]
                    gr = receipt["gr_number"]
                    if gr in batches and gr not in adjusted_receipts:
                        batch = batches[gr]
                        available[material] -= batch["quantity"]
                        adjusted_receipts.add(gr)
                        evidence = [receipt["source"], batch["source"], *field_sources(doc, "damage")]
                        stock_sources[material].extend(evidence[2:])
                        issue(f'{note} has damage recorded against an on-hand lot. Quarantined pending count.',
                              material, evidence, "high", "receipt")
        if doc["kind"] == "notice":
            translation = field_sources(doc, "translation_en")
            if translation:
                translations.append({"source": doc["source"], "fields": doc["fields"]})
                issue("Supplier notice extracted for review", None, [*translation, *field_sources(doc, "effective_at")],
                      "high", "notice")
        if doc["kind"] != "confirmation":
            continue
        po = value(doc, "po")
        for entry in doc["fields"].get("shipped", []):
            info = entry["value"]
            if isinstance(info, dict) and {"reference", "quantity"} <= info.keys():
                shipped[info["reference"]] = (info["quantity"], entry["citation"], field_sources(doc, "balance"))
        if po and value(doc, "dock_hold"):
            blocked[po] = (next((item["value"].get("material") for item in doc["fields"].get("items", [])
                                if isinstance(item["value"], dict)), None), field_sources(doc, "dock_hold"))
        for entry in doc["fields"].get("items", []):
            item = entry["value"]
            if not isinstance(item, dict):
                continue
            erp = po_rows.get((po, item.get("line")))
            if not erp or erp["status"] not in {"open", "awaiting_approval", "released", "confirmed"}:
                continue
            material = aliases.get(item.get("material"), item.get("material")) or erp["material_id"]
            differences, changed_fields = [], []
            for field, confirmed in (("quantity", item.get("quantity")), ("promised_date", item.get("promised_date")),
                                     ("unit_price", item.get("unit_price")), ("material_id", material)):
                if confirmed is not None and erp[field] is not None and confirmed != erp[field]:
                    differences.append(f'{field} {erp[field]} vs {confirmed}')
                    changed_fields.append(field)
            incoterm = value(doc, "incoterm")
            if incoterm and erp.get("incoterm") and incoterm != erp["incoterm"]:
                differences.append(f'terms {erp["incoterm"]} vs {incoterm}')
                changed_fields.append("incoterm")
            if differences:
                issue(f'PO {po} line {erp["po_line"]}: ' + ", ".join(differences), material,
                      [erp["source"], entry["citation"], *field_sources(doc, "incoterm")], "high", "confirmation",
                      po=po, po_line=erp["po_line"], changed_fields=changed_fields)

    # Post-snapshot SAP postings are incremental, provided the same receipt was not already represented by a batch.
    for receipt in receipt_by_id.values():
        if snapshot < receipt["gr_date"] <= launch_date and receipt["gr_number"] not in batches:
            if "damage" in (receipt["remark"] or "").lower():
                continue
            available[receipt["material_id"]] += receipt["qty_received"]
            stock_sources[receipt["material_id"]].append(receipt["source"])

    plan = {row["reference"]: row for row in tab["plan_inbound"]}
    route_map = {row["route_id"]: row for row in tab["route"]}
    groups = defaultdict(list)
    for row in tab["shipment"]:
        groups[row["shipment_id"]].append(row)
    inbound = []
    for shipment_id, entries in groups.items():
        feeds = sorted(entries, key=lambda row: ("erp/" in row["source"]["file"], row.get("updated_at") or ""), reverse=True)
        head = feeds[0]
        reference = head.get("reference") or shipment_id
        plan_row = plan.get(reference, {})
        plan_part = plan_row.get("material_id")
        parts = set(head.get("material_ids") or ())
        material = plan_part or (next(iter(parts)) if len(parts) == 1 else None)
        if not material or (head.get("dest_site") and head["dest_site"] != site):
            continue
        evidence = [row["source"] for row in feeds] + ([plan_row["source"]] if plan_row else [])
        if len({(row["status"], row["eta"]) for row in feeds}) > 1:
            issue(f'{shipment_id} SAP vs tracker: ' + " / ".join(f'{row["status"]} {row["eta"]}' for row in feeds),
                  material, evidence[:len(feeds)], "high", "tracker")
        pos = head.get("po_numbers") or []
        hold = [source for po in pos if po in blocked and blocked[po][0] in (material, None) for source in blocked[po][1]]
        if hold:
            issue(f'{reference} held at supplier dock pending EXW or nominated forwarder', material,
                  [*evidence, *hold], "critical", "dock_hold", supplier=head.get("supplier_id"))
        confirmed_qty = head.get("quantity")
        if confirmed_qty is None:
            confirmed_qty = plan_row.get("quantity", 0)
        if reference in shipped:
            actual, citation, balance = shipped[reference]
            if actual < confirmed_qty:
                issue(f'{reference}: {actual:,.0f} flown against {confirmed_qty:,.0f} planned', material,
                      [*evidence, citation, *balance], "critical", "short_ship", supplier=head.get("supplier_id"),
                      quantity=confirmed_qty - actual)
            confirmed_qty = actual
            evidence = [*evidence, citation, *balance]
        statuses = {row["status"] for row in feeds if row["status"]}
        authoritative_cancel = "erp/" in head["source"]["file"] and head["status"] in CANCELLED
        if authoritative_cancel or (statuses and statuses <= CANCELLED) or head["status"] in {"delivered", "received"}:
            continue
        # Only shipment-specific quantities count. A PO quantity can span multiple shipments.
        eta, route = shipment_time(dict(head, etas=[row["eta"] for row in feeds], flight_evidence=reference in shipped), route_map, shift_start)
        if route:
            evidence.append(route["source"])
        inbound.append({"id": shipment_id, "reference": reference, "material": material, "quantity": float(confirmed_qty),
                        "mode": head.get("mode") or plan_row.get("mode") or "road", "eta": head.get("eta"),
                        "earliest": eta, "held": bool(hold), "supplier": head.get("supplier_id"), "evidence": evidence})

    required = defaultdict(float)
    for pid, items in needs.items():
        for part, amount in items.items():
            required[part] += editions[pid]["remaining"] * amount
    meta = {row["component_id"]: row for row in tab["component"]}
    parts = {}
    for part, demand in required.items():
        candidates = qualified[part]
        evidence = [*bom_sources[part], *stock_sources[part], *[item["source"] for item in candidates]]
        passing = [item for item in inbound if item["material"] == part and item["earliest"] and
                   item["earliest"] < deadline and not item["held"] and item["quantity"] > 0]
        by_launch = sum(item["quantity"] for item in passing)
        material_stock = available[part]
        bundled_with = embedded.get(part)
        if bundled_with:
            parent, dependency = bundled_with
            units_per_parent = max(needs[pid][part] / needs[pid][parent] for pid in needs if part in needs[pid])
            material_stock = available[parent] * units_per_parent
            by_launch = sum(item["quantity"] for item in inbound if item["material"] == parent and item["earliest"] and
                            item["earliest"] < deadline and not item["held"]) * units_per_parent
            evidence.append(dependency)
            issue(f'{part} is supplied fitted into {parent}', part, [*bom_sources[part], dependency], "watch", "embedded")
        if snapshot != "0001-01-01":
            for reported in (row for row in tab["plan_part"] if row["material_id"] == part and row["erp_stock"] is not None):
                if original.get(part, 0) != reported["erp_stock"] and not bundled_with:
                    issue(f'Workbook lists {reported["erp_stock"]:,.0f} units, stock snapshot shows {original.get(part, 0):,.0f}',
                          part, [reported["source"], *stock_sources[part]], "high", "stock")
        parts[part] = {
            "material": part, "label": meta.get(part, {}).get("description") or part, "required": demand,
            "on_hand": round(material_stock), "raw_stock": original.get(part, 0), "inbound": int(by_launch),
            "shortfall": int(max(0, demand - material_stock - by_launch)),
            "per_edition": {pid: int(recipe[part] * editions[pid]["remaining"]) for pid, recipe in needs.items() if part in recipe},
            "suppliers": candidates, "evidence": [*evidence, *[src for item in passing for src in item["evidence"]]],
            "embedded_in": bundled_with[0] if bundled_with else None, "unit_usage": {pid: recipe[part] for pid, recipe in needs.items() if part in recipe},
        }
    forecast = simulate(editions, independent, available, inbound, shifts)
    alternatives = simulate(editions, independent, available, inbound, shifts, mode="std_first")
    for pid in forecast:
        editions[pid].update(forecast[pid], std_first_p50=alternatives[pid]["p50"],
                             std_first_probability=alternatives[pid]["probability"])
    for item in inbound:
        item["earliest"] = item["earliest"].isoformat() if item["earliest"] else None
    return {"name": re.search(r"([^.\n]+?) goes on sale", notes)[1] if re.search(r"([^.\n]+?) goes on sale", notes) else "Launch",
            "deadline": deadline.isoformat(), "site": site, "snapshot": snapshot,
            "editions": editions, "parts": parts, "inbound": inbound, "issues": issues, "notices": translations,
            "shifts": [[start.isoformat(), end.isoformat()] for start, end in shifts],
            "source": {"file": ctx, "quote": launch_time[0] if launch_time else "Launch cut-off from shift plan"},
            "data_quality": {"documents": len(docs), "errors": sum(bool(doc["error"]) for doc in docs)},
            "model": {"runs": MODEL_RUNS, "allocation": "Collector’s first", "lag_hours": LAG_HOURS,
                      "assumptions": "Fixed shift windows and rate, 30-minute dispatch buckets, route minimum plus last-mile route and independent triangular handling delays. Estimates are scenario frequencies."}}
