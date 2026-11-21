"""Replan disrupted launch shipments and request nonbinding recovery coverage."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re

from src.ingest.store import get_state, save_state
from src.truth import LAG_HOURS, SLOT

from .allowlist import check_recipient
from .guardrails import Guardrails
from .reply_plan import cited_reference, supply_constraint
from .supplier_loop import _correspondence, as_time

STATE = "supplierRecovery"
CANCELLED = re.compile(
    r"\b(?:status\s*[:：=]\s*cancell?ed|(?:has been|was|is) cancell?ed|"
    r"we (?:have )?cancell?ed (?:the |this |shipment |lot )|zosta\w* anulowan\w*|anulowano)\b"
    r"|已(?:经)?取消|취소(?:되었습니다|했습니다|됐습니다)", re.I)
CANCEL_NEGATED = re.compile(r"\b(?:not|never) (?:been )?cancell?ed\b|\bnie (?:zosta\w* )?anulowan|未取消|취소되지", re.I)
RESTORED = re.compile(
    r"\b(?:status\s*[:=]\s*reinstated|(?:has been|was|is) reinstated)\b", re.I)
WITHDRAWN = re.compile(
    r"\b(?:offer|quote|reservation) (?:has been |is |was |is now )?"
    r"(?:withdrawn|cancell?ed|no longer available)\b|"
    r"\bwycofano (?:ofertę|rezerwację)\b|报价已取消|견적(?:이)? 취소되었습니다", re.I)
QUANTITY = re.compile(
    r"^\s*(?:revised )?(?:shipment quantity|ship qty|quantity|ilość wysyłki|출하 수량|发货数量)"
    r"\s*[:：=]\s*(\d+(?:[ ,]\d{3})*)\s*(?:units?|pcs?|szt\.?)?\s*$", re.I | re.M)
SHIP_TIME = re.compile(
    r"^\s*(?:revised )?(?:DC-HAM ETA|ETA (?:at )?DC-HAM|Hamburg handoff|dostawa DC-HAM|DC-HAM 납품|DC-HAM 交付)"
    r"\s*[:：=]\s*(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2}))\s*$",
    re.I | re.M)
QUOTED = re.compile(r"^\s*(?:-{2,}\s*(?:original message|forwarded message)\b|on .+ wrote:\s*$)", re.I | re.M)
NO_COVER = re.compile(
    r"\b(?:no (?:released )?(?:european|EU) (?:stock|inventory)|no (?:replacement|stock) available|"
    r"(?:do not have|don't have) (?:any )?(?:released )?(?:european|EU) (?:stock|inventory)|"
    r"(?:zero|0) (?:units |pieces )?available|cannot (?:deliver|supply) (?:any|before|by)\b|"
    r"nie (?:możemy|mogę) potwierdzić żadnej dodatkowej ilości)\b|可分批发运的数量为零", re.I)
INFORMATION = {
    "en": ("Urgent coverage check for {part}",
           "Can you supply up to {quantity:,} released units of {part} for handoff at DC-HAM by {deadline}? "
           "Please confirm any partial quantity, time-zoned Hamburg handoff, delivered quote and current shipping "
           "evidence. If that window is unavailable, please give your earliest feasible handoff. "
           "This is a request for information only."),
    "pl": ("Pilne potwierdzenie dostępności {part}",
           "Czy mogą Państwo dostarczyć do {quantity:,} zwolnionych sztuk {part} do DC-HAM do {deadline}? "
           "Prosimy podać możliwą ilość częściową, datę i godzinę dostawy ze strefą czasową, cenę z dostawą "
           "i aktualne dokumenty przewozowe. Jeśli termin jest niemożliwy, prosimy o najwcześniejszą datę. "
           "To wyłącznie zapytanie informacyjne."),
    "ko": ("{part} 긴급 공급 확인",
           "{deadline}까지 DC-HAM에 품질 승인된 {part} 최대 {quantity:,}개를 공급할 수 있습니까? "
           "부분 수량, 시간대가 표시된 인계 시각, 배송 포함 견적 및 운송 증빙을 알려 주십시오. "
           "불가능하면 가장 빠른 인계 일정을 알려 주십시오. 이 메일은 정보 요청이며 발주가 아닙니다."),
    "zh": ("紧急确认 {part} 库存",
           "请确认能否在 {deadline} 前向 DC-HAM 交付最多 {quantity:,} 件已获质量放行的 {part}。"
           "请提供可部分交付的数量、含时区的交付时间、到货报价及运输凭证。若无法按时交付，请告知最早交付时间。"
           "本邮件仅为信息询问，并非订单。"),
}


def watermark(con):
    return con.execute("""SELECT coalesce(max(id),0) FROM messages
                          WHERE side='in' AND json_extract(transport,'$.mode')='inbox'""").fetchone()[0]


def pending_revision(con, after, through=None):
    bodies = (unquoted(row[0]) for row in con.execute("""
        SELECT body FROM messages WHERE id>? AND id<=? AND side='in'
          AND json_extract(transport,'$.mode')='inbox'
    """, (after, watermark(con) if through is None else through)))
    return any(WITHDRAWN.search(body) or _revision(body) for body in bodies)


def unquoted(body):
    return QUOTED.split(body, maxsplit=1)[0]


def _only(pattern, body):
    matches = set(pattern.findall(body))
    return next(iter(matches)) if len(matches) == 1 else None


def _revision(body):
    restored = bool(RESTORED.search(body))
    cancelled = bool(CANCELLED.search(body) and not CANCEL_NEGATED.search(body) and not WITHDRAWN.search(body))
    if restored and cancelled:
        return {}
    eta = as_time(_only(SHIP_TIME, body))
    quantity = _only(QUANTITY, body)
    result = {}
    if restored or cancelled:
        result["cancelled"] = cancelled
    if eta:
        result["earliest"] = eta
    if quantity:
        result["quantity"] = int(quantity.replace(",", "").replace(" ", ""))
    return result


def _bound_status(body, lot):
    """A different shipment in the same email cannot change this lot's status."""
    for clause in re.split(r"[!?]\s+|\.\s+|\n", body):
        if cited_reference(clause, lot) and (CANCELLED.search(clause) or RESTORED.search(clause)):
            return True
    return bool(re.search(r"^\s*(?:shipment )?status\s*[:：=]", body, re.I | re.M))


