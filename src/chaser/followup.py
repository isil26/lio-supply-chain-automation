"""Reminder drafts for silent suppliers, and attachment evidence from replies.

Reminders: a sent supplier email with no answer gets a polite reminder draft after a wait
that shrinks as the cut-off gets closer (12 h a few days out, 2 h on the last day). At most
two reminders per thread. After two sent reminders, Procurement reviews alternative supply.

Attachments: replies often carry a packing list, air waybill, bill of lading or invoice.
We record each attachment's name, type, what kind of document it looks like, and its text
(PDF or plain text), so the best-supplier model can count it as proof.
"""
from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime, timezone

from .guardrails import Guardrails

MAX_REMINDERS = 2
DOC_KINDS = (
    ("air_waybill", re.compile(r"\bAWB\b|air ?waybill|\b\d{3}-\d{8}\b", re.I)),
    ("bill_of_lading", re.compile(r"\bB/?L\b|bill of lading|\b[A-Z]{4}\d{7}\b", re.I)),
    ("packing_list", re.compile(r"packing ?list|lista pakunkowa|装箱单|패킹 ?리스트", re.I)),
    ("invoice", re.compile(r"invoice|faktura|发票|송장", re.I)),
    ("delivery_note", re.compile(r"delivery note|lieferschein|wz\b|送货单", re.I)),
)
REMINDER = {
    "en": ("Reminder: {subject}", "Hello,\n\nWe are following up on our message of {sent} ({ref}). Could you reply with the "
           "available quantity, delivery date and price for {material}? A short answer is enough.\n\n"
           "This is a request for information only, not an order.\n\nSoony launch team"),
    "pl": ("Przypomnienie: {subject}", "Dzień dobry,\n\nnawiązujemy do naszej wiadomości z {sent} ({ref}). Prosimy o "
           "informację o dostępnej ilości, terminie dostawy i cenie {material}. Wystarczy krótka odpowiedź.\n\n"
           "To jest wyłącznie zapytanie informacyjne, a nie zamówienie.\n\nZespół startowy Soony"),
    "ko": ("다시 연락드립니다: {subject}", "안녕하세요,\n\n{sent}에 보내드린 메일({ref})에 대해 다시 연락드립니다. {material}의 "
           "가능 수량, 납기, 단가를 회신해 주시기 바랍니다. 간단한 답변이면 충분합니다.\n\n"
           "이 메일은 정보 요청이며 발주가 아닙니다.\n\nSoony 출시 담당팀"),
    "zh": ("提醒：{subject}", "您好，\n\n我们跟进 {sent} 发送的邮件（{ref}）。请告知 {material} 的可供数量、交货日期和价格，"
           "简短回复即可。\n\n本邮件仅为信息询问，并非订单。\n\nSoony 上市团队"),
}


def hamburg_time(value):
    """Show a time the way the suppliers saw the cut-off: Hamburg local time, e.g. '22 Nov 20:00 CET'."""
    from zoneinfo import ZoneInfo
    local = value.astimezone(ZoneInfo("Europe/Berlin"))
    return local.strftime("%d %b %H:%M ") + (local.tzname() or "CET")


def _aware(value):
    value = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def wait_hours(now, deadline):
    """How long to wait for an answer before reminding: shorter as the cut-off nears."""
    hours_left = (_aware(deadline) - _aware(now)).total_seconds() / 3600
    return max(2.0, min(12.0, hours_left / 6))


