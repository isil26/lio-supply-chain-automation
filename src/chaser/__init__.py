"""Persistent, asynchronous supplier follow-ups with SMTP and IMAP tools."""
import email
import hashlib
import imaplib
import json
import os
import re
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.policy import default
from email.utils import format_datetime, make_msgid, parseaddr, parsedate_to_datetime

from . import supplier_loop



def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rows(con, table):
    return [dict(row) for row in con.execute(f'SELECT * FROM "{table}"')]

LANGUAGE = {
    "en": ("Launch stock and delivery confirmation",
           "Hello {name},\n\nCan you confirm whether {quantity:,} units of {part} are available for our Hamburg cut-off ({deadline} CET)? Please reply with available quantity, earliest collection time, carrier reference and delivered price, if applicable. This is a request for information only.\n\nSoony launch team"),
    "pl": ("Potwierdzenie dostępności i dostawy",
           "Dzień dobry,\n\nCzy mogą Państwo potwierdzić dostępność {quantity:,} szt. części {part} przed terminem dostawy do Hamburga ({deadline} CET)? Prosimy podać dostępną ilość, najwcześniejszy termin odbioru, numer przewozowy i ewentualną cenę z dostawą. Jest to wyłącznie zapytanie.\n\nZespół Soony"),
    "ko": ("출시 재고 및 납품 일정 확인 요청",
           "{name}님, 안녕하세요.\n\n함부르크 납품 마감({deadline} CET)까지 부품 {part} {quantity:,}개를 공급할 수 있는지 확인 부탁드립니다. 공급 가능 수량, 가장 빠른 픽업 시간, 운송장 번호 및 해당 시 운임 포함 견적을 알려 주시기 바랍니다. 이 메일은 정보 요청이며 발주가 아닙니다.\n\nSoony 출시 담당팀"),
    "zh": ("上市库存和交付时间确认",
           "{name}，您好。\n\n请确认在汉堡交付截止时间（{deadline} CET）之前，能否提供 {quantity:,} 件 {part}。请告知可供数量、最早提货时间、运单号和适用的到货报价。本邮件仅为询价和信息确认。\n\nSoony 上市团队"),
}


# T67: ask the shipper for customs documents so an air lot can be cleared before it lands.
DOCUMENTS = {
    "en": ("Customs documents for {ref}",
           "Hello {name},\n\nShipment {ref} ({units:,} units of {part}) is critical for our Hamburg launch cut-off ({deadline} CET). So that customs can be cleared before it lands, please send the commercial invoice, packing list and air waybill for {ref} today, and confirm the flight number and expected arrival time. This is a request for information only.\n\nSoony launch team"),
    "pl": ("Dokumenty celne dla {ref}",
           "Dzień dobry,\n\nPrzesyłka {ref} ({units:,} szt. części {part}) jest kluczowa dla terminu w Hamburgu ({deadline} CET). Aby odprawa celna nastąpiła przed przylotem, prosimy jeszcze dziś przesłać fakturę handlową, listę pakunkową i lotniczy list przewozowy dla {ref} oraz potwierdzić numer lotu i przewidywaną godzinę przylotu. Jest to wyłącznie zapytanie.\n\nZespół Soony"),
    "ko": ("{ref} 통관 서류 요청",
           "{name}님, 안녕하세요.\n\n운송 건 {ref}(부품 {part} {units:,}개)는 함부르크 출시 마감({deadline} CET)에 꼭 필요한 물량입니다. 도착 전에 통관을 마칠 수 있도록 오늘 중으로 {ref}의 상업송장, 포장명세서 및 항공화물운송장을 보내 주시고, 항공편 번호와 예상 도착 시간을 확인해 주시기 바랍니다. 이 메일은 정보 요청이며 발주가 아닙니다.\n\nSoony 출시 담당팀"),
    "zh": ("{ref} 清关文件",
           "{name}，您好。\n\n货运 {ref}（{units:,} 件 {part}）对我们的汉堡上市截止时间（{deadline} CET）至关重要。为在到达前完成清关，请于今天发送 {ref} 的商业发票、装箱单和航空运单，并确认航班号和预计到达时间。本邮件仅为信息确认，并非订单。\n\nSoony 上市团队"),
}