def _verified(con, pair):
    return [reply for reply in _correspondence(con, *pair, "live")[1]
            if reply["parent"]["envelope"].get("status") in {"smtp_accepted", "gmail_sent"}]


def reconcile(con, inbound, deadline, previous):
    """Rebuild effective lots from source data plus latest applicable, matched events."""
    old_plan = {lot["id"]: lot for lot in previous.get("sourceShipmentPlan", previous.get("inbound", []))}
    source_changes = {item["shipmentId"]: item for item in previous.get("shipmentChanges", [])
                      if item["cause"] == "source"}
    plans, changes, usable = [], [], []
    pairs = {}
    for lot in inbound:
        plans.append({**lot, "earliest": lot["earliest"].isoformat() if lot["earliest"] else None})
        pairs.setdefault((lot["supplier"], lot["material"]), []).append(lot)
    for pair, lots in pairs.items():
        mail = {}
        for reply in _verified(con, pair):
            content = unquoted(reply["body"])
            if not (revision := _revision(content)):
                continue
            matches = [lot for lot in lots if cited_reference(content, lot)]
            if len(matches) != 1:
                continue
            lot, = matches
            if "cancelled" in revision and not _bound_status(content, lot):
                del revision["cancelled"]
            updated = as_time(lot.get("sourceUpdatedAt"))
            if updated and reply["authored"] < updated:
                continue
            fields, _ = mail.get(lot["id"], ({}, None))
            # A reinstatement starts a new explicit revision; stale restrictions do not carry forward.
            mail[lot["id"]] = (({} if revision.get("cancelled") is False else fields) | revision, reply)

        for lot in lots:
            sid, ref = lot["id"], lot["reference"]
            source_cancel = lot["sourceCancelled"]
            fields, reply = mail.get(sid, ({}, None))
            quantity, eta = lot["quantity"], lot["earliest"]
            past = old_plan.get(sid, {})
            prior = source_changes.get(sid, {})
            planned_qty = prior.get("plannedUnits", past.get("quantity", quantity))
            planned_eta = as_time(prior.get("plannedEta") or past.get("earliest")) or eta
            planned_launch = planned_eta and planned_eta < deadline and not past.get("held", lot["held"])
            minimum_hours = LAG_HOURS.get(lot.get("mode"), (0,))[0]
            latest_handoff = deadline - SLOT - timedelta(hours=minimum_hours)
            reason = None
            cause = "source"
            if source_cancel:
                reason = "cancelled"
            elif planned_launch and lot["held"]:
                reason = "held"
            elif planned_launch and (quantity < planned_qty or (eta and planned_eta <= latest_handoff < eta)):
                reason = "reduced" if quantity < planned_qty and eta and eta <= latest_handoff else "delayed"

            effective_qty, effective_eta = quantity, eta
            if not source_cancel and fields:
                effective_qty = min(quantity, fields.get("quantity", quantity))
                if "earliest" in fields:
                    # A supplier's earlier estimate cannot bypass the route minimum.
                    effective_eta = max(eta, fields["earliest"]) if eta else fields["earliest"]
                if fields.get("cancelled") or (quantity and effective_qty == 0):
                    reason, cause = "cancelled", "mail"
                elif effective_qty < quantity or effective_eta != eta:
                    reason, cause = ("delayed" if effective_eta and effective_eta != eta else "reduced"), "mail"
                if cause == "mail":
                    planned_qty, planned_eta = quantity, eta
                    planned_launch = eta and eta < deadline and not lot["held"]
            if reason == "cancelled":
                effective_qty = 0
            misses_packing = bool(reason == "delayed" and effective_eta and effective_eta > latest_handoff)
            if effective_qty > 0 or (not reason and not source_cancel):
                usable.append({**lot, "quantity": effective_qty, "earliest": effective_eta,
                               "missesPackout": misses_packing})
            if not reason or not planned_launch or planned_qty <= 0:
                continue
            evidence = lot["evidence"]
            effective_by_cutoff = (effective_qty if not misses_packing and not lot["held"]
                                   and effective_eta and effective_eta < deadline else 0)
            changes.append({
                "shipmentId": sid, "reference": ref, "material": lot["material"], "supplier": lot["supplier"],
                "kind": reason, "cause": cause, "title": f"{ref}: shipment {reason}",
                "plannedUnits": round(planned_qty), "plannedEta": planned_eta.isoformat(),
                "currentUnits": round(effective_qty),
                "lostUnits": round(max(0, planned_qty - effective_by_cutoff)),
                "eta": effective_eta.isoformat() if effective_eta and reason != "cancelled" else None,
                "threadId": reply["chase_id"] if cause == "mail" else None,
                "replyId": reply["id"] if cause == "mail" else None,
                "replyTo": reply["external_id"] if cause == "mail" else None,
                "parentId": reply["parent"]["external_id"] if cause == "mail" else None,
                "evidence": evidence,
            })
    order = {lot["id"]: index for index, lot in enumerate(inbound)}
    usable.sort(key=lambda lot: order[lot["id"]])
    return usable, {"shipmentChanges": changes, "sourceShipmentPlan": plans}


