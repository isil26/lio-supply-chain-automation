"""Approve on an Actions card sends the supplier email (gülşah-agent, Gülşah's decision 22 Nov).

`preview(con, option)` says exactly which email an Approve click on this option causes, so the
approver sees what they are responsible for before confirming:

  mode "send"          -> a new hold-and-quote request in the supplier's language; on approve it goes
                          out through the T83 send path (src/chaser/actions.py: allowlist, guardrails,
                          team mailbox; dry run unless live mail is on).
  mode "conversation"  -> the mail agent already runs this supplier conversation (supplier loop);
                          a second email would confuse the supplier and break reply matching, so the
                          preview shows the ongoing email instead and nothing new is sent.
  mode "internal"      -> decisions for colleagues (pack-out priority, dock slot, quality, ...): the
                          person approving IS the decision-maker, so the decision goes out as a message
                          to the colleague who carries it out. The case's colleagues are fictional and
                          have no mailboxes, so the message is emailed to the team mailbox, addressed
                          "[For <name>]" (CHASER_INTERNAL_TO overrides the address).

`send(con, option, by, demo)` performs the "send" case and returns the T83 delivery row.
"""
from __future__ import annotations

import os
import re
from datetime import datetime

from . import supplier_loop

HOLD_QUOTE = {
    "en": ("Hold request and delivered quote for {part}",
           "Hello {name},\n\nFor our Hamburg launch we would like to ask whether you can hold {qty:,} units of {part} for us "
           "until {deadline} CET. Please reply with the quantity you can hold, a written delivered price to Hamburg (DAP), "
           "the earliest pickup time and how long the hold is valid.\n\n"
           "This is a request for information only, not an order. Any order follows separately in writing.\n\nSoony launch team"),
    "pl": ("Prośba o rezerwację i ofertę z dostawą: {part}",
           "Dzień dobry,\n\nw związku z premierą w Hamburgu prosimy o informację, czy mogą Państwo zarezerwować dla nas "
           "{qty:,} szt. {part} do {deadline} CET. Prosimy o podanie ilości możliwej do rezerwacji, pisemnej ceny z dostawą "
           "do Hamburga (DAP), najwcześniejszego terminu odbioru oraz okresu ważności rezerwacji.\n\n"
           "Jest to wyłącznie zapytanie informacyjne, a nie zamówienie. Ewentualne zamówienie prześlemy osobno na piśmie.\n\nZespół Soony"),
    "ko": ("{part} 재고 확보 및 도착도 견적 요청",
           "{name}님, 안녕하세요.\n\n함부르크 출시를 위해 {part} {qty:,}개를 {deadline} CET까지 저희를 위해 확보해 주실 수 있는지 "
           "문의드립니다. 확보 가능 수량, 함부르크 도착도(DAP) 서면 견적, 가장 빠른 픽업 시간, 확보 유효 기간을 회신해 주시기 바랍니다.\n\n"
           "이 메일은 정보 요청이며 발주가 아닙니다. 발주는 별도로 서면으로 드립니다.\n\nSoony 출시 담당팀"),
    "zh": ("{part} 预留及到岸报价请求",
           "{name}，您好。\n\n为配合汉堡上市，请问贵司能否为我们预留 {qty:,} 件 {part}，至 {deadline} CET。请告知可预留数量、"
           "送达汉堡（DAP）的书面报价、最早提货时间以及预留有效期。\n\n本邮件仅为信息询问，并非订单。如需下单，我们将另行书面通知。\n\nSoony 上市团队"),
}
QTY = re.compile(r"(\d{1,3}(?:[,\s]\d{3})+|\d+)\s+(?:finished\s+)?(?:units|copies|pcs|pieces)", re.I)


def _row(con, sql, args):
    cur = con.execute(sql, args)
    row = cur.fetchone()
    return dict(zip([c[0] for c in cur.description], row)) if row else None


def _table(con, name):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _quantity(con, option):
    if option.get("quantity"):
        return int(option["quantity"])
    if hit := QTY.search(option.get("recommendation") or ""):
        return int(re.sub(r"\D", "", hit[1]))
    try:
        from src.ingest.store import get_state
        return int((get_state(con, "truth", {}) or {}).get("parts", {}).get(option.get("material"), {}).get("shortfall") or 0)
    except Exception:
        return 0


def _deadline(con, option):
    value = option.get("latest_action") or option.get("deadline") or ""
    try:
        return datetime.fromisoformat(value).strftime("%d %b %H:%M")
    except ValueError:
        return "the cut-off"


SUPPLIER_KINDS = {"partial", "alternate", "air"}  # options whose next step is a supplier request


