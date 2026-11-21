"""Persistent decisions for the launch-critical card and art-book threads."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from src.decide.inbound import EXPEDITED_HANDLING_HOURS, POLICY
from src.truth.sensitivity import counterfactual

from .allowlist import check_recipient
from .reply_plan import ETA, HOLD, cited_reference

CARD = ("SUP-0010", "CMP-GAM-001")
BOOK = ("SUP-0028", "CMP-GAM-008")
CASES = {CARD: "game_card", BOOK: "karton"}
SHIPMENT = "SHP-2026-04311"
AMOUNT = r"(\d{1,3}(?:[., \u00a0]\d{3})+|\d+)"
MOQ = re.compile(rf"\b(?:minimum|MOQ|minimaln\w+)[^\n]{{0,100}}?\b{AMOUNT}\s*(?:units?|pcs?|pieces?|szt(?:\.|uk\w*)?)\b", re.I)
BOOK_QUANTITY = re.compile(rf"\b(?:możemy|potwierdzamy,? że możemy)\s+zarezerwować\s+{AMOUNT}\b", re.I)
PRICE = re.compile(r"\b(?:EUR\s*\d[\d .\u00a0,]*|\d[\d .\u00a0,]*\s+EUR)\b", re.I)
SMALL_LOT = re.compile(r"\b(?:small[- ]lot|MOQ|minimum|minimaln\w+|mał\w+ parti\w+)\b", re.I)
LOT_PENDING = re.compile(r"\b(?:sprawdz\w*[^\n.]{0,90}|wróc\w* z potwierdzon\w*[^\n.]{0,90}|(?:checking|check)\s+(?:internally|whether|if)[^\n.]{0,90}|(?:will|shall)\s+(?:get back|confirm)[^\n.]{0,90})", re.I)
LOT_DENIAL = re.compile(r"\b(?:cannot|can’t|can't|can not|unable to)\s+(?:offer|accept|supply|make an exception)[^\n.]{0,80}|\bnie (?:możemy|będziemy mogli)\s+(?:zaoferować|dostarczyć|zrealizować)[^\n.]{0,80}", re.I)
ACCEPTED = {"dry_run", "smtp_accepted", "gmail_sent"}
DOCS = {"invoice", "packing_list", "air_waybill"}
SLOT = re.compile(r"^(?:receiving |dock )slot\s*:\s*(?:confirmed|reserved)\b[^\n]*", re.I | re.M)
ETA_NOTICE = re.compile(r"\b(?:ETA|arrival|delayed|rescheduled)\b", re.I)
CARRIER_PENDING = re.compile(
    r"\b(?:checking|confirming)\s+(?:the (?:ETA|arrival time)\s+)?with\s+(?:the\s+)?(?:airline|carrier)\b"
    r"|항공사에\s*확인\s*중", re.I,
)
MESSAGE_ID = re.compile(r"<[^<>\s]+>")


def managed(supplier, material):
    return (supplier, material) in CASES


def import_verified(con, path):
    """Feed the operational worker from the local, verified mailbox checkpoint."""
    if not path or not Path(path).is_file():
        return False
    path = Path(path).resolve()
    if any(db_path and Path(db_path).resolve() == path for _, _, db_path in con.execute("PRAGMA database_list")):
        return False
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)) as history:
            history.row_factory = sqlite3.Row
            history.execute("BEGIN")
            records = []
            for pair in CASES:
                sent, replies = _correspondence(history, *pair, "verified")
                for record in [*[m for m in sent if m["envelope"].get("status") == "gmail_sent"], *replies]:
                    records.append(record)
    except sqlite3.OperationalError:
        return False
    with con:
        con.execute("BEGIN IMMEDIATE")
        for record in records:
            thread = record["chase_id"]
            if record["side"] == "in":
                parent = con.execute("SELECT chase_id FROM messages WHERE external_id=? AND side='out'",
                                     (record["parent"]["external_id"],)).fetchone()
                if not parent:
                    continue
                thread = parent[0]
            else:
                con.execute("""INSERT OR IGNORE INTO chases
                               (id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline,message_id)
                               VALUES (?,?,?,?,?,?,'verified correspondence',?,?,?,?,?)""",
                            (thread, record["supplier_id"], record["supplier"], record["address"], record["language"],
                             record["subject"], record["material"], record["qty"], record["body"], record["deadline"],
                             record["external_id"]))
                bound = con.execute("SELECT supplier_id,material,lower(address) FROM chases WHERE id=?", (thread,)).fetchone()
                if tuple(bound) != (record["supplier_id"], record["material"], record["address"].casefold()):
                    continue
            con.execute("""INSERT OR IGNORE INTO messages
                           (chase_id,external_id,side,sender,body,time,parsed,transport) VALUES (?,?,?,?,?,?,?,?)""",
                        (thread, record["external_id"], record["side"], record["sender"], record["body"], record["time"],
                         record["parsed"], record["transport"]))
    return True


def schema(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS supplier_loop_actions (
          id TEXT PRIMARY KEY, scope TEXT NOT NULL, case_name TEXT NOT NULL,
          active INTEGER NOT NULL, payload TEXT NOT NULL
        )
    """)