def _withdrawn_offers(con, truth):
    from .negotiate import parse_offer

    for row in con.execute("""
        SELECT DISTINCT c.supplier_id,c.material FROM chases c
        JOIN messages m ON m.chase_id=c.id
        WHERE m.side='in' AND json_extract(m.transport,'$.mode')='inbox'
    """):
        supplier, material = row
        if not truth["parts"].get(material, {}).get("shortfall"):
            continue
        quotes, withdrawals = {}, {}
        for reply in _verified(con, (supplier, material)):
            thread = reply["chase_id"]
            body = unquoted(reply["body"])
            if WITHDRAWN.search(body):
                if thread in quotes:
                    withdrawals[thread] = reply
                continue
            offer = parse_offer(body)
            if offer["quantity"] and offer["unit_price"]:
                quotes[thread] = offer["quantity"]
                withdrawals.pop(thread, None)
        for thread, reply in withdrawals.items():
            yield {
                "shipmentId": f"offer-{thread}", "material": material, "supplier": supplier,
                "title": f"{reply['supplier']}: supplier offer withdrawn", "kind": "offer_withdrawn",
                "threadId": thread, "replyId": reply["id"], "evidence": [], "reference": None,
                "replyTo": reply["external_id"], "parentId": reply["parent"]["external_id"],
                "lostUnits": quotes[thread], "eta": None,
            }


def _contact_allowed(contact, deadline):
    if contact.get("qualification_status") != "qualified" or contact.get("status") not in {"active", "at_risk"}:
        return False
    if (valid := contact.get("qualification_valid_until")) and valid < deadline.date().isoformat():
        return False
    try:
        check_recipient(contact.get("contact_email") or "")
    except PermissionError:
        return False
    return True


def _no_cover(replies, since, due):
    for reply in reversed(replies):
        if reply["authored"] < since:
            break
        body = unquoted(reply["body"])
        if NO_COVER.search(body) or supply_constraint(body).get("disposition") == "no_launch_cover":
            return True
        if (eta := as_time(_only(SHIP_TIME, body))) and _only(QUANTITY, body):
            return eta >= due
    return False


