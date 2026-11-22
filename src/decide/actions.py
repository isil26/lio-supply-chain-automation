"""Operational recovery approvals projected from the live evidence and review records."""

from datetime import datetime, timedelta
import json
import math
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


def recovery_reviews(con, truth, options, supplier_actions, *, include_pending=False):
    """Expose the live launch reviews with their operating conditions."""
    cutoff = datetime.fromisoformat(truth["deadline"])
    approvals = [dict(review, status="awaiting_approval", policy=POLICY)
                 for review in inbound_receiving_reviews(con, truth)]
    statuses = {"review", "pending", "approved"} if include_pending else {"review"}
    pending = {option["id"]: option for option in options
               if option["status"] in statuses and option.get("kind")}
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


def _proposal(source, title, person, role, deadline, why, evidence, **details):
    return dict(source=source, title=title, person=person, owner=person, ownerRole=role,
                approver=person, deadline=deadline, dueAt=deadline, why=why, detail=why,
                evidence=[item for item in evidence if item], kind="internal",
                eurAtStake=None, costEur=None, priority=20) | details


def source_proposals(con, truth, root):
    """Project slower sources during forecast publication, with the same inputs."""
    from collections import defaultdict

    from src.chaser.negotiate import fx_rates
    from src.docs import documents
    from src.ingest.store import rows
    from .claims import late_delivery_claims
    from .packplan import plan
    from .release_gate import evaluate, load_drop

    deadline = truth["deadline"]
    gate = evaluate(truth, documents(con), rows(con, "component"), rows(con, "supplier"),
                    rows(con, "po"), rows(con, "receipt"), drop=load_drop(root))
    result = []
    for material, part in gate["parts"].items():
        revision = truth["parts"].get(material, {}).get("revision_hold")
        if not revision and (part["status"] not in {"HUMAN", "HOLD"} or not part["evidence"]):
            continue
        authority = part.get("required_authority") or {}
        requirement = part.get("required_human_action") or {}
        why = " ".join(part["reasons"])
        role = authority.get("role") or requirement.get("role") or "Supplier Quality"
        if revision:
            role = "Category Lead Print & Packaging"
            why += (f" Confirm the replacement plan under {revision['ecn']} and "
                    f"keep rev-{revision['old_revision']} stock on hold.")
        elif "Marketing must confirm" in why:
            role = "Marketing"
        elif "Engineering must confirm" in why:
            role = "Engineering"
        person = authority.get("name") or next((d["name"] for d in requirement.get("decisions", [])
                                               if d.get("name")), "Dr. Maren Vogt")
        title = f"Confirm the rev-{revision['new_revision']} replacement for {part['label']}" if revision else (
            f"Get {role} disposition for {part['label']}")
        evidence = [*part["evidence"], *((revision or {}).get("evidence") or [])]
        result.append(_proposal("release_gate", title, person, role, deadline, why, evidence,
                                material=material, priority=7))

    if all(any(pid.endswith(suffix) for pid in truth["editions"]) for suffix in ("-CE", "-STD")):
        # Compare policies using the same usable stock, receipt lags and schedule.
        report = plan(truth, weights=(1,))
        baseline = report["baseline"]
        if baseline["ce_first"]["packed"] != baseline["std_first"]["packed"]:
            ce, std = report["inputs"]["ce"], report["inputs"]["std"]
            first = baseline["ce_first"]["packed"]
            other = baseline["std_first"]["packed"]
            why = (f"Collector’s-first packs {first[ce]:,} CE and {first[std]:,} STD of the remaining units. "
                   f"Standard-first packs {other[ce]:,} CE and {other[std]:,} STD. Confirm allocation "
                   "for the numbered preorders and keep the documented holds in place.")
            evidence = [item for row in truth["editions"].values() for item in row["evidence"]]
            result.append(_proposal("packplan", "Confirm the pack-out priority", "Dr. Maren Vogt",
                                    "Head of Procurement", deadline, why, evidence,
                                    copiesCe=first[ce] - other[ce], copiesStd=first[std] - other[std],
                                    costEur=0, priority=8))

    groups = defaultdict(list)
    try:
        claims = late_delivery_claims(root, as_of=datetime.fromisoformat(deadline).date())
    except (OSError, KeyError, ValueError):
        claims = []  # The claims parser may not support a newer export format.
    for claim in claims:
        if claim["damages"] > 0 and claim["claim_status"] in {"Open", "Plausible"}:
            groups[claim["supplier_id"], claim["currency"]].append(claim)
    rates = fx_rates()
    for (supplier, currency), items in sorted(groups.items()):
        total = round(sum(row["damages"] for row in items), 2)
        dated = min((row["claim_deadline"] for row in items if row["claim_status"] == "Open"), default=None)
        evidence = [dict(source, file=source["file"].removeprefix("case-data/"))
                    for source in (items[0]["contract"], *(row["evidence"] for row in items[:4]))]
        rate = rates.get(currency)
        euros = round(total * rate, 2) if rate and math.isfinite(rate) and rate > 0 else None
        why = (f"Review {len(items)} delayed PO lines with estimated damages of {currency} {total:,.2f}. "
               "Validate the contractual notice date, any exclusions and approved recovery route.")
        if currency != "EUR" and euros is not None:
            why += f" EUR exposure uses an assumed EUR {rate:g} per {currency}."
        if not dated:
            why += " The queue deadline is the internal review target."
        result.append(_proposal("claims", f"Review late-delivery claims for {supplier}", "Dr. Maren Vogt",
                                "Head of Procurement", dated or deadline, why, evidence,
                                eurAtStake=euros, priority=35))
    return result


