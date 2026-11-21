"""Persistent decisions for the launch-critical card and art-book threads."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re

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
SMALL_LOT = re.compile(r"\b(?:small[- ]lot|MOQ|minimum|minimaln\w+)\b", re.I)
LOT_PENDING = re.compile(r"\b(?:sprawdz\w*[^\n.]{0,90}|wróc\w* z potwierdzon\w*[^\n.]{0,90}|(?:checking|check)\s+(?:internally|whether|if)[^\n.]{0,90}|(?:will|shall)\s+(?:get back|confirm)[^\n.]{0,90})", re.I)
LOT_DENIAL = re.compile(r"\b(?:cannot|can’t|can't|can not|unable to)\s+(?:offer|accept|supply|make an exception)[^\n.]{0,80}|\bnie (?:możemy|będziemy mogli)\s+(?:zaoferować|dostarczyć|zrealizować)[^\n.]{0,80}", re.I)
ACCEPTED = {"dry_run", "smtp_accepted", "gmail_sent"}
DOCS = {"invoice", "packing_list", "air_waybill"}


def managed(supplier, material):
    return (supplier, material) in CASES


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


def _correspondence(con, supplier, material, scope):
    mode = {"verified": "gmail", "demo": "dry_run", "live": "smtp"}[scope]
    out = []
    inbound = []
    sent = {}
    for row in con.execute("""
        SELECT m.*, c.subject, c.qty, c.due_at
        FROM messages m JOIN chases c ON c.id=m.chase_id
        WHERE c.supplier_id=? AND c.material=? ORDER BY m.id
    """, (supplier, material)):
        envelope = json.loads(row["transport"] or "{}")
        item = {**dict(row), "envelope": envelope}
        if row["side"] == "out" and envelope.get("mode") == mode:
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
            replies.append({**reply, "authored": authored, "parent": parent})
    replies.sort(key=lambda r: (r["authored"], r["id"]))
    unique = {}
    for reply in replies:
        key = (reply["parent"]["external_id"], " ".join(reply["body"].split()).casefold())
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
                   thread=ref, dispatchThread=ref)


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


def _card(con, scope, truth, options, sent, replies, clock):
    item = next((s for s in truth.get("inbound", []) if s["id"] == SHIPMENT
                 and s["material"] == CARD[1] and s["supplier"] == CARD[0]), None)
    option = next((o for o in options if o.get("shipment_id") == SHIPMENT and o.get("kind") == "inbound"), None)
    if not item or not truth.get("shifts"):
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
        same_date = {r["body"] for r in dated if r["authored"] == reply["authored"]}
        dates = list(ETA.finditer(reply["body"]))
        when = as_time(dates[0][1]) if len(dates) == 1 and len(same_date) == 1 else None
        if when:
            plan = json.loads(reply["parsed"] or "{}")
            attachment_types = {a.get("kind") for a in plan.get("attachments", []) if not a.get("needs_review")}
            missing = sorted(DOCS - attachment_types)
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
            context = dict(common, reply=reply, facts=[dates[0][0].strip()], eta=when.isoformat(), impact=impact)
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
            return [_action("game_card", "approve_dock", "Queue PP-07 dock and customs review", "approval_required",
                            detail, **context)]
        return [_action("game_card", "verify_eta", "Verify the shipment ETA", "escalated",
                        "The matched reply did not establish one time-zoned ETA. Verify the shipment reference and any conflicting reports.",
                        reply=reply, **common)]
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
                    kind, title, status = "check_small_lot_exception", "Check the outstanding exception internally", "escalated"
                    detail += " Procurement should check the existing thread before further outreach."
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


def _write(con, scope, case, items, clock):
    from . import activity

    ids = []
    for item in items:
        key = [scope, case, item["kind"], item.get("threadId"), item.get("replyId")]
        action_id = sha256(json.dumps(key).encode()).hexdigest()[:16]
        previous = con.execute("SELECT payload FROM supplier_loop_actions WHERE id=?", (action_id,)).fetchone()
        item.update(id=action_id, scope=scope, queuedAt=json.loads(previous[0])["queuedAt"] if previous else clock.isoformat())
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

    if not truth:
        return
    clock = clock or datetime.now(timezone.utc)
    with con:
        con.execute("BEGIN IMMEDIATE")
        for pair, evaluate in ((CARD, _card), (BOOK, _karton)):
            sent, replies = _correspondence(con, *pair, scope)
            _write(con, scope, CASES[pair], evaluate(con, scope, truth, options, sent, replies, clock), clock)
    if scope == "demo" and dispatch:
        for item in view(con, scope):
            if item["status"] == "queued" and item.get("dispatchThread"):
                try:
                    send(con, item["dispatchThread"], demo=True, managed=True)
                except ValueError:
                    # The claim may already belong to another worker. Never reset it.
                    if con.execute("SELECT status FROM chases WHERE id=?", (item["dispatchThread"],)).fetchone()[0] == "loop draft":
                        raise


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
        row = con.execute("""SELECT external_id,time,transport FROM messages WHERE side='out' AND
                              (external_id=? OR chase_id=?) ORDER BY id DESC LIMIT 1""",
                          (origin, dispatch_thread)).fetchone()
        if not row:
            continue
        meta = json.loads(row["transport"] or "{}")
        item["transport"] = {"mode": meta.get("mode"), "status": meta.get("status"),
                             "messageId": row["external_id"], "time": row["time"]}
        if item["status"] == "queued":
            item["status"] = "awaiting_reply" if meta.get("status") in ACCEPTED else "escalated"
    order = {"escalated": 0, "approval_required": 1, "queued": 2, "awaiting_reply": 3}
    return sorted(actions, key=lambda item: order[item["status"]])


def eligible_draft(con, chase_id, scope):
    return any(item["status"] == "queued" and item.get("dispatchThread") == chase_id for item in view(con, scope))


def sample_card_reply(truth, scenario):
    if scenario not in {"on-time", "delayed"} or not truth.get("shifts"):
        raise ValueError("Choose an on-time or delayed demo reply")
    cutoff = as_time(truth["shifts"][-1][1])
    when = cutoff + (timedelta(hours=3) if scenario == "delayed" else -timedelta(hours=7))
    return f"Shipment {SHIPMENT}.\nRevised ETA: {when.isoformat(timespec='minutes')}"