def as_time(value):
    try:
        parsed = datetime.fromisoformat(value or "")
        return parsed if parsed.tzinfo else None
    except ValueError:
        return None


def number(value):
    return int(re.sub(r"\D", "", value))


def _document_signatures(reply):
    documents = json.loads(reply["parsed"] or "{}").get("attachments", [])
    return tuple(sorted({
        (doc["kind"], sha256(" ".join(doc["text"].split()).encode()).hexdigest())
        for doc in documents
        if doc.get("kind") in DOCS and not doc.get("needs_review") and doc.get("text", "").strip()
    }))


def _correspondence(con, supplier, material, scope):
    modes = {"verified": {"gmail"}, "demo": {"dry_run"}, "live": {"smtp", "gmail"}}[scope]
    out = []
    inbound = []
    sent = {}
    for row in con.execute("""
        SELECT m.*, c.subject, c.qty, c.due_at, c.address, c.language, c.supplier, c.supplier_id, c.material, c.deadline
        FROM messages m JOIN chases c ON c.id=m.chase_id
        WHERE c.supplier_id=? AND c.material=? ORDER BY m.id
    """, (supplier, material)):
        envelope = json.loads(row["transport"] or "{}")
        item = {**dict(row), "envelope": envelope}
        if row["side"] == "out" and envelope.get("mode") in modes:
            out.append(item)
            if envelope.get("status") in ACCEPTED | {"attempting", "delivery_uncertain"}:
                sent[row["external_id"]] = item
        elif row["side"] == "in" and envelope.get("mode") == ("simulated" if scope == "demo" else "inbox"):
            inbound.append(item)

    replies = []
    for reply in inbound:
        parent = sent.get(reply["envelope"].get("inReplyTo"))
        if not parent or parent["chase_id"] != reply["chase_id"]:
            continue
        # The provider Date orders explicit revisions. Reject impossible time order
        # rather than letting it override an already recorded decision.
        authored = as_time(reply["envelope"].get("authoredAt")) or as_time(reply["time"])
        parent_time = as_time(parent["time"])
        if authored and parent_time and authored + timedelta(minutes=2) >= parent_time:
            documents = _document_signatures(reply) if (supplier, material) == CARD else ()
            replies.append({**reply, "authored": authored, "parent": parent, "documents": documents})
    replies.sort(key=lambda r: (r["authored"], r["id"]))
    unique = {}
    for reply in replies:
        key = (reply["parent"]["external_id"], " ".join(reply["body"].split()).casefold(), reply["documents"])
        unique.setdefault(key, reply)
    return out, list(unique.values())