def _option_proposals(truth, options, reviews, other):
    by_id = {item["id"]: item for item in options}
    for review in reviews:
        option = by_id.get(review["id"], {})
        if ((option.get("approval_block") or {}).get("tool") == "supplier_reply"
                or (not option and not review["id"].startswith("receive-"))):
            continue
        evidence = [review.get("evidence"), *option.get("evidence", []), {"file": POLICY}]
        item = _proposal("recovery", review["title"], review["owner"],
                         "DC-HAM receiving" if review["priority"] in (0, 2, 3) else "Procurement and Quality",
                         review.get("dueAt") or truth["deadline"], review["detail"], evidence,
                         approver=review["approver"], costEur=review.get("price"), priority=review["priority"],
                         material=option.get("material"), optionId=option.get("id"))
        if review["priority"] in (0, 3):
            item["approvalKind"] = "dock_slot"
        elif review["priority"] == 4:
            item["approvalKind"] = "quality_exception"
        yield _with_forecast(item, option)
    covered = {item["id"] for item in reviews}
    has_packplan = any(item["source"] == "packplan" for item in other)
    for option in options:
        kind, material = option.get("kind"), option.get("material")
        if (not kind or not option.get("recommendation") or option["id"] in covered
                or (kind == "priority" and has_packplan)
                or (option.get("approval_block") or {}).get("tool") == "supplier_reply"):
            continue
        owner, role = option.get("owner") or "Dr. Maren Vogt", "Procurement"
        if material == "CMP-GAM-001" and kind in {"air", "alternate"}:
            owner, role = "Tobias Brandt", "Game Media Category Lead"
        elif kind in {"quality", "ppap_release"}:
            owner, role = "Daniel Okafor", "Supplier Quality Lead"
        if kind == "inbound":
            role = "DC-HAM site lead"
        candidate = _proposal("options", option["title"], owner, role,
                              option.get("latest_action") or option.get("deadline") or truth["deadline"],
                              option["recommendation"] + " " + option.get("impact", ""),
                              option.get("evidence", []), approver=option.get("threshold") or owner,
                              costEur=option.get("price"), material=material, optionId=option["id"],
                              priority=12 if kind != "priority" else 18)
        approval_kind = {"inbound": "dock_slot", "quality": "quality_exception", "ppap_release": "supplier_release"}
        if kind in approval_kind:
            candidate["approvalKind"] = approval_kind[kind]
        if kind in {"offer_revision_review", "air", "alternate"} and not option.get("approval_block"):
            candidate["supplierCandidate"] = option.get("supplier_id")
            candidate["qty"] = int(truth["parts"].get(material, {}).get("shortfall") or 0)
        yield _with_forecast(candidate, option)
    reviewed_air = any(option.get("shipment_id") == "SHP-2026-04311" for option in options)
    cutoff = datetime.fromisoformat(truth["deadline"])
    if not reviewed_air:
        for lot in truth.get("inbound", []):
            if (lot["id"] != "SHP-2026-04311" or lot["held"] or lot.get("missesPackout")
                    or not lot.get("earliest") or datetime.fromisoformat(lot["earliest"]) >= cutoff
                    or any(change["shipmentId"] == lot["id"] for change in truth.get("shipmentChanges", []))):
                continue
            yield _proposal("recovery", "Arrange a provisional Hamburg dock slot", "Katrin Jansen",
                            "DC-HAM site lead", truth["deadline"],
                            f"Verify carrier ETA, customs documents and FRA-to-Hamburg transfer for "
                            f"{lot['reference']} ({lot['quantity']:,.0f} game cards). Confirm slot expiry "
                            "and costs with DC-HAM before booking.",
                            [*lot["evidence"], {"file": POLICY}], priority=0, material=lot["material"],
                            approvalKind="dock_slot",
                            approver="Katrin Jansen, DC-HAM site lead (deputy Raj Patel)")
    for event in truth.get("issues", []):
        if event["kind"] != "short_ship" or event.get("material") != "CMP-GAM-001":
            continue
        gap = truth["parts"].get(event["material"], {}).get("shortfall", 0)
        if gap <= 0:
            continue
        received = next((issue for issue in truth["issues"] if issue["kind"] == "shipment_received"
                         and issue["shipment"] == event.get("shipment")), None)
        detail = (f"{event['title']}. Check the existing supplier correspondence for the "
                  f"{event['quantity']:,.0f}-card balance. Escalate any new, evidenced delivery option.")
        if received:
            detail = (f"{gap:,} game cards are still needed by launch. Review supplier correspondence for the "
                      f"{event['quantity']:,.0f}-card balance and escalate any offer with a documented delivery window.")
        yield _proposal("recovery", "Track recovery of the game-card balance", "Tobias Brandt",
                        "Game Media Category Lead", truth["deadline"],
                        detail,
                        received["evidence"] if received else event["evidence"],
                        material=event["material"], priority=6,
                        **({"recoveryKind": "short_ship_balance"} if received else {}))