def _draft_id(truth, change, target):
    return sha256(f"recovery:{truth['deadline']}:{change['shipmentId']}:{target}".encode()).hexdigest()[:10].upper()


def _draft(con, truth, change, contact, gap, due, part):
    from .followup import hamburg_time

    target = contact["supplier_id"]
    source = target == change["supplier"]
    ref = _draft_id(truth, change, target)
    language = contact.get("preferred_language") or "en"
    subject, template = INFORMATION.get(language, INFORMATION["en"])
    material = change["material"]
    required_rev = (part.get("revision_hold") or {}).get("new_revision")
    description = f"{material} rev {required_rev}" if required_rev else material
    wording = dict(part=description, quantity=gap, deadline=hamburg_time(due))
    prefix = f"{change['reference']}\n\n" if source and change["reference"] else ""
    body = prefix + template.format(**wording) + "\n\nSoony launch team"
    if not Guardrails().validate_draft(body).ok:
        return None
    con.execute("""
        INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)
        VALUES(?,?,?,?,?,?,'recovery draft',?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET qty=excluded.qty,body=excluded.body,status=excluded.status,
          address=excluded.address,language=excluded.language,subject=excluded.subject
        WHERE chases.status IN ('recovery draft','recovery withdrawn')
          AND (chases.qty<>excluded.qty OR chases.body<>excluded.body OR chases.status<>excluded.status
               OR chases.address<>excluded.address OR chases.language<>excluded.language)
        """, (ref, target, contact["name"], contact["contact_email"], language,
              f"[SOONY-{ref}] {subject.format(**wording)}", material, gap, body, due.isoformat()))
    return ref


def advance(con, truth, *, clock=None):
    """Queue one enquiry per shipment and qualified contact; retire unneeded drafts."""
    from . import activity

    clock = clock or datetime.now(timezone.utc)
    actions, drafts, claimed = [], {}, set()
    contacts_used = set()
    if not truth:
        return
    deadline = as_time(truth["deadline"])
    last_shift = as_time(truth["shifts"][-1][1]) if truth.get("shifts") else deadline
    # A newly offered lot must reach receiving before the last pack-out slot.
    due = min(deadline, last_shift) - timedelta(minutes=30)
    start = as_time(truth["shifts"][0][0]) if truth.get("shifts") else clock - timedelta(days=1)
    with con:
        con.execute("BEGIN IMMEDIATE")
        now_plan = get_state(con, STATE, {})
        claimed.update(now_plan.get("claimed", []))
        changes = [*truth.get("shipmentChanges", []), *_withdrawn_offers(con, truth)]
        for change in sorted(changes, key=lambda item: (-item["lostUnits"], item["shipmentId"])):
            material = change["material"]
            part = truth["parts"].get(material, {})
            if change["threadId"]:
                claimed.add(change["threadId"])
                if con.execute("SELECT 1 FROM sqlite_master WHERE name='deals'").fetchone():
                    con.execute("""
                        UPDATE chases SET status='superseded draft'
                        WHERE status='draft' AND id IN (SELECT email_id FROM deals WHERE thread_id=?)
                    """, (change["threadId"],))
            gap = part.get("shortfall", 0)
            action = {
                "case": "recovery", "scope": "live", "kind": "shipment_change",
                "id": f"recovery-{change['shipmentId']}", "title": change["title"], "status": "escalated",
                "owner": "Procurement / DC-HAM", "threadId": change["threadId"], "replyId": change["replyId"],
                "facts": [], "eta": change["eta"], "evidence": next(iter(change["evidence"]), None),
                "detail": (("The withdrawn offer has been excluded from recovery. " if change["kind"] == "offer_withdrawn"
                            else "The forecast now uses the revised shipment. ")
                           + f"{gap:,} {material} units remain uncovered at cutoff."),
            }
            actions.append(action)
            if not gap or not change["lostUnits"] or material in contacts_used:
                continue
            contacts_used.add(material)
            count_before = len(actions)
            for candidate in part["suppliers"]:
                contact = candidate["supplier"]
                if not _contact_allowed(contact, deadline):
                    continue
                target = contact["supplier_id"]
                ref = _draft_id(truth, change, target)
                sent = con.execute("SELECT 1 FROM messages WHERE chase_id=? AND side='out'", (ref,)).fetchone()
                if not sent and (clock >= due or _no_cover(_verified(con, (target, material)), start, due)):
                    continue
                if not (ref := _draft(con, truth, change, contact, gap, due, part)):
                    continue
                claimed.add(ref)
                drafts[ref] = {"replyTo": change["replyTo"], "originMessageId": change["parentId"]} if target == change["supplier"] else {}
                enquiry = {
                    "id": f"request-{ref}", "case": "recovery", "kind": "coverage_request", "scope": "live",
                    "title": f"Check recovery stock with {contact['name']}", "status": "queued", "owner": "Supplier Chaser",
                    "threadId": ref, "facts": [],
                    "detail": f"Request up to {gap:,} released {material} units, including partial coverage. "
                              "Any offer still needs PP-07 and a verified receiving window.",
                }
                actions.append(enquiry)
            if len(actions) == count_before:
                action["detail"] += (" The window for new enquiries has closed." if clock >= due else
                                     " No qualified contact has a plausible launch-window response. Escalate to Procurement.")
        for ref in now_plan.get("drafts", {}).keys() - drafts.keys():
            con.execute("UPDATE chases SET status='recovery withdrawn' WHERE id=? AND status='recovery draft'", (ref,))
        plan = {"actions": actions, "drafts": drafts, "claimed": sorted(claimed),
                "mailWatermark": get_state(con, "forecastMailWatermark", 0), "sendBy": due.isoformat()}
        if plan != now_plan:
            save_state(con, STATE, plan)
        known = {item["id"] for item in now_plan.get("actions", [])}
        for item in actions:
            if item["kind"] == "shipment_change" and item["id"] not in known:
                activity(con, "Supplier Recovery", item["title"], "warning")