def _action(case, kind, title, status, detail, *, thread=None, reply=None, facts=None, **extra):
    if reply:
        thread = reply["chase_id"]
        extra["originMessageId"] = reply["parent"]["external_id"]
    return {
        "case": case, "kind": kind, "title": title, "status": status, "detail": detail,
        "threadId": thread, "replyId": reply["id"] if reply else None,
        "replyAt": reply["authored"].isoformat() if reply else None,
        "facts": facts or [], **extra,
    }


def _queue_email(con, scope, case, truth, supplier_id, material, *, shipment=None):
    from . import DOCUMENTS, LANGUAGE, rows
    from .guardrails import Guardrails

    game = case == "game_card"
    title = "Request customs documents and flight ETA" if game else "Ask Karton about finished art-book stock"
    contact = next((s for s in rows(con, "suppliers") if s["supplier_id"] == supplier_id), {})
    address = contact.get("contact_email")
    try:
        if address is None:
            raise PermissionError
        check_recipient(address)
    except PermissionError:
        return _action(case, "contact_review", "Verify the shipment contact" if game else "Verify Karton correspondence",
                       "escalated", "Procurement needs a verified, allowed supplier contact before sending.",
                       owner="Procurement", policy=POLICY)
    if scope != "demo" and not game:
        return _action(case, "history_review", "Check for the existing Karton request", "escalated",
                       "Check the verified team mailbox before contacting Karton about this lot.",
                       owner="Procurement", policy=POLICY)

    ref = sha256(f"loop:{truth['deadline']}:{scope}:{case}".encode()).hexdigest()[:10].upper()
    lang = contact.get("preferred_language") or "en"
    deadline = datetime.fromisoformat(truth["deadline"]).strftime("%d %b %H:%M")
    gap = truth["parts"][material]["shortfall"]
    language_map = DOCUMENTS if game else LANGUAGE
    subject, template = language_map.get(lang, language_map["en"])
    values = dict(name=contact.get("contact_name") or contact["name"], part=material,
                  quantity=gap, deadline=deadline)
    if game:
        values.update(ref=SHIPMENT, units=int(shipment["quantity"]))
    body = template.format(**values)
    if not Guardrails().validate_draft(body).ok:
        return _action(case, "draft_review", "Review supplier information request", "escalated",
                       "The generated request requires Procurement review before sending.", owner="Procurement")
    con.execute("""
        INSERT OR IGNORE INTO chases
        (id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)
        VALUES (?,?,?,?,?,?,'loop draft',?,?,?,?)
    """, (ref, supplier_id, contact["name"], address, lang, f"[SOONY-{ref}] {subject.format(**values)}",
          material, gap, body, truth["deadline"]))
    return _action(case, "information_request", title, "queued", "This request asks for information only.",
                   thread=ref, dispatchThread=ref, routine=game)


def _pending(case, sent, clock):
    if not sent:
        return None
    message = max(sent, key=lambda x: (as_time(x["time"]) or datetime.min.replace(tzinfo=timezone.utc), x["id"]))
    status = message["envelope"].get("status")
    thread = message["chase_id"]
    if status not in ACCEPTED:
        return _action(case, "reconcile_dispatch", "Verify the dispatch", "escalated",
                       "Check the recorded Message-ID and transport outcome before any retry.",
                       thread=thread, owner="Procurement", dispatchThread=thread)
    due = (as_time(message["time"]) or clock) + timedelta(hours=1)
    if clock >= due:
        return _action(case, "no_reply", "Escalate an unanswered request", "escalated",
                       "Procurement should verify the status through its approved channel.",
                       thread=thread, owner="Procurement", dispatchThread=thread, dueAt=due.isoformat())
    return _action(case, "await_reply", "Wait for the matched supplier reply", "awaiting_reply",
                   "The request is recorded. The loop will evaluate the matching inbox reply.",
                   thread=thread, dispatchThread=thread, dueAt=due.isoformat())