def _with_forecast(item, option):
    for suffix, key in (("-CE", "copiesCe"), ("-STD", "copiesStd")):
        value = next((row["medianDelta"] for pid, row in (option.get("modeled_impact") or {}).items()
                      if pid.endswith(suffix)), None)
        if value is not None:
            item[key] = value
    return item


def _table(con, name):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()


def _triage(con, truth):
    if not _table(con, "event_decisions"):
        return
    seen = set()
    for event, category, verdict, why, raw in con.execute(
            "SELECT event,category,decision,reason,evidence FROM event_decisions ORDER BY id DESC LIMIT 30"):
        event, evidence = json.loads(event), json.loads(raw)
        subject = event.get("summary") or event.get("title") or event.get("subject") or category
        if subject in seen:
            continue
        seen.add(subject)
        if verdict not in {"act", "escalate"} or not evidence:
            continue
        owner = "Katrin Jansen" if category == "logistics" else "Dr. Maren Vogt"
        role = "DC-HAM site lead" if category == "logistics" else "Head of Procurement"
        yield _proposal("triage", f"Review triaged {category} update", owner, role,
                        truth["deadline"], why, evidence, priority=9)


def action_queue(con, truth, options, reviews, other, missed, *, include_history=False):
    """Make evidence changes invalidate stale action IDs and delivery records."""
    import hashlib

    from src.chaser import LANGUAGE, deadlines, supplier_loop
    from src.chaser.actions import internal_message
    from src.ingest.store import rows

    statuses = dict(con.execute("SELECT id,status FROM action_queue_marks")) if (
        include_history and _table(con, "action_queue_marks")) else {}
    deliveries = {row["action_id"]: dict(row) for row in con.execute(
        "SELECT action_id,status,note,approved_by,kind FROM action_sends")} if (
            include_history and _table(con, "action_sends")) else {}
    rates = {suffix: next((item for pid, item in missed.items() if pid.endswith(suffix)), {})
             for suffix in ("-CE", "-STD")}
    suppliers = {row["supplier_id"]: row for row in rows(con, "suppliers")}
    covered = {tuple(row) for row in con.execute("SELECT supplier_id,material FROM chases")} if (
        _table(con, "chases")) else set()
    candidates = [*_option_proposals(truth, options, reviews, other), *other, *_triage(con, truth)]
    for chase_id, material, supplier, parent, reply, deadline, detail in deadlines.handoffs(con):
        candidates.append(_proposal(
            "supplier_chaser", f"Review missed supplier decision window for {supplier}", "Procurement",
            "Procurement", deadline, detail, [{"text": f"Supplier thread SOONY-{parent or chase_id}"}],
            material=material, threadId=parent or chase_id, replyId=reply, priority=1,
        ))
    contacts = ({row["supplier_id"]: row for row in rows(con, "supplier")} if _table(con, "suppliers") else suppliers)
    source_options = {option["id"]: option for option in options}
    recovery_by_title = {review["title"]: review for review in reviews}
    result = {}
    for item in candidates:
        action = dict(item)
        supplier = action.pop("supplierCandidate", None)
        material = action.get("material")
        profile = suppliers.get(supplier, {})
        action["evidence"] = [dict(row, source=row.get("file") or row.get("source"))
                              if isinstance(row, dict) else row for row in action["evidence"]]
        encoded = json.dumps([action, supplier, profile.get("contact_email")], ensure_ascii=False, sort_keys=True).encode()
        action_id = hashlib.sha256(encoded).hexdigest()[:24]
        # Enrich the human handoff after deriving its ID so existing decisions keep their history.
        option = source_options.get(action.get("optionId"), {})
        review = recovery_by_title.get(action["title"], {}) if action["source"] == "recovery" else {}
        review_id = review.get("id", "")
        task = option.get("kind") or action.get("recoveryKind") or action["source"]
        if review_id.startswith("receive-"):
            task = "pickup" if action.get("approvalKind") == "dock_slot" else "receipt"
        action["task"] = task
        supplier_id = option.get("supplier_id") or supplier
        if action["source"] == "claims":
            supplier_id = next((sid for sid in contacts if action["title"].endswith(" " + sid)), None)
        contact = contacts.get(supplier_id, {})
        if action["source"] == "claims" and contact.get("name"):
            action["title"] = f"Review late-delivery claims for {contact['name']}"
        if contact.get("phone"):
            action["contact"] = {"name": contact["name"], "phone": contact["phone"]}
        if review.get("threadId"):
            action["threadId"] = review["threadId"]
        elif supplier_id and material and not action.get("threadId") and _table(con, "messages"):
            latest = con.execute("""SELECT c.id FROM chases c JOIN messages m ON m.chase_id=c.id
                                    WHERE c.supplier_id=? AND c.material=? AND m.side='in'
                                    ORDER BY julianday(m.time) DESC,m.id DESC LIMIT 1""", (supplier_id, material)).fetchone()
            if latest:
                action["threadId"] = latest[0]
        previously_routed = deliveries.get(action_id, {}).get("kind")
        if (include_history and supplier and material and action.get("qty") and profile.get("contact_email")
                and not supplier_loop.managed(supplier, material)
                and (previously_routed == "supplier" or (not previously_routed and (supplier, material) not in covered))):
            language = profile.get("preferred_language") or "en"
            subject, template = LANGUAGE.get(language, LANGUAGE["en"])
            deadline = datetime.fromisoformat(truth["deadline"]).strftime("%d %b %H:%M")
            body = template.format(name=profile.get("contact_name") or profile["name"], part=material,
                                   quantity=action["qty"], deadline=deadline)
            action.update(kind="supplier", supplierId=supplier,
                          draft={"subject": subject, "body": body, "language": language})
        if "copiesCe" in item or "copiesStd" in item:
            action["eurAtStake"] = round(sum(action.get(key, 0) * (rates[suffix].get("value") or 0)
                                             for key, suffix in (("copiesCe", "-CE"), ("copiesStd", "-STD"))), 2)
            action["eurIncludesUnconfirmedRate"] = any(
                action.get(key) and not rates[suffix].get("confirmed")
                for key, suffix in (("copiesCe", "-CE"), ("copiesStd", "-STD")))
        action.update(id=action_id, status=statuses.get(action_id) or
                      deliveries.get(action_id, {}).get("status", "pending"))
        if action["kind"] == "internal":
            subject, body = internal_message(action)
            action["draft"] = {"subject": subject, "body": body}
        if action_id in deliveries:
            action["delivery"] = deliveries[action_id]
        result[action_id] = action
    return sorted(result.values(), key=lambda a: (a["status"] in {"dismissed", "done"}, a["priority"],
                                                  -(a["eurAtStake"] or 0), a["deadline"] or "", a["title"]))


def mark_action(con, action_id, status, by, note):
    with con:
        con.execute("""CREATE TABLE IF NOT EXISTS action_queue_marks (
            id TEXT PRIMARY KEY, status TEXT NOT NULL, by_name TEXT NOT NULL, note TEXT)""")
        con.execute("INSERT OR REPLACE INTO action_queue_marks VALUES(?,?,?,?)",
                    (action_id, status, by, note))