def due_reminders(con, now=None, *, save=False):
    """Threads that need a reminder now. With save=True, store reminder drafts for review."""
    import sqlite3
    from .supplier_loop import managed
    now = _aware(now) if now else datetime.now(timezone.utc)
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT c.*, (SELECT time FROM messages WHERE chase_id=c.id AND side='out'
                         AND coalesce(json_extract(transport,'$.mode'),'') NOT IN ('dry_run','simulated')
                         AND coalesce(json_extract(transport,'$.status'),'smtp_accepted')='smtp_accepted'
                         AND sender NOT LIKE '%(demo)' ORDER BY julianday(time) DESC LIMIT 1) AS last_out
        FROM chases c
        WHERE c.status IN ('awaiting reply', 'no reply') AND c.parent_thread_id IS NULL
          AND c.subject NOT LIKE '%(SOONY-%'
    """).fetchall()
    out = []
    from .mail_plan import contexts
    states = contexts(con)
    handoffs = quality_handoffs(con)
    for row in rows:
        row = dict(row)
        if row["id"] in states or _root(row) in handoffs or managed(row["supplier_id"], row["material"]):
            continue
        if not row["last_out"] or _aware(row["deadline"]) <= now:
            continue
        # Use only accepted send receipts. A pending draft may survive many worker cycles.
        reminder_ids = [reminder_id(row["id"], n) for n in range(1, MAX_REMINDERS + 1)]
        sent = con.execute("""SELECT chase_id, time FROM messages WHERE chase_id IN (?,?) AND side='out'
                            AND coalesce(json_extract(transport,'$.mode'),'') NOT IN ('dry_run','simulated')
                            AND coalesce(json_extract(transport,'$.status'),'smtp_accepted')='smtp_accepted'
                            AND sender NOT LIKE '%(demo)' ORDER BY julianday(time) DESC""", reminder_ids).fetchall()
        sent_reminders = len({m["chase_id"] for m in sent})
        if sent:
            row["last_out"] = sent[0]["time"]
        waited = (now - _aware(row["last_out"])).total_seconds() / 3600
        need = wait_hours(now, row["deadline"])
        if waited < need:
            continue
        item = {"thread_id": row["id"], "supplier": row["supplier"], "waited_hours": round(waited, 1),
                "wait_limit_hours": round(need, 1), "reminders_so_far": sent_reminders}
        if sent_reminders >= MAX_REMINDERS:
            item["action"] = "review"
            if save:
                detail = f"SOONY-{row['id']} · {row['supplier']}: two reminders sent without a reply. Procurement to review alternative supply."
                with con:
                    con.execute("""INSERT INTO activity(time,agent,action,type) SELECT ?, 'Mail Agent', ?, 'warning'
                                   WHERE NOT EXISTS (SELECT 1 FROM activity WHERE agent='Mail Agent' AND action=?)""",
                                (now.isoformat(timespec="seconds"), detail, detail))
        else:
            item["action"] = "remind"
            draft = reminder_draft(row, sent_reminders + 1)
            item["draft_id"], item["body"] = draft["id"], draft["body"]
            if save:
                with con:
                    inserted = con.execute("""INSERT OR IGNORE INTO chases
                        (id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline,parent_thread_id)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                                           (draft["id"], row["supplier_id"], row["supplier"], row["address"],
                                            row["language"], draft["subject"], "draft", row["material"], row["qty"],
                                            draft["body"], row["deadline"], row["id"])).rowcount
                if inserted:
                    _activity(con, f"{row['supplier']}: no answer for {waited:.0f} h. Reminder drafted for review.")
        out.append(item)
    return out


def reminder_id(thread_id, number):
    return hashlib.sha256(f"{thread_id}:reminder:{number}".encode()).hexdigest()[:10].upper()


def reminder_draft(row, number):
    subject_t, body_t = REMINDER.get(row["language"], REMINDER["en"])
    original = re.sub(r"^\[SOONY-[A-F0-9]+\]\s*", "", row["subject"])
    sent = hamburg_time(_aware(row["last_out"]))
    body = body_t.format(sent=sent, ref=f"SOONY-{row['id']}", material=row["material"])
    check = Guardrails().validate_draft(body)
    if not check.ok:
        raise ValueError("reminder failed guardrails: " + "; ".join(check.errors))
    ref = reminder_id(row["id"], number)
    return {"id": ref, "subject": f"[SOONY-{ref}] " + subject_t.format(subject=f"{original} (SOONY-{row['id']})"),
            "body": body}


def _activity(con, text, kind="info"):
    with con:
        con.execute("INSERT INTO activity(time,agent,action,type) VALUES(?,?,?,?)",
                    (datetime.now(timezone.utc).isoformat(timespec="seconds"), "Mail Agent", text, kind))


def attachment_evidence(message, limit=4000):
    """Name, type, document kind and text of each attachment in an email.message.EmailMessage."""
    found = []
    for part in message.iter_attachments():
        name = part.get_filename() or "attachment"
        ctype = part.get_content_type()
        text = ""
        try:
            payload = part.get_payload(decode=True) or b""
            if ctype == "application/pdf" or name.lower().endswith(".pdf"):
                from pypdf import PdfReader
                reader = PdfReader(io.BytesIO(payload))
                text = "\n".join((page.extract_text() or "") for page in reader.pages[:5])
            elif ctype.startswith("text/") or name.lower().endswith((".txt", ".csv")):
                text = payload.decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:  # unreadable attachment: keep the name, flag for a person
            text = ""
        kind = next((k for k, pattern in DOC_KINDS if pattern.search(name) or pattern.search(text)), None)
        found.append({"name": name, "type": ctype, "kind": kind, "text": text[:limit].strip(),
                      "needs_review": not text})
    return found