def _followup(con, scope, case, truth, reply, clock, missing=()):
    """Stage one informational request using the matched sender and mail thread."""
    from .guardrails import Guardrails

    karton = case == "karton"
    kind = "karton_status_followup" if karton else "customs_followup"
    title = "Follow up on Karton’s exception" if karton else "Request the missing shipment details"
    origin = reply["parent"]
    ref = sha256(f"loop:{truth['deadline']}:{scope}:{kind}".encode()).hexdigest()[:10].upper()
    current = con.execute("""SELECT m.*, c.due_at FROM messages m JOIN chases c ON c.id=m.chase_id
                             WHERE c.id=? AND m.side='out' ORDER BY m.id DESC LIMIT 1""", (ref,)).fetchone()
    if current:
        if origin["external_id"] == current["external_id"]:
            return _action(case, kind, title, "escalated", "The follow-up reply still needs Procurement review.",
                           reply=reply, dispatchThread=ref, owner="Procurement", policy=POLICY)
        pending = _pending(case, [{**dict(current), "envelope": json.loads(current["transport"] or "{}")}], clock)
        return dict(pending, kind=kind, title=title, threadId=reply["chase_id"], replyId=reply["id"])
    context = dict(reply=reply, owner="Procurement", policy=POLICY)
    if scope == "verified":
        return _action(case, kind, title, "approval_required",
                       "Send one status check on this thread from an authorized operational mailbox. This mailbox view is read-only.",
                       **context)
    if not MESSAGE_ID.fullmatch(reply["external_id"]) or not MESSAGE_ID.fullmatch(origin["external_id"]):
        return _action(case, kind, title, "escalated", "A transport Message-ID is required to send on the existing thread.", **context)
    try:
        address = check_recipient(origin["address"])
        if address != reply["sender"].casefold():
            raise PermissionError
    except PermissionError:
        return _action(case, kind, title, "escalated",
                       "The matched address is not an authorized outbound recipient. Procurement must verify the contact.",
                       **context)
    if clock >= as_time(truth["deadline"]):
        return _action(case, kind, title, "escalated", "The launch cut-off has passed. Review the open request internally.", **context)

    labels = ", ".join(field.replace("_", " ") for field in missing)
    if karton:
        body = ("Dzień dobry,\n\nCzy mają już Państwo odpowiedź w sprawie wyjątku dla małej partii? "
                "Prosimy o potwierdzoną ilość, cenę DAP do Hamburga i możliwe okno dostawy. "
                "To wyłącznie zapytanie informacyjne.\n\nZespół Soony") if origin["language"] == "pl" else (
                "Hello,\n\nIs there an update on the small-lot exception? Please confirm the quantity, DAP Hamburg price, "
                "and delivery window. This is a request for information only.\n\nSoony launch team")
    else:
        ko = {"invoice": "상업송장", "packing_list": "포장명세서", "air_waybill": "항공운송장",
              "time_zoned_eta": "시간대가 표시된 도착 예정 시각", "receiving_slot": "하역 가능 시간"}
        if origin["language"] == "ko":
            labels_ko = ", ".join(ko[field] for field in missing)
            body = f"안녕하세요.\n\n{SHIPMENT} 운송 건을 확인 중입니다. 필요한 정보: {labels_ko}. 확인된 내용만 알려 주십시오. 이 메일은 정보 확인 요청입니다.\n\nSoony 출시 담당팀"
        else:
            body = f"Hello,\n\nFor {SHIPMENT}, please confirm the following outstanding details: {labels}. This is a request for information only.\n\nSoony launch team"
    if not Guardrails().validate_draft(body).ok:
        return _action(case, kind, title, "escalated", "The follow-up draft needs an information-only wording check.", **context)
    subject = re.sub(r"^(?:re:\s*)+", "", origin["subject"], flags=re.I)
    con.execute("""INSERT INTO chases
                   (id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)
                   VALUES (?,?,?,?,?,?,'loop draft',?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET body=excluded.body,address=excluded.address,subject=excluded.subject
                   WHERE chases.status='loop draft'""",
                (ref, origin["supplier_id"], origin["supplier"], address, origin["language"], "Re: " + subject,
                 origin["material"], origin["qty"], body, truth["deadline"]))
    return _action(case, kind, title, "queued", "Queued one information-only follow-up on the matched mail thread.",
                   dispatchThread=ref, replyTo=reply["external_id"], routine=True, **context)


