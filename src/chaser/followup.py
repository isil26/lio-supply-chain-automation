"""Reminder drafts for silent suppliers, and attachment evidence from replies.

Reminders: a sent supplier email with no answer gets a polite reminder draft after a wait
that shrinks as the cut-off gets closer (12 h a few days out, 2 h on the last day). At most
two reminders per thread; after that the activity feed recommends a phone call. Reminders
are `draft` chases, so a person still reviews and sends them.

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
    now = _aware(now) if now else datetime.now(timezone.utc)
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT c.*, (SELECT max(time) FROM messages WHERE chase_id=c.id AND side='out') AS last_out
        FROM chases c
        WHERE c.status IN ('awaiting reply', 'no reply')
          AND c.subject NOT LIKE '%(SOONY-%'
          AND NOT EXISTS (SELECT 1 FROM messages WHERE chase_id=c.id AND side='in')
          AND NOT EXISTS (SELECT 1 FROM chases r JOIN messages m ON m.chase_id=r.id AND m.side='in'
                          WHERE r.subject LIKE '%(SOONY-' || c.id || ')%')
    """).fetchall()
    out = []
    for row in rows:
        row = dict(row)
        if not row.get("last_out"):
            continue
        waited = (now - _aware(row["last_out"])).total_seconds() / 3600
        need = wait_hours(now, row["deadline"])
        sent_reminders = con.execute("SELECT count(*) FROM chases WHERE subject LIKE ? AND id != ?",
                                     (f"%{row['id']}%", row["id"])).fetchone()[0]
        if waited < need:
            continue
        item = {"thread_id": row["id"], "supplier": row["supplier"], "waited_hours": round(waited, 1),
                "wait_limit_hours": round(need, 1), "reminders_so_far": sent_reminders}
        if sent_reminders >= MAX_REMINDERS:
            item["action"] = "call"
            if save:
                _activity(con, f"{row['supplier']}: no answer after {sent_reminders} reminders. Please call them.",
                          "warning")
        else:
            item["action"] = "remind"
            draft = reminder_draft(row, sent_reminders + 1)
            item["draft_id"], item["body"] = draft["id"], draft["body"]
            if save:
                with con:
                    inserted = con.execute("""INSERT OR IGNORE INTO chases
                        (id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                                           (draft["id"], row["supplier_id"], row["supplier"], row["address"],
                                            row["language"], draft["subject"], "draft", row["material"], row["qty"],
                                            draft["body"], row["deadline"])).rowcount
                if inserted:
                    _activity(con, f"{row['supplier']}: no answer for {waited:.0f} h. Reminder drafted for review.")
        out.append(item)
    return out


def reminder_draft(row, number):
    subject_t, body_t = REMINDER.get(row["language"], REMINDER["en"])
    original = re.sub(r"^\[SOONY-[A-F0-9]+\]\s*", "", row["subject"])
    sent = _aware(row["last_out"]).strftime("%Y-%m-%d %H:%M UTC")
    body = body_t.format(sent=sent, ref=f"SOONY-{row['id']}", material=row["material"])
    check = Guardrails().validate_draft(body)
    if not check.ok:
        raise ValueError("reminder failed guardrails: " + "; ".join(check.errors))
    ref = hashlib.sha256(f"{row['id']}:reminder:{number}".encode()).hexdigest()[:10].upper()
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