# --------------------------------------------------------------------------- answering replies

CANNOT = re.compile(r"\b(?:cannot|can't|can’t|unable|not possible|impossible|no way to)\b|nie (?:możemy|będziemy|jest możliwe)"
                    r"|无法|不能|不可能|불가|어렵", re.I)
PICKUP = re.compile(r"\bEXW\b|ex[- ]works|forwarder|pick[- ]?up|collect(?:ion)?|odbi[oó]r|spedytor|自提|提货|픽업|포워더", re.I)
THREAD = re.compile(r"\[SOONY-([A-F0-9]+)\]", re.I)
SORT = re.compile(r"\b(?:visual sort|inspection|quarantin\w*|signed disposition)\b|检验|선별|sortowani\w*", re.I)
CRITERIA = re.compile(r"\b(?:acceptance (?:standards?|criteria)|reference (?:photos?|photographs)|sorting criteria)\b"
                      r"|验收标准|검사 기준|kryteri\w+ akceptacji", re.I)
ARRIVAL = re.compile(
    r"\b(?:arrival|handoff)\b[^.\n]{0,80}?\b(\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
    r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"(?:\s+\d{4})?)\b", re.I)
FREIGHT_REF = re.compile(r"\b(?:[A-Z]{4}\d{7}|\d{3}-\d{8}|SHP-[A-Z0-9-]+)\b")
ANSWER = {
    "en": {"open": "Hello,\n\nThank you for your reply.",
           "cannot": "We understand the full quantity is not possible in time. Could you tell us how many units you could ship before {deadline} as a part shipment, and the earliest date for the rest?",
           "pickup": "To arrange collection, please send the ready-for-pickup date and time, the pickup address, the number of cartons or pallets and the gross weight.",
           "missing": "To complete our planning, could you also confirm: {items}?",
           "doc": "Could you send the packing list or the shipping/booking reference once available?",
           "noted": "We have noted your confirmation and will come back to you after our internal review.",
           "items": {"quantity": "the quantity you can supply", "eta": "the delivery date to Hamburg", "price": "the delivered unit price"},
           "close": "This is a request for information only, not an order.\n\nSoony launch team"},
    "pl": {"open": "Dzień dobry,\n\ndziękujemy za odpowiedź.",
           "cannot": "Rozumiemy, że pełna ilość nie jest możliwa na czas. Ile sztuk mogliby Państwo wysłać przed {deadline} jako dostawę częściową i jaki jest najwcześniejszy termin dla reszty?",
           "pickup": "Aby zorganizować odbiór, prosimy o datę i godzinę gotowości do odbioru, adres odbioru, liczbę kartonów lub palet oraz wagę brutto.",
           "missing": "Prosimy również o potwierdzenie: {items}.",
           "doc": "Prosimy o przesłanie listy pakunkowej lub numeru przesyłki/rezerwacji, gdy będzie dostępny.",
           "noted": "Przyjęliśmy Państwa potwierdzenie do wiadomości i wrócimy po wewnętrznej weryfikacji.",
           "items": {"quantity": "dostępnej ilości", "eta": "terminu dostawy do Hamburga", "price": "ceny jednostkowej z dostawą"},
           "close": "To jest wyłącznie zapytanie informacyjne, a nie zamówienie.\n\nZespół startowy Soony"},
    "ko": {"open": "안녕하세요,\n\n회신 감사합니다.",
           "cannot": "전체 수량이 기한 내 어렵다는 점 이해했습니다. {deadline} 전에 부분 출하로 보낼 수 있는 수량과 나머지 수량의 가장 빠른 날짜를 알려 주시겠습니까?",
           "pickup": "픽업 준비를 위해 출고 가능 일시, 픽업 주소, 카톤 또는 팔레트 수량, 총중량을 보내 주시기 바랍니다.",
           "missing": "계획 수립을 위해 다음도 확인 부탁드립니다: {items}.",
           "doc": "준비되는 대로 패킹 리스트 또는 운송/부킹 번호를 보내 주시겠습니까?",
           "noted": "확인 내용을 접수했으며 내부 검토 후 다시 연락드리겠습니다.",
           "items": {"quantity": "공급 가능 수량", "eta": "함부르크 도착일", "price": "도착 기준 단가"},
           "close": "이 메일은 정보 요청이며 발주가 아닙니다.\n\nSoony 출시 담당팀"},
    "zh": {"open": "您好，\n\n感谢您的回复。",
           "cannot": "我们理解无法按时交付全部数量。请告知在 {deadline} 前可以分批发运多少件，以及其余数量的最早日期。",
           "pickup": "为安排提货，请提供可提货日期和时间、提货地址、箱数或托盘数以及毛重。",
           "missing": "为完成计划，也请确认：{items}。",
           "doc": "请在可用时发送装箱单或运输/订舱编号。",
           "noted": "我们已记录贵司的确认，内部审核后会再与您联系。",
           "items": {"quantity": "可供数量", "eta": "到达汉堡的日期", "price": "到货单价"},
           "close": "本邮件仅为信息询问，并非订单。\n\nSoony 上市团队"},
}