def _card(con, scope, truth, options, sent, replies, clock):
    item = next((s for s in truth.get("inbound", []) if s["id"] == SHIPMENT
                 and s["material"] == CARD[1] and s["supplier"] == CARD[0]), None)
    option = next((o for o in options if o.get("shipment_id") == SHIPMENT and o.get("kind") == "inbound"), None)
    if (not item or not truth.get("shifts")
            or any(change["shipmentId"] == SHIPMENT and change["lostUnits"] > 0
                   for change in truth.get("shipmentChanges", []))):
        return []
    cutoff = min(as_time(truth["shifts"][-1][1]), as_time(truth["deadline"]))
    sent = [out for out in sent if SHIPMENT in out["body"]]
    dated = [r for r in replies if cited_reference(r["body"], item) or SHIPMENT in r["parent"]["body"]]
    common = dict(optionId=(option or {}).get("id"), policy=POLICY,
                  owner=(option or {}).get("owner", "DC-HAM site lead / Procurement"),
                  cutoff=cutoff.isoformat(), reference=SHIPMENT)
    if item["held"] or not item["quantity"]:
        return [_action("game_card", "release_review", "Review the hold before planning receipt", "escalated",
                        "The reconciled shipment is held or has no usable units.", **common)]
    if dated:
        reply = dated[-1]
        eta_reply = reply
        if reply["documents"] and not ETA_NOTICE.search(reply["body"]):
            eta_reply = next((r for r in reversed(dated) if ETA_NOTICE.search(r["body"])), reply)
        same_date = {r["body"] for r in dated if r["authored"] == eta_reply["authored"]
                     and (ETA_NOTICE.search(r["body"]) or not r["documents"])}
        dates = list(ETA.finditer(eta_reply["body"]))
        when = as_time(dates[0][1]) if len(dates) == 1 and len(same_date) == 1 else None
        if when:
            attachment_types = {kind for r in dated for kind, _ in r["documents"]}
            missing = sorted(DOCS - attachment_types)
            slot = SLOT.search(reply["body"]) or SLOT.search(eta_reply["body"])
            if not slot:
                missing.append("receiving_slot")
            hours = EXPEDITED_HANDLING_HOURS
            args = {"trials": truth["model"]["runs"]}
            baseline = counterfactual(truth, {}, **args)["editions"]
            change = {"shipment_earliest": {SHIPMENT: when.isoformat()}}
            revised = counterfactual(truth, change, **args)["editions"]
            expedited = counterfactual(truth, dict(change, handling_hours={SHIPMENT: hours}), **args)["editions"]
            impact = [{
                "edition": truth["editions"][edition].get("edition", edition),
                "before": base["p50"], "after": revised[edition]["p50"],
                "withDock": expedited[edition]["p50"],
                "pBefore": base["probability"], "pAfter": revised[edition]["probability"],
            } for edition, base in baseline.items()]
            context = dict(common, reply=reply, facts=[dates[0][0].strip(), *([slot[0]] if slot else [])],
                           eta=when.isoformat(), impact=impact)
            if when + timedelta(hours=hours) >= cutoff or clock >= cutoff:
                detail = ("The packing cut-off has passed." if clock >= cutoff else
                          "The reported arrival plus modeled dock handling reaches or crosses the packing cut-off.")
                alternatives = [o["title"] for o in options if o.get("kind") == "priority" or
                                (o.get("kind") in {"alternate", "air"} and o.get("material") == CARD[1])]
                if alternatives:
                    detail += " Planner follow-ups include " + ", ".join(alternatives) + "."
                else:
                    detail += " Review alternate stock and pack allocation."
                return [_action("game_card", "review_recovery", "Escalate to launch recovery", "escalated",
                                detail,
                                **{**context, "owner": "Procurement / DC-HAM site lead"})]
            detail = "Confirm the slot and customs release with the site lead. Forwarder fees and any booking require approval."
            if missing:
                detail += " Still needed: " + ", ".join(word.replace("_", " ") for word in missing) + "."
            actions = [_action("game_card", "approve_dock", "Queue PP-07 dock and customs review", "approval_required",
                               detail, **context)]
            if missing:
                actions.append(_followup(con, scope, "game_card", truth, reply, clock, missing))
            return actions
        if len(same_date) == 1 and not dates and (pending := CARRIER_PENDING.search(reply["body"])):
            due = min(reply["authored"] + timedelta(hours=1), cutoff)
            if clock < due:
                return [_action("game_card", "await_carrier_eta", "Wait for the airline’s ETA confirmation", "awaiting_reply",
                                "The supplier is checking with the airline. Keep dock release and customs pending until the time-zoned ETA and documents arrive.",
                                reply=reply, facts=[pending[0]], dueAt=due.isoformat(), **common)]
        actions = [_action("game_card", "verify_eta", "Verify the shipment ETA", "escalated",
                           "The matched reply did not establish one time-zoned ETA. Verify the shipment reference and any conflicting reports.",
                           reply=reply, **common)]
        if len(same_date) == 1:
            actions.append(_followup(con, scope, "game_card", truth, reply, clock, ["time_zoned_eta"]))
        return actions
    pending = _pending("game_card", sent, clock)
    if pending:
        return [dict(pending, reference=SHIPMENT, cutoff=cutoff.isoformat())]
    if not option or clock >= cutoff or scope == "verified":
        return []
    return [dict(_queue_email(con, scope, "game_card", truth, *CARD, shipment=item), **common)]