def preview(con, option):
    supplier_id, material = option.get("supplier_id"), option.get("material")
    if option.get("kind") and option["kind"] not in SUPPLIER_KINDS:
        return internal_preview(con, option)
    profile = _row(con, "SELECT * FROM suppliers WHERE supplier_id=?", (supplier_id,)) if (
        supplier_id and _table(con, "suppliers")) else None
    name = (profile or {}).get("name") or supplier_id or "the supplier"
    if supplier_id and supplier_loop.managed(supplier_id, material):
        last = _row(con, """SELECT c.id AS threadId, c.address, c.subject, m.body, m.time FROM chases c
                            JOIN messages m ON m.chase_id=c.id AND m.side='out'
                            WHERE c.supplier_id=? AND c.material=? ORDER BY m.time DESC LIMIT 1""",
                    (supplier_id, material)) if _table(con, "chases") else None
        return {"mode": "conversation", "supplier": name, "to": (last or {}).get("address") or (profile or {}).get("contact_email"),
                "subject": (last or {}).get("subject"), "body": (last or {}).get("body"), "sentAt": (last or {}).get("time"),
                "threadId": (last or {}).get("threadId"),
                "note": f"The mail agent already runs the email conversation with {name}. Approving records your decision; "
                        "it does not send a second email, so the supplier gets one clear thread."}
    if not (profile and profile.get("contact_email")):
        return internal_preview(con, option, note=f"No email address on file for {name}, so the buyer gets the task.")
    language = profile.get("preferred_language") or "en"
    subject, template = HOLD_QUOTE.get(language, HOLD_QUOTE["en"])
    qty = _quantity(con, option)
    body = template.format(name=profile.get("contact_name") or name, part=material, qty=qty, deadline=_deadline(con, option))
    return {"mode": "send", "supplier": name, "to": profile["contact_email"], "language": language,
            "subject": subject.format(part=material), "body": body, "qty": qty,
            "note": f"Approving sends this email to {name} from the team mailbox and tracks the reply."}


# Who carries out an internal decision (org_chart_v2, 21 Nov). Falls back to the option owner.
DOER = {"priority": ("Katrin Jansen", "Site Lead DC Hamburg"), "inbound": ("Katrin Jansen", "Site Lead DC Hamburg"),
        "quality": ("Clara Weiss", "Quality & Compliance Manager"), "ppap_release": ("Daniel Okafor", "Supplier Quality Lead")}


def team_mailbox():
    from .mailenv import load_team_mail_env
    load_team_mail_env()
    return os.getenv("CHASER_INTERNAL_TO") or os.getenv("CHASER_SENDER") or "launch-team@example.invalid"


def internal_preview(con, option, note=None):
    name, role = DOER.get(option.get("kind"), (option.get("owner") or "the owner", ""))
    first = name.split()[1] if name.startswith("Dr.") and len(name.split()) > 1 else name.split()[0]
    lines = [f"Hello {first},", "", f"Approved: {option.get('title')}.", ""]
    if option.get("recommendation"):
        # The decision-maker is the sender, so drop sentences that ask them to decide ("Ask Maren to confirm ...").
        owner = (option.get("owner") or "").replace("Dr. ", "").split()
        ask = re.compile(rf"\bAsk (?:{'|'.join(map(re.escape, owner))})\b", re.I) if owner else None
        kept = [x for x in re.split(r"(?<=\.)\s+", option["recommendation"]) if not (ask and ask.search(x))]
        if kept:
            lines.append(" ".join(kept))
    if option.get("impact"):
        lines.append(f"Expected effect: {option['impact']}")
    if option.get("price"):
        lines.append(f"Cost: EUR {float(option['price']):,.0f}")
    if when := _deadline(con, option) if (option.get("latest_action") or option.get("deadline")) else None:
        lines.append(f"Please act on it by {when} CET.")
    lines += ["", "Please reply to this email when it is done, or right away if something blocks it.", "", "Soony launch control"]
    who = f"{name} ({role})" if role else name
    return {"mode": "internal", "to": team_mailbox(), "recipientName": who,
            "subject": f"[For {name}] {option.get('title')}", "body": "\n".join(lines),
            "note": (note + " " if note else "") + f"Approving sends this message to {who} via the team mailbox."}


def _send_internal(con, option, mail, by, demo):
    """Email an internal decision to the team mailbox and record it like any T83 delivery."""
    import hashlib
    from . import actions, schema, send as chaser_send
    schema(con)
    actions.schema(con)
    ref = hashlib.sha256(f"internal:{option['id']}".encode()).hexdigest()[:10].upper()
    subject = f"[SOONY-{ref}] {mail['subject']}"
    with con:
        con.execute("""INSERT OR IGNORE INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (ref, "INTERNAL", mail["recipientName"], mail["to"], "en", subject,
                                                       "draft", option.get("material") or "", 0, mail["body"],
                                                       option.get("deadline") or ""))
    try:
        chaser_send(con, ref, demo=demo)
        status, note = "sent", ("Dry run (demo): nothing left the building." if demo else "Sent to the team mailbox.")
    except (ValueError, PermissionError) as exc:
        status, note = "not sent", f"Not sent: {exc}"
    with con:  # internal mail is not chased by reminders or auto-send
        con.execute("UPDATE chases SET status='internal ' || status WHERE id=? AND status IN ('awaiting reply','draft')", (ref,))
    return actions._record(con, {"id": f"option-{option['id']}", "title": option.get("title") or ""}, "internal", status, by,
                           chase_id=ref, recipient=mail["recipientName"], subject=subject, body=mail["body"], note=note)


def send(con, option, by, *, demo, mail=None):
    """Send the previewed email for an approved option through the T83 send path."""
    from . import actions
    mail = mail or preview(con, option)
    if mail["mode"] == "internal":
        return _send_internal(con, option, mail, by, demo)
    if mail["mode"] != "send":
        return None
    action = {"id": f"option-{option['id']}", "kind": "supplier", "title": option.get("title") or "Supplier request",
              "supplierId": option.get("supplier_id"), "material": option.get("material"), "qty": mail.get("qty") or 0,
              "deadline": option.get("latest_action") or option.get("deadline"), "evidence": option.get("evidence") or [],
              "draft": {"to": mail["to"], "subject": mail["subject"], "body": mail["body"], "language": mail.get("language")}}
    # The person's click is the approval (ONE-CLICK); the T83 path still applies allowlist and guardrails.
    return actions.on_approve(con, action, by, demo=demo, decision={"mode": "ONE_CLICK", "approver": by})