def answer_body(language, reply, deadline):
    """Plain follow-up to a supplier reply: ask for what is missing, never commit."""
    from .negotiate import parse_offer
    t = ANSWER.get(language, ANSWER["en"])
    offer = parse_offer(reply)
    due = hamburg_time(_aware(deadline)) if deadline else "the launch"
    lines, kinds = [t["open"]], []
    if CANNOT.search(reply):
        lines.append(t["cannot"].format(deadline=due)); kinds.append("partial")
    if PICKUP.search(reply):
        lines.append(t["pickup"]); kinds.append("pickup")
    missing = [key for key, value in (("quantity", offer["quantity"]), ("eta", offer["eta"]),
                                      ("price", offer["unit_price"])) if not value]
    if "partial" not in kinds and missing:
        lines.append(t["missing"].format(items=", ".join(t["items"][m] for m in missing))); kinds.append("missing")
    if offer["commitment"] < 3 and "partial" not in kinds:
        lines.append(t["doc"]); kinds.append("document")
    if not kinds:
        lines.append(t["noted"]); kinds.append("noted")
    body = "\n\n".join([lines[0], " ".join(lines[1:]), t["close"]])
    check = Guardrails().validate_draft(body)
    if not check.ok:
        raise ValueError("answer failed guardrails: " + "; ".join(check.errors))
    return body, kinds


def _root(row):
    token = THREAD.search(row["subject"])
    return (row["supplier_id"], row["material"], token[1].upper() if token else row["id"])


def quality_handoffs(con):
    """A verified request for internal acceptance criteria belongs to Supplier Quality."""
    from .recovery import unquoted

    roots = {}
    for row in con.execute("""
        SELECT c.id,c.supplier,c.supplier_id,c.material,c.subject,m.body,m.external_id
        FROM messages m JOIN chases c ON c.id=m.chase_id
        WHERE m.side='in' AND json_extract(m.transport,'$.mode')='inbox'
          AND EXISTS (
            SELECT 1 FROM messages p WHERE p.chase_id=c.id AND p.side='out'
              AND json_extract(p.transport,'$.status') IN ('smtp_accepted','gmail_sent')
              AND (p.external_id=json_extract(m.transport,'$.inReplyTo')
                   OR (lower(m.sender)=lower(c.address) AND julianday(p.time)<=julianday(m.time)
                       AND instr(upper(json_extract(m.transport,'$.subject')), '[SOONY-' || upper(c.id) || ']')>0))
          )
        ORDER BY m.id
    """):
        body = unquoted(row["body"])
        if SORT.search(body) and CRITERIA.search(body):
            roots[_root(row)] = row
    return roots


def human_owned_thread(con, thread):
    row = con.execute("SELECT id,supplier_id,material,subject FROM chases WHERE id=?", (thread,)).fetchone()
    return bool(row and _root(row) in quality_handoffs(con))


def _late_freight(body, deadline):
    # This only settles the identified freight question. It does not infer
    # that a separate local sort or another available shipment is also late.
    from .recovery import hamburg_eta

    if len(set(FREIGHT_REF.findall(body))) != 1 or not (match := ARRIVAL.search(body)):
        return False
    text = match[1]
    cutoff = _aware(deadline)
    if (alternate := hamburg_eta(body)) and alternate < cutoff:
        return False
    for form in ("%d %B %Y", "%d %b %Y", "%d %B", "%d %b"):
        try:
            date = datetime.strptime(text, form)
            year = date.year if "%Y" in form else cutoff.year
            return date.replace(year=year).date() > cutoff.date()
        except ValueError:
            continue
    return False