def _karton(con, scope, truth, options, sent, replies, clock):
    gap = truth.get("parts", {}).get(BOOK[1], {}).get("shortfall", 0)
    offer = next((o for o in options if o.get("kind") == "partial" and o.get("supplier_id") == BOOK[0]
                  and o.get("material") == BOOK[1]), None)
    common = dict(optionId=(offer or {}).get("id"), policy=POLICY,
                  owner=(offer or {}).get("owner", "Procurement"), unitsNeeded=gap)
    general = [r for r in replies if not SMALL_LOT.search(r["parent"]["body"])]
    small_lot = [r for r in replies if SMALL_LOT.search(r["parent"]["body"])]
    decisions = []
    if general:
        r = general[-1]
        hold = HOLD.search(r["body"]) or BOOK_QUANTITY.search(r["body"])
        same_date = {a["body"] for a in general if a["authored"] == r["authored"]}
        if hold and len(same_date) == 1:
            quantity = number(hold[1])
            prices = [p[0].strip() for p in PRICE.finditer(r["body"])][:4]
            remaining = max(0, gap - quantity)
            decisions.append(_action("karton", "review_cover" if not remaining else "review_art_book_gap",
                                     "Queue art-book purchase review" if not remaining else "Review uncovered art-book quantity",
                                     "approval_required",
                                     "Verify written delivered terms, pickup and hold expiry. PO and dock release remain subject to PP-07.",
                                     reply=r, facts=[hold[0], *prices], reportedUnits=quantity, unitsUncovered=remaining,
                                     materialEstimate=(offer or {}).get("price"), **common))
        else:
            decisions.append(_action("karton", "verify_offer", "Verify the art-book offer", "escalated",
                                     "The matched reply did not establish a single available quantity. Review the correspondence before changing the purchase plan.",
                                     reply=r, **common))
    if small_lot:
        r = small_lot[-1]
        minimum = MOQ.search(r["body"])
        same_date = {a["body"] for a in small_lot if a["authored"] == r["authored"]}
        if len(same_date) == 1:
            units = number(minimum[1]) if minimum else None
            asks = re.search(r"\b(\d{1,3})\s*(?:[–—-]|to|do)\s*(\d{1,3})\b", r["parent"]["body"], re.I)
            max_requested = int(asks[2]) if asks else None
            detail = f"Karton reported a standard minimum of {units:,} units." if units else "Karton replied to the small-lot request."
            if max_requested is not None and units is not None and units > max_requested:
                detail += f" The request for {asks[1]}–{asks[2]} units is below it."
            facts = [minimum[0]] if minimum else []
            due_at = None
            if denied := LOT_DENIAL.search(r["body"]):
                kind, title, status = "review_minimum", "Review alternatives for the declined small lot", "escalated"
                detail += " Karton declined the request. Review alternatives or consolidate demand."
                facts.append(denied[0])
            elif agreed := HOLD.search(r["body"]) or BOOK_QUANTITY.search(r["body"]):
                kind, title, status = "review_exception_terms", "Review the small-lot terms", "approval_required"
                detail += f" Karton reports {number(agreed[1]):,} units. Verify delivered price and timing before a PO decision."
                facts.append(agreed[0])
            elif pending := LOT_PENDING.search(r["body"]):
                kind, title, status = "await_small_lot_exception", "Wait for Karton’s small-lot exception decision", "awaiting_reply"
                detail += " Karton is checking a one-off exception. Wait for confirmed quantity, delivered price and delivery window."
                facts.append(pending[0])
                due_at = min(r["authored"] + timedelta(hours=2), as_time(truth["deadline"]))
                if clock >= due_at:
                    decisions.append(_followup(con, scope, "karton", truth, r, clock))
                    kind, title = "small_lot_exception_overdue", "Karton’s exception is still pending"
            else:
                kind, title, status = "verify_small_lot", "Review the terms of Karton’s small-lot reply", "escalated"
                detail += " Verify whether the supplier will make an exception before changing the plan."
            decisions.append(_action("karton", kind, title, status, detail, reply=r, facts=facts,
                                     dueAt=due_at.isoformat() if due_at else None, **common))
        else:
            decisions.append(_action("karton", "verify_small_lot", "Clarify Karton’s small-lot response", "escalated",
                                     "The matched small-lot reply is recorded. Procurement should check its terms before any further contact.",
                                     reply=r, **common))
    if not small_lot:
        if pending := _pending("karton", [out for out in sent if SMALL_LOT.search(out["body"])], clock):
            decisions.append(pending)
    if not decisions:
        if pending := _pending("karton", sent, clock):
            return [pending]
        if not gap or not offer or scope == "verified" or clock >= as_time(truth["deadline"]):
            return []
        return [_queue_email(con, scope, "karton", truth, *BOOK)]
    return decisions