def schema(con):
    con.executescript("""
       CREATE TABLE IF NOT EXISTS chases (
           id TEXT PRIMARY KEY, supplier_id TEXT NOT NULL, supplier TEXT NOT NULL,
           address TEXT NOT NULL, language TEXT NOT NULL, subject TEXT NOT NULL, status TEXT NOT NULL,
           material TEXT NOT NULL, qty INTEGER NOT NULL, body TEXT NOT NULL, deadline TEXT NOT NULL,
           due_at TEXT, message_id TEXT, parent_thread_id TEXT, based_on_reply_id INTEGER
       );
       CREATE TABLE IF NOT EXISTS messages (
           id INTEGER PRIMARY KEY, chase_id TEXT REFERENCES chases(id), external_id TEXT UNIQUE,
           side TEXT NOT NULL, sender TEXT NOT NULL, body TEXT NOT NULL, time TEXT NOT NULL,
           parsed TEXT, transport TEXT
       );
       CREATE TABLE IF NOT EXISTS activity (
           id INTEGER PRIMARY KEY, time TEXT NOT NULL, agent TEXT NOT NULL, action TEXT NOT NULL, type TEXT NOT NULL
       );
       CREATE TABLE IF NOT EXISTS chaser_deadline_handoffs (
           chase_id TEXT PRIMARY KEY REFERENCES chases(id), deadline TEXT, detail TEXT NOT NULL
       );
    """)

    if "transport" not in {row[1] for row in con.execute("PRAGMA table_info(messages)")}:
        con.execute("ALTER TABLE messages ADD COLUMN transport TEXT")
    columns = {row[1] for row in con.execute("PRAGMA table_info(chases)")}
    for name, kind in (("parent_thread_id", "TEXT"), ("based_on_reply_id", "INTEGER")):
        if name not in columns:
            con.execute(f"ALTER TABLE chases ADD COLUMN {name} {kind}")
    supplier_loop.schema(con)


def activity(con, agent, action, kind="analysis"):
    con.execute("INSERT INTO activity(time,agent,action,type) VALUES(?,?,?,?)", (now(), agent, action, kind))


def draft(con, truth, options=None):
    schema(con)
    due = datetime.fromisoformat(truth["deadline"]).strftime("%d %b %H:%M")
    created = 0
    profiles = {row["supplier_id"]: row for row in rows(con, "suppliers")}
    with con:
        for part in truth["parts"].values():
            if not part["shortfall"]:
                continue
            if any(change["material"] == part["material"] for source in ("shipmentChanges", "portalShortfalls")
                   for change in truth.get(source, [])):
                continue  # The recovery loop owns targeted outreach for this disruption.
            candidates = {row["supplier_id"] for row in part["suppliers"] if row["supplier"].get("status") == "active"}
            candidates.update(event["supplier"] for event in truth["issues"]
                              if event["material"] == part["material"] and event.get("supplier"))
            for supplier_id in sorted(candidates):
                if supplier_loop.managed(supplier_id, part["material"]):
                    continue
                supplier = profiles.get(supplier_id, {})
                if not supplier.get("contact_email"):
                    continue
                ref = hashlib.sha256(f'{truth["deadline"]}:{supplier_id}:{part["material"]}'.encode()).hexdigest()[:10].upper()
                language = supplier.get("preferred_language", "en")
                subject, template = LANGUAGE.get(language, LANGUAGE["en"])
                quantity = part["shortfall"]
                body = template.format(name=supplier["contact_name"] or supplier["name"], part=part["material"],
                                       quantity=quantity, deadline=due)
                result = con.execute("""INSERT INTO chases
                    (id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET qty=excluded.qty,body=excluded.body
                    WHERE chases.status='draft' AND chases.qty != excluded.qty""",
                    (ref, supplier_id, supplier["name"], supplier["contact_email"], language, f"[SOONY-{ref}] {subject}",
                     "draft", part["material"], quantity, body, truth["deadline"]))
                if result.rowcount:
                    activity(con, "Supplier Chaser", f'{supplier["name"]}: prepared {language} follow-up for {part["material"]} ({quantity:,} units).')
                    created += 1
    return created + draft_documents(con, truth, options or ())