def _answer_id(root, body, content):
    from .negotiate import parse_offer

    offer = parse_offer(content)
    evidence = (*sorted(set(FREIGHT_REF.findall(content))), offer["quantity"], offer["eta"],
                offer["unit_price"], offer["currency"], offer["commitment"])
    return hashlib.sha256(repr((root, body, evidence)).encode()).hexdigest()[:10].upper()


def _legacy_answer_id(reply):
    return hashlib.sha256(f"answer:{reply}".encode()).hexdigest()[:10].upper()


def answer_replies(con, *, save=False, now=None):
    """Draft an answer for every supplier reply that we have not answered yet."""
    import sqlite3
    from .recovery import claimed_threads, unquoted
    from .supplier_loop import managed

    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT c.*, m.body AS reply, m.external_id AS reply_id, m.id AS source_id, m.parsed AS reply_fields
        FROM chases c JOIN messages m ON m.chase_id = c.id AND m.side = 'in'
        WHERE NOT EXISTS (SELECT 1 FROM messages o WHERE o.chase_id=c.id AND o.side='out' AND o.id>m.id
                          AND coalesce(json_extract(o.transport,'$.mode'),'') NOT IN ('dry_run','simulated'))
          AND coalesce(json_extract(m.transport, '$.mode'), '') <> 'simulated'
    """).fetchall()
    out = []
    from .mail_plan import contexts, record_checkpoints
    from .negotiate import is_late_offer
    import json

    states = contexts(con)
    owned = claimed_threads(con)
    handoffs = quality_handoffs(con)
    if save:
        with con:
            record_checkpoints(con, states, now)
            # Preserve legacy physical threads and sent mail. Only retire queued
            # drafts that can be identified as a generic reply to this handoff.
            for root, trigger in handoffs.items():
                for history in con.execute("""
                    SELECT c.id,c.supplier_id,c.material,c.subject,c.language,c.deadline,m.external_id,m.body
                    FROM chases c JOIN messages m ON m.chase_id=c.id WHERE m.side='in'
                      AND c.supplier_id=? AND c.material=?
                """, root[:2]):
                    if _root(history) == root:
                        content = unquoted(history["body"])
                        body, _ = answer_body(history["language"], content, history["deadline"])
                        con.execute("UPDATE chases SET status='superseded draft' WHERE id IN (?,?) AND status='draft'",
                                    (_legacy_answer_id(history["external_id"]), _answer_id(root, body, content)))
                details = (f"{trigger['supplier']}: Supplier Quality owns the local sort acceptance criteria "
                           f"requested in SOONY-{root[2]}. Routine freight follow-ups paused for this thread.")
                con.execute("""INSERT INTO activity(time,agent,action,type)
                    SELECT ?, 'Mail Agent', ?, 'warning' WHERE NOT EXISTS(
                        SELECT 1 FROM activity WHERE agent='Mail Agent' AND action=?)""",
                            (datetime.now(timezone.utc).isoformat(timespec="seconds"), details, details))
    for row in rows:
        row = dict(row)
        if row["id"] in owned or managed(row["supplier_id"], row["material"]):
            continue  # the launch-critical loop (supplier_loop.py) answers these itself
        root = _root(row)
        content = unquoted(row["reply"])
        state = states.get(row["id"])
        if not state or state["replyId"] != row["source_id"] or state["plan"]:
            continue
        attachments = json.loads(row["reply_fields"] or "{}").get("attachments", [])
        if root in handoffs or _late_freight(content, row["deadline"]) or is_late_offer(content, row["deadline"], attachments):
            continue
        body, kinds = answer_body(row["language"], content, row["deadline"])
        ref = _answer_id(root, body, content)
        legacy = _legacy_answer_id(row["reply_id"])
        if con.execute("SELECT 1 FROM chases WHERE id IN (?,?)", (ref, legacy)).fetchone():
            continue
        subject = row["subject"] if row["subject"].lower().startswith("re:") else "Re: " + row["subject"]
        item = {"thread_id": row["id"], "supplier": row["supplier"], "draft_id": ref, "asks": kinds, "body": body}
        if save:
            with con:
                con.execute("""INSERT OR IGNORE INTO chases
                    (id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline,parent_thread_id,based_on_reply_id)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (ref, row["supplier_id"], row["supplier"], row["address"], row["language"], subject,
                             "draft", row["material"], row["qty"], body, row["deadline"], row["id"], row["source_id"]))
            _activity(con, f"{row['supplier']}: replied. Answer drafted ({', '.join(kinds)}).")
        out.append(item)
    return out