def _last_inbound(con, pair):
    return con.execute("""SELECT COALESCE(max(m.id),0) FROM messages m JOIN chases c ON c.id=m.chase_id
                          WHERE c.supplier_id=? AND c.material=? AND m.side='in'""", pair).fetchone()[0]


def _write(con, scope, pair, items, clock):
    from . import activity

    case = CASES[pair]
    ids = []
    reviewed_through = _last_inbound(con, pair)
    for item in items:
        key = [scope, case, item["kind"], item.get("threadId"), item.get("replyId")]
        action_id = sha256(json.dumps(key).encode()).hexdigest()[:16]
        previous = con.execute("SELECT payload FROM supplier_loop_actions WHERE id=?", (action_id,)).fetchone()
        item.update(id=action_id, scope=scope, reviewedThrough=reviewed_through,
                    queuedAt=json.loads(previous[0])["queuedAt"] if previous else clock.isoformat())
        con.execute("""INSERT INTO supplier_loop_actions VALUES (?,?,?,1,?)
                       ON CONFLICT(id) DO UPDATE SET active=1,payload=excluded.payload
                       WHERE supplier_loop_actions.active=0 OR supplier_loop_actions.payload!=excluded.payload""",
                    (action_id, scope, case, json.dumps(item, ensure_ascii=False)))
        if previous is None:
            activity(con, "Supplier Loop", item["title"], "warning" if item["status"] == "escalated" else "analysis")
        ids.append(action_id)
    placeholders = ",".join("?" for _ in ids)
    con.execute(f"UPDATE supplier_loop_actions SET active=0 WHERE scope=? AND case_name=? AND active=1"
                + (f" AND id NOT IN ({placeholders})" if ids else ""), (scope, case, *ids))