def claimed_threads(con):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='state'").fetchone():
        return set()
    return set(get_state(con, STATE, {}).get("claimed", []))


def superseded_offer(con, deal_id):
    row = con.execute("SELECT thread_id FROM deals WHERE id=?", (deal_id,)).fetchone()
    return bool(row and row[0] in superseded_threads(con))


def superseded_threads(con):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='state'").fetchone():
        return set()
    return {item["threadId"] for item in get_state(con, STATE, {}).get("actions", [])
            if item["kind"] == "shipment_change" and item.get("threadId")}


def hamburg_eta(body):
    return as_time(_only(SHIP_TIME, unquoted(body)))


def eligible_draft(con, ref):
    state = get_state(con, STATE, {})
    if ref not in state.get("drafts", {}) or state["mailWatermark"] != watermark(con):
        return None
    if datetime.now(timezone.utc) >= as_time(state["sendBy"]):
        return None
    return state["drafts"][ref] | {"recovery": True}


def view(con):
    """Combine queued decisions with actual dispatch and matched reply evidence."""
    state = get_state(con, STATE, {})
    actions = state.get("actions", [])
    for item in actions:
        if item["kind"] != "coverage_request":
            continue
        thread = item["threadId"]
        chase = con.execute("SELECT status,deadline FROM chases WHERE id=?", (thread,)).fetchone()
        sent = con.execute("""SELECT time,transport FROM messages WHERE chase_id=? AND side='out'
                             ORDER BY id DESC LIMIT 1""", (thread,)).fetchone()
        if not sent:
            continue
        envelope = json.loads(sent["transport"] or "{}")
        item["transport"] = {**envelope, "time": sent["time"]}
        item["status"] = "awaiting_reply" if chase["status"] == "awaiting reply" else "escalated"
        reply = con.execute("""
            SELECT m.id,m.body FROM messages m JOIN messages parent ON parent.chase_id=m.chase_id
            WHERE m.chase_id=? AND m.side='in' AND parent.side='out'
              AND json_extract(m.transport,'$.mode')='inbox'
              AND json_extract(parent.transport,'$.status') IN ('smtp_accepted','gmail_sent')
              AND parent.external_id=json_extract(m.transport,'$.inReplyTo')
            ORDER BY julianday(coalesce(json_extract(m.transport,'$.authoredAt'),m.time)) DESC,m.id DESC LIMIT 1
        """, (thread,)).fetchone()
        if reply is not None:
            from .negotiate import parse_offer

            item["replyId"] = reply["id"]
            body = unquoted(reply["body"])
            offer = parse_offer(body)
            eta = as_time(_only(SHIP_TIME, body))
            if (not NO_COVER.search(body) and offer["quantity"] and eta
                    and eta < as_time(chase["deadline"]) and offer["unit_price"]):
                item.update(status="approval_required", eta=eta.isoformat(), policy="soony/context/approval_policy_PP-07.pdf")
                item["detail"] = f"Supplier quotes {offer['quantity']:,} units. Verify release, delivered terms and receiving before any commitment."
            else:
                item["detail"] = "Supplier replied. No eligible priced coverage with a time-zoned Hamburg handoff is verified."
    return actions
