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
from email.utils import make_msgid, parseaddr



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
           due_at TEXT, message_id TEXT
       );
       CREATE TABLE IF NOT EXISTS messages (
           id INTEGER PRIMARY KEY, chase_id TEXT REFERENCES chases(id), external_id TEXT UNIQUE,
           side TEXT NOT NULL, sender TEXT NOT NULL, body TEXT NOT NULL, time TEXT NOT NULL, parsed TEXT
       );
       CREATE TABLE IF NOT EXISTS activity (
           id INTEGER PRIMARY KEY, time TEXT NOT NULL, agent TEXT NOT NULL, action TEXT NOT NULL, type TEXT NOT NULL
       );
    """)


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
            candidates = {row["supplier_id"] for row in part["suppliers"] if row["supplier"].get("status") == "active"}
            candidates.update(event["supplier"] for event in truth["issues"]
                              if event["material"] == part["material"] and event.get("supplier"))
            for supplier_id in sorted(candidates):
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


def send(con, chase_id, demo=False):
    schema(con)
    if not demo:
        from .mailenv import load_team_mail_env
        load_team_mail_env()
    sender = os.getenv("CHASER_SENDER")
    host = os.getenv("CHASER_SMTP_HOST")
    if not sender:
        raise ValueError("CHASER_SENDER is required")
    if not demo and (not host or os.getenv("CHASER_REAL_SMTP") != "1"):
        raise ValueError("Live sending requires CHASER_REAL_SMTP=1 and CHASER_SMTP_HOST")
    message = EmailMessage()
    message["From"] = sender
    with con:
        con.execute("BEGIN IMMEDIATE")
        chase = con.execute("SELECT * FROM chases WHERE id=?", (chase_id,)).fetchone()
        if not chase or chase["status"] != "draft":
            raise ValueError("Only a current draft can be sent")
        message_id = make_msgid(domain=parseaddr(sender)[1].split("@")[-1])
        if not demo:
            from .allowlist import check_recipient
            check_recipient(chase["address"])
        message["To"], message["Subject"], message["Message-ID"] = chase["address"], chase["subject"], message_id
        message.set_content(chase["body"])
        con.execute("UPDATE chases SET status='sending',message_id=?,due_at=? WHERE id=?",
                    (message_id, (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds"), chase_id))
    try:
        if not demo:
            context = ssl.create_default_context()
            port = int(os.getenv("CHASER_SMTP_PORT", "587"))
            if port == 465:
                with smtplib.SMTP_SSL(host, port, timeout=20, context=context) as client:
                    authenticate(client)
                    client.send_message(message)
            else:
                with smtplib.SMTP(host, port, timeout=20) as client:
                    client.starttls(context=context)
                    authenticate(client)
                    client.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        # SMTP acceptance can be ambiguous after a disconnect. Keep the message ID for reconciliation.
        with con:
            con.execute("UPDATE chases SET status='delivery uncertain' WHERE id=?", (chase_id,))
            activity(con, "Supplier Chaser", f'{chase["supplier"]}: delivery uncertain. Verify the outbox before retry.', "warning")
        raise ValueError("SMTP delivery is uncertain. Check the registered sender’s outbox.") from exc
    with con:
        con.execute("UPDATE chases SET status='awaiting reply' WHERE id=? AND status='sending'", (chase_id,))
        con.execute("INSERT OR IGNORE INTO messages(chase_id,external_id,side,sender,body,time) VALUES(?,?,?,?,?,?)",
                    (chase_id, message_id, "out", "Supplier Chaser"+(" (demo)" if demo else ""), chase["body"], now()))
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


def receive(con, message):
    schema(con)
    sender = parseaddr(message.get("From", ""))[1].casefold()
    parent = (message.get("In-Reply-To", "") or "").strip()
    subject = message.get("Subject", "")
    ref = re.search(r"\[SOONY-([A-F0-9]+)\]", subject)
    chase = con.execute("""SELECT * FROM chases WHERE lower(address)=? AND
               (message_id=? OR id=?) AND status NOT IN ('draft')""", (sender, parent, ref[1] if ref else "")).fetchone()
    if not chase:
        return False
    part = message.get_body(preferencelist=("plain",))
    if not part:
        return False
    # Exclude quoted previous mail so a request in the original isn't imported as a claim.
    body = "\n".join(line for line in part.get_content().splitlines() if not line.lstrip().startswith(">")).strip()[:12000]
    if not body:
        return False
    message_id = message.get("Message-ID") or hashlib.sha256(message.as_bytes()).hexdigest()
    with con:
        inserted = con.execute("""INSERT OR IGNORE INTO messages(chase_id,external_id,side,sender,body,time,parsed)
            VALUES(?,?,?,?,?,?,?)""", (chase["id"], str(message_id), "in", chase["supplier"], body, now(),
                                     json.dumps(parse_reply(body), ensure_ascii=False))).rowcount
        if inserted:
            con.execute("UPDATE chases SET status='reply to verify' WHERE id=?", (chase["id"],))
            activity(con, "Supplier Chaser", f'{chase["supplier"]}: matched reply. Supplier claims are queued for review.')
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
        inbox.select("INBOX")
        status, hits = inbox.uid("search", None, '(UNSEEN SUBJECT "SOONY-")')
        if status != "OK" or not hits:
            return 0
        for uid in hits[0].split()[:40]:
            status, payload = inbox.uid("fetch", uid, "(BODY.PEEK[])")
            if status != "OK":
                continue
            item = next((entry[1] for entry in payload if isinstance(entry, tuple)), None)
            if item and receive(con, email.message_from_bytes(item, policy=default)):
                count += 1
                inbox.uid("store", uid, "+FLAGS", "(\\Seen)")
    return count


def expire(con):
    schema(con)
    with con:
        con.execute("BEGIN IMMEDIATE")
        stale = list(con.execute("SELECT id,supplier,material,status FROM chases WHERE status IN ('awaiting reply','sending') AND due_at<=?", (now(),)))
        for chase in stale:
            con.execute("UPDATE chases SET status='escalated' WHERE id=?", (chase["id"],))
            activity(con, "Supplier Chaser", f'{chase["supplier"]}, {chase["material"]}: escalated to Procurement after one hour without a verified reply.', "warning")
    return len(stale)


def list_threads(con):
    schema(con)
    for row in con.execute("SELECT * FROM chases ORDER BY CASE status WHEN 'reply to verify' THEN 0 WHEN 'draft' THEN 2 ELSE 1 END, qty DESC, supplier"):
        thread = dict(row)
        thread["messages"] = [dict(msg, parsed=json.loads(msg["parsed"]) if msg["parsed"] else None) for msg in
                              con.execute("SELECT sender,side,body AS text,time,parsed FROM messages WHERE chase_id=? ORDER BY id", (row["id"],))]
        if not thread["messages"] and thread["status"] == "draft":
            thread["messages"] = [{"sender": "Supplier Chaser · draft", "side": "out", "text": row["body"], "time": ""}]
        yield thread
from .agent import SupplierChaser
from .llm import DeterministicFakeLLM, LLMClient, LLMReplyParser
from .models import Issue, ReplyParse
from .store import ChaserStore

__all__ = ["SupplierChaser", "DeterministicFakeLLM", "LLMClient", "LLMReplyParser", "Issue", "ReplyParse", "ChaserStore"]