def advance(con, truth, options, *, scope, clock=None, dispatch=True):
    """Evaluate durable messages on a worker cycle. The verified mailbox cannot dispatch."""
    from . import send
    from .autosend import enabled

    if not truth:
        return
    clock = clock or datetime.now(timezone.utc)
    with con:
        con.execute("BEGIN IMMEDIATE")
        for pair, evaluate in ((CARD, _card), (BOOK, _karton)):
            sent, replies = _correspondence(con, *pair, scope)
            _write(con, scope, pair, evaluate(con, scope, truth, options, sent, replies, clock), clock)
    if dispatch and (scope == "demo" or (scope == "live" and enabled())):
        for item in view(con, scope):
            if item["status"] == "queued" and item.get("dispatchThread") and (scope == "demo" or item.get("routine")):
                try:
                    send(con, item["dispatchThread"], demo=scope == "demo", managed=True, auto=True)
                except (ValueError, PermissionError):
                    # A claim or new reply may have won the race. Transport attempts remain in the outbox.
                    continue


def view(con, scope):
    """Read-only current decisions, joined to actual transport outcomes."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='supplier_loop_actions'").fetchone():
        return []
    actions = [json.loads(row[0]) for row in con.execute(
        "SELECT payload FROM supplier_loop_actions WHERE scope=? AND active=1 ORDER BY case_name, rowid", (scope,))]
    for item in actions:
        dispatch_thread, origin = item.get("dispatchThread"), item.get("originMessageId")
        if not dispatch_thread and not origin:
            continue
        row = (con.execute("""SELECT external_id,time,transport FROM messages WHERE side='out' AND chase_id=?
                              ORDER BY id DESC LIMIT 1""", (dispatch_thread,)).fetchone() if dispatch_thread else
               con.execute("SELECT external_id,time,transport FROM messages WHERE side='out' AND external_id=?",
                           (origin,)).fetchone())
        if not row:
            continue
        meta = json.loads(row["transport"] or "{}")
        item["transport"] = {"mode": meta.get("mode"), "status": meta.get("status"),
                             "messageId": row["external_id"], "time": row["time"]}
        if item["status"] == "queued":
            item["status"] = "awaiting_reply" if meta.get("status") in ACCEPTED else "escalated"
    order = {"escalated": 0, "approval_required": 1, "queued": 2, "awaiting_reply": 3}
    return sorted(actions, key=lambda item: order[item["status"]])


def eligible_draft(con, chase_id, scope, pair):
    latest = _last_inbound(con, pair)
    return next((item for item in view(con, scope) if item["status"] == "queued"
                 and item.get("dispatchThread") == chase_id and item.get("reviewedThrough") == latest), None)


def sample_card_reply(truth, scenario):
    if scenario not in {"on-time", "delayed", "complete"} or not truth.get("shifts"):
        raise ValueError("Choose an on-time, complete, or delayed demo reply")
    cutoff = as_time(truth["shifts"][-1][1])
    when = cutoff + (timedelta(hours=3) if scenario == "delayed" else -timedelta(hours=7))
    slot = "\nReceiving slot: confirmed at 15:00 CET by the simulated carrier." if scenario == "complete" else ""
    return f"Shipment {SHIPMENT}.\nRevised ETA: {when.isoformat(timespec='minutes')}{slot}"