def draft_documents(con, truth, options):
    """Draft a customs-documents request to the shipper of each expedited air lot (T67).

    The thread quantity is the component gap, matching the send endpoint's staleness check;
    the shipment's own units appear in the body.
    """
    due = datetime.fromisoformat(truth["deadline"]).strftime("%d %b %H:%M")
    profiles = {row["supplier_id"]: row for row in rows(con, "suppliers")}
    inbound = {item["id"]: item for item in truth["inbound"]}
    created = 0
    with con:
        for option in options:
            item = inbound.get(option.get("shipment_id"))
            if option.get("kind") != "inbound" or not item or item["mode"] != "air":
                continue
            if supplier_loop.managed(item["supplier"], item["material"]):
                continue
            supplier = profiles.get(item.get("supplier"), {})
            gap = truth["parts"].get(item["material"], {}).get("shortfall", 0)
            if not supplier.get("contact_email") or not gap:
                continue
            shipment = item.get("reference") or item["id"]
            ref = hashlib.sha256(f'{truth["deadline"]}:{item["supplier"]}:{item["id"]}:documents'.encode()).hexdigest()[:10].upper()
            language = supplier.get("preferred_language", "en")
            subject, template = DOCUMENTS.get(language, DOCUMENTS["en"])
            body = template.format(name=supplier["contact_name"] or supplier["name"], ref=shipment,
                                   units=int(item["quantity"]), part=item["material"], deadline=due)
            result = con.execute("""INSERT INTO chases
                (id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)
                VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET qty=excluded.qty,body=excluded.body
                WHERE chases.status='draft' AND chases.qty != excluded.qty""",
                (ref, item["supplier"], supplier["name"], supplier["contact_email"], language,
                 f"[SOONY-{ref}] {subject.format(ref=shipment)}", "draft", item["material"], gap, body, truth["deadline"]))
            if result.rowcount:
                activity(con, "Supplier Chaser", f'{supplier["name"]}: prepared {language} customs-documents request for {shipment}.')
                created += 1
    return created


def send(con, chase_id, demo=False, *, managed=False, auto=False):
    from . import deadlines

    schema(con)
    if not demo:
        from .mailenv import load_team_mail_env
        load_team_mail_env()
    sender = os.getenv("CHASER_SENDER")
    host = os.getenv("CHASER_SMTP_HOST")
    message = EmailMessage()
    with con:
        con.execute("BEGIN IMMEDIATE")
        chase = con.execute("SELECT * FROM chases WHERE id=?", (chase_id,)).fetchone()
        if not chase:
            raise ValueError("Only a current draft can be sent")
        if not demo:
            if reason := deadlines.record_if_expired(con, chase, datetime.now(timezone.utc), deadlines.current_plan(con)):
                # Save the handoff before reporting the rejected send to the caller.
                con.commit()
                raise deadlines.DeadlineHandoff(reason)
        if not sender:
            raise ValueError("CHASER_SENDER is required")
        if not demo and (not host or os.getenv("CHASER_REAL_SMTP") != "1"):
            raise ValueError("Live sending requires CHASER_REAL_SMTP=1 and CHASER_SMTP_HOST")
        message["From"] = sender
        from . import deals, mail_plan
        decision_mail = chase["status"] == "draft" and deals.check_draft(con, chase_id)
        action = None
        if chase["status"] in ("promise draft","quote draft"):
            from . import promise_watch, quote_followup
            owner = quote_followup if chase["status"] == "quote draft" else promise_watch
            if demo or not auto or not owner.current(con, chase, datetime.now(timezone.utc)):
                raise ValueError("The supplier promise is no longer due for follow-up")
        elif chase["status"] == "recovery draft":
            from .recovery import eligible_draft

            action = eligible_draft(con, chase_id) if auto and not demo else None
            if not action:
                raise ValueError("Recovery request changed or passed its send window")
        elif not decision_mail and supplier_loop.managed(chase["supplier_id"], chase["material"]):
            if managed and chase["status"] == "loop draft":
                action = supplier_loop.eligible_draft(con, chase_id, "demo" if demo else "live",
                                                      (chase["supplier_id"], chase["material"]))
            if not action:
                raise ValueError("This case requires a current supplier-loop draft")
        elif chase["status"] != "draft":
            raise ValueError("Only a current draft can be sent")
        if chase["status"] not in ("promise draft","quote draft") and not action and not decision_mail and (auto or chase["based_on_reply_id"] is not None):
            mail_plan.check_draft(con, chase, simulated=demo)
        if action or auto or decision_mail:
            from .guardrails import Guardrails
            if not Guardrails().validate_draft(chase["body"]).ok:
                raise ValueError("Automatic request failed the information-only check")
        if auto and not demo:
            from .autosend import cooldown_minutes, duplicate_body, recent_cases
            address = chase["address"].strip().lower()
            case = (address, chase["material"])
            if duplicate_body(con, address, chase["body"]) or case in recent_cases(
                con, cooldown_minutes(), datetime.now(timezone.utc)
            ):
                raise ValueError("Automatic request is on cooldown or was already sent")
        message_id = make_msgid(domain=parseaddr(sender)[1].split("@")[-1])
        if not demo:
            from .allowlist import check_recipient
            check_recipient(chase["address"])
        message["To"], message["Subject"], message["Message-ID"] = chase["address"], chase["subject"], message_id
        message["Date"] = format_datetime(datetime.now(timezone.utc))
        if action and action.get("replyTo"):
            message["In-Reply-To"] = action["replyTo"]
            message["References"] = f'{action["originMessageId"]} {action["replyTo"]}'
        elif chase["based_on_reply_id"] is not None:
            reply = con.execute("""SELECT external_id,transport FROM messages WHERE id=? AND side='in'""",
                                (chase["based_on_reply_id"],)).fetchone()
            if reply and reply["external_id"]:
                message["In-Reply-To"] = reply["external_id"]
                parent = (json.loads(reply["transport"] or "{}").get("inReplyTo") or "").strip()
                message["References"] = " ".join(filter(None, (parent, reply["external_id"])))
        if not demo:
            message["X-Soony-Chaser"] = "1"
        message.set_content(chase["body"])
        envelope = {"from": str(message["From"]), "to": chase["address"], "subject": chase["subject"],
                    "messageId": message_id, "inReplyTo": str(message.get("In-Reply-To", "")),
                    "mode": "dry_run" if demo else "smtp", "status": "attempting"}
        recorded_at = now()
        con.execute("""INSERT INTO messages(chase_id,external_id,side,sender,body,time,transport)
                       VALUES(?,?,?,?,?,?,?)""",
                    (chase_id, message_id, "out", sender, chase["body"], recorded_at, json.dumps(envelope)))
        con.execute("UPDATE chases SET status='sending',message_id=?,due_at=? WHERE id=?",
                    (message_id, (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds"), chase_id))
    try:
        if not demo:
            context = ssl.create_default_context()
            port = int(os.getenv("CHASER_SMTP_PORT", "587"))
            transport = (smtplib.SMTP_SSL(host, port, timeout=20, context=context) if port == 465
                         else smtplib.SMTP(host, port, timeout=20))
            with transport as client:
                if port != 465:
                    client.starttls(context=context)
                authenticate(client)
                if chase["status"] in ("promise draft","quote draft"):
                    deadlines.expire_transport_claim(con, chase_id, message_id, promise=True, quote=chase["status"]=="quote draft")
                else:
                    deadlines.expire_transport_claim(con, chase_id, message_id)
                rejected = client.send_message(message)
                if rejected:
                    raise smtplib.SMTPRecipientsRefused(rejected)
    except (OSError, smtplib.SMTPException) as exc:
        # SMTP acceptance can be ambiguous after a disconnect. Keep the message ID for reconciliation.
        rejected = isinstance(exc, (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused,
                                    smtplib.SMTPAuthenticationError, smtplib.SMTPDataError))
        status = "failed" if rejected else "delivery_uncertain"
        with con:
            con.execute("UPDATE chases SET status=? WHERE id=? AND status='sending'",
                        ("send failed" if rejected else "delivery uncertain", chase_id))
            con.execute("UPDATE messages SET transport=? WHERE external_id=?",
                        (json.dumps(dict(envelope, status=status)), message_id))
            explanation = "SMTP rejected the message." if rejected else "Delivery uncertain. Verify the outbox before retry."
            activity(con, "Supplier Chaser", f'{chase["supplier"]}: {explanation}', "warning")
        raise ValueError(explanation) from exc
    with con:
        con.execute("UPDATE chases SET status='awaiting reply' WHERE id=? AND status='sending'", (chase_id,))
        label = "Supplier Chaser (demo)" if demo else sender
        completed = "dry_run" if demo else "smtp_accepted"
        con.execute("UPDATE messages SET sender=?, time=?, transport=? WHERE external_id=?",
                    (label, now(), json.dumps(dict(envelope, status=completed)), message_id))
        activity(con, "Supplier Chaser", f'{chase["supplier"]}: ' + ("sent via demo transport." if demo else "accepted by SMTP. Awaiting reply."), "sent")


def authenticate(client):
    username = os.getenv("CHASER_SMTP_USERNAME")
    if username:
        client.login(username, os.getenv("CHASER_SMTP_PASSWORD", ""))


def parse_reply(body):
    result = {}
    qty = re.search(r"(?:qty|quantity|available|ilość|수량|数量)\s*[:：=]\s*(\d[\d, ]*)",
                    body, re.I)
    date = re.search(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2})?\b", body)
    price = re.search(r"(EUR|USD|CNY|INR)\s+(\d+(?:\.\d+)?)", body, re.I)
    tracking = re.search(r"\b(?:\d{3}-\d{8}|[A-Z]{4}\d{7})\b", body)
    for name, hit in (("quantity", qty), ("stated_time", date), ("cost", price), ("tracking", tracking)):
        if hit:
            result[name] = {"value": hit.group(), "quote": hit.group()}
    return result


def receive(con, message, *, simulated=False, matched_thread_id=None):
    schema(con)
    sender = parseaddr(message.get("From", ""))[1].casefold()
    parent = (message.get("In-Reply-To", "") or "").strip()
    subject = message.get("Subject", "")
    ref = re.search(r"\[SOONY-([A-F0-9]+)\]", subject)
    parent_chase = con.execute("""SELECT c.* FROM chases c JOIN messages m ON m.chase_id=c.id
                   WHERE m.external_id=? AND m.side='out' AND lower(c.address)=?""", (parent, sender)).fetchone()
    chase = parent_chase or con.execute("""SELECT * FROM chases WHERE lower(address)=? AND
               (message_id=? OR id=?) AND status NOT IN ('draft')""",
                        (sender, parent, matched_thread_id or (ref[1] if ref else ""))).fetchone()
    if not chase:
        return False
    if supplier_loop.managed(chase["supplier_id"], chase["material"]) and not parent_chase:
        return False
    sent = con.execute("SELECT sender,transport FROM messages WHERE external_id=? AND chase_id=? AND side='out'",
                       (parent if parent_chase else chase["message_id"], chase["id"])).fetchone()
    if sent:
        sent_transport = json.loads(sent["transport"] or "{}")
        dry_run = sent_transport.get("mode") == "dry_run" or sent["sender"].endswith("(demo)")
        if simulated != dry_run:
            return False
    elif simulated:
        return False
    part = message.get_body(preferencelist=("plain",))
    if not part:
        return False
    # Exclude quoted previous mail so a request in the original isn't imported as a claim.
    body = "\n".join(line for line in part.get_content().splitlines() if not line.lstrip().startswith(">")).strip()[:12000]
    if not body:
        return False
    message_id = str(message.get("Message-ID") or hashlib.sha256(message.as_bytes()).hexdigest())
    envelope = {"from": str(message.get("From") or sender), "to": str(message.get("To") or ""),
                "subject": str(subject), "messageId": message_id, "inReplyTo": parent,
                "mode": "simulated" if simulated else "inbox", "status": "received"}
    try:
        date = parsedate_to_datetime(str(message["Date"] or ""))
        if date.tzinfo:
            envelope["authoredAt"] = date.isoformat()
    except (TypeError, ValueError, AttributeError):
        pass
    with con:
        inserted = con.execute("""INSERT OR IGNORE INTO messages(chase_id,external_id,side,sender,body,time,transport)
            VALUES(?,?,?,?,?,?,?)""", (chase["id"], message_id, "in", sender, body, datetime.now(timezone.utc).isoformat(),
                                        json.dumps(envelope))).rowcount
        if inserted:
            from src.ingest.store import get_state
            from .reply_plan import plan_reply

            fields = parse_reply(body)
            try:
                from .followup import attachment_evidence
                if attachments := attachment_evidence(message):
                    fields["attachments"] = attachments
            except Exception:  # attachment reading must never block a reply
                pass
            plan = plan_reply(get_state(con, "truth", {}), chase, body,
                              options=get_state(con, "options", []), simulated=simulated)
            plan["id"] = hashlib.sha256(f'reply:{chase["id"]}:{message_id}'.encode()).hexdigest()[:16]
            from .mail_plan import classify
            workflow = classify(body)
            if workflow:
                fields["mail_workflow"] = workflow
                if not (plan.get("editions") or plan.get("offerId") or plan.get("disposition")):
                    plan.update(nextAction=workflow["nextAction"], evidence=[workflow["evidence"]])
            fields["reply_plan"] = plan
            con.execute("UPDATE messages SET parsed=? WHERE external_id=?",
                        (json.dumps(fields, ensure_ascii=False), str(message_id)))
            con.execute("UPDATE chases SET status='reply to verify' WHERE id=?", (chase["id"],))
            activity(con, "Supplier Chaser", f'{chase["supplier"]}: matched reply. {fields["reply_plan"]["nextAction"]}')
    return bool(inserted)


def poll(con):
    from .mailenv import load_team_mail_env
    load_team_mail_env()
    host, username = os.getenv("SOONY_IMAP_HOST"), os.getenv("SOONY_IMAP_USER")
    if not host or not username:
        return 0
    count = 0
    with imaplib.IMAP4_SSL(host, int(os.getenv("SOONY_IMAP_PORT", "993")), ssl_context=ssl.create_default_context(), timeout=20) as inbox:
        inbox.login(username, os.getenv("SOONY_IMAP_PASSWORD", ""))
        if inbox.select("INBOX", readonly=True)[0] != "OK":
            raise imaplib.IMAP4.error("Cannot open the supplier inbox read-only")
        status, hits = inbox.uid("search", None, '(HEADER Subject "SOONY-")')
        if status != "OK":
            raise imaplib.IMAP4.error("Cannot search for supplier replies")
        if not hits:
            return 0
        for uid in (hits[0] or b"").split()[-120:]:
            status, payload = inbox.uid("fetch", uid, "(BODY.PEEK[])")
            if status != "OK":
                continue
            item = next((entry[1] for entry in payload if isinstance(entry, tuple)), None)
            if item and receive(con, email.message_from_bytes(item, policy=default)):
                count += 1
    return count


def reconcile_reply_constraints(con):
    """Revisit previously matched replies when the launch-constraint parser expands."""
    from .reply_plan import supply_constraint

    pending = con.execute("""
        SELECT id,body,parsed FROM messages WHERE side='in'
          AND json_extract(transport, '$.mode')='inbox'
          AND json_extract(parsed, '$.reply_plan.disposition') IS NULL
    """).fetchall()
    with con:
        for row in pending:
            constraint = supply_constraint(row["body"])
            if constraint:
                fields = json.loads(row["parsed"] or "{}")
                plan = fields.setdefault("reply_plan", {"id": f'mail-{row["id"]}', "simulated": False})
                plan.update(constraint)
                con.execute("UPDATE messages SET parsed=? WHERE id=?", (json.dumps(fields, ensure_ascii=False), row["id"]))
                activity(con, "Supplier Chaser", constraint["nextAction"])


def live_reply_constraints(con):
    """Select the latest observed reply for each contacted supplier and component."""
    latest = {}
    for row in con.execute("""
        SELECT c.supplier_id,c.material,m.parsed,m.id AS reply_id,c.id AS thread_id
        FROM messages m JOIN chases c ON c.id=m.chase_id
        WHERE m.side='in' AND json_extract(m.transport,'$.mode')='inbox'
        ORDER BY julianday(coalesce(json_extract(m.transport,'$.authoredAt'),m.time)) DESC, m.id DESC
    """):
        latest.setdefault((row["supplier_id"], row["material"]), row)
    blocks = {}
    for key, row in latest.items():
        plan = json.loads(row["parsed"] or "{}").get("reply_plan", {})
        if plan.get("disposition"):
            blocks[key] = {**plan, "thread_id": row["thread_id"], "reply_id": row["reply_id"]}
    return blocks


def expire(con):
    schema(con)
    with con:
        con.execute("BEGIN IMMEDIATE")
        stale = list(con.execute("SELECT id,supplier,material,status FROM chases WHERE status IN ('awaiting reply','sending') AND due_at<=?", (now(),)))
        for chase in stale:
            if con.execute("SELECT 1 FROM supplier_loop_actions WHERE active=1 AND json_extract(payload,'$.dispatchThread')=?", (chase["id"],)).fetchone():
                continue
            con.execute("UPDATE chases SET status='escalated' WHERE id=?", (chase["id"],))
            activity(con, "Supplier Chaser", f'{chase["supplier"]}, {chase["material"]}: escalated to Procurement after one hour without a verified reply.', "warning")
    return len(stale)


def list_threads(con, decision_states=None):
    schema(con)
    from .mail_plan import contexts
    from .deals import is_decision_draft
    decision_states = decision_states or {}
    workflow = contexts(con)
    simulated_workflow = contexts(con, simulated=True)
    for row in con.execute("SELECT * FROM chases ORDER BY CASE status WHEN 'reply to verify' THEN 0 WHEN 'draft' THEN 2 ELSE 1 END, qty DESC, supplier"):
        thread = dict(row)
        if thread["status"] == "draft" and supplier_loop.managed(row["supplier_id"], row["material"]) and not is_decision_draft(con, row["id"]):
            thread["status"] = "superseded draft"
        if thread["status"] == "loop draft" and not con.execute(
            "SELECT 1 FROM supplier_loop_actions WHERE active=1 AND json_extract(payload,'$.dispatchThread')=?", (row["id"],)
        ).fetchone():
            thread["status"] = "superseded draft"
        thread["messages"] = []
        dry_run_thread = False
        for message in con.execute("""SELECT id,sender,side,body AS text,time,parsed,transport
                                     FROM messages WHERE chase_id=? ORDER BY id""", (row["id"],)):
            entry = dict(message)
            entry["parsed"] = json.loads(entry["parsed"]) if entry["parsed"] else None
            if entry["transport"]:
                entry["transport"] = json.loads(entry["transport"])
            elif entry["side"] == "out" and entry["sender"].endswith("(demo)"):
                entry["transport"] = {"mode": "dry_run", "status": "dry_run"}
            if entry["side"] == "out":
                dry_run_thread = (entry["transport"] or {}).get("mode") == "dry_run"
            elif dry_run_thread and not entry["transport"]:
                entry["transport"] = {"mode": "simulated", "status": "received"}
            plan = (entry["parsed"] or {}).get("reply_plan")
            if plan:
                default_status = plan.get("disposition") or ("proposed" if plan.get("editions") or plan.get("holdUnits") else "pending")
                plan["status"] = decision_states.get(plan.get("id"), default_status)
            thread["messages"].append(entry)
        if not thread["messages"] and thread["status"] in {"draft", "loop draft", "promise draft", "quote draft", "superseded draft"}:
            thread["messages"] = [{
                "sender": "Supplier Chaser", "side": "out", "text": row["body"], "time": "",
                "transport": {"mode": "draft", "status": "draft", "to": row["address"], "subject": row["subject"]},
            }]
        if dry_run_thread:
            state = simulated_workflow.get(thread["id"])
        else:
            state = workflow.get(thread["id"])
        if state and state["plan"]:
            thread["mailPlan"] = {**state["plan"], "replyId": state["replyId"],
                                  "sourceThread": state["sourceThread"], "simulated": dry_run_thread}
        yield thread


def reply_decision(con, message_id):
    row = con.execute("SELECT parsed FROM messages WHERE side='in' AND id=?", (message_id,)).fetchone()
    if row and row["parsed"]:
        plan = json.loads(row["parsed"]).get("reply_plan")
        if plan and (plan.get("editions") or plan.get("holdUnits")):
            return dict(plan, request_only=True)
    return None


from .agent import SupplierChaser
from .llm import DeterministicFakeLLM, LLMClient, LLMReplyParser
from .models import Issue, ReplyParse
from .store import ChaserStore

__all__ = ["SupplierChaser", "DeterministicFakeLLM", "LLMClient", "LLMReplyParser", "Issue", "ReplyParse", "ChaserStore"]
