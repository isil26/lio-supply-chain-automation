"""What an Approve click on an Actions card actually did, in plain words (gülşah-agent, 21 Nov).

Gülşah approved "Secure art book stock" and only saw "Approved". An option approval records the
team's go-ahead; it does not by itself email a supplier or place a PO. This module writes down,
at click time, what happened and what happens next, so the card can show it:

  {"at": ISO time, "by": name|None, "sent": bool, "lines": [str, ...], "threadId": chase id|None}

Stored in state key "decisionEffects" (option id -> effect); dashboard() attaches it as option["effect"].
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.chaser import supplier_loop
from src.ingest.store import get_state, save_state

BERLIN = ZoneInfo("Europe/Berlin")
KEY = "decisionEffects"


def _clock(iso):
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(BERLIN).strftime("%a %H:%M")
    except (TypeError, ValueError):
        return ""


def _table(con, name):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _supplier_name(con, supplier_id):
    if supplier_id and _table(con, "suppliers"):
        row = con.execute("SELECT name FROM suppliers WHERE supplier_id=?", (supplier_id,)).fetchone()
        if row:
            return row[0]
    return None


def _latest_thread(con, supplier_id, material):
    """Newest chase for this supplier and part that actually went out (or was answered)."""
    if not (supplier_id and _table(con, "chases")):
        return None
    return con.execute("""
        SELECT c.id, c.address, c.status, max(m.time) AS last_time,
               sum(m.side='out') AS sent, sum(m.side='in') AS replies
        FROM chases c JOIN messages m ON m.chase_id = c.id
        WHERE c.supplier_id=? AND c.material=? GROUP BY c.id ORDER BY last_time DESC LIMIT 1
    """, (supplier_id, material or "")).fetchone()


def _delivery_lines(delivery):
    status = delivery.get("status")
    who = delivery.get("recipient") or "the supplier"
    if status == "sent":
        return [f"Email sent to {who}. Waiting for their reply."], True
    if status == "replied":
        return [f"{who} replied. Open the conversation to read it."], True
    if status == "done":
        return [f"Done: {delivery.get('note') or 'the supplier confirmed.'}"], True
    if status == "prepared":
        return [f"A ready message for {who} is prepared; pass it on and mark it sent."], False
    if status == "queued":
        return [f"Email to {who} is queued and goes out with the next mail round."], False
    if status == "awaiting approval":
        return [f"Waiting for one click from {delivery.get('approver') or 'the named approver'}."], False
    return [delivery.get("note") or f"Status: {status}."], False


def describe(con, option, status, by=None, queue=None, *, auto=None, delivery=None, mail=None):
    """Build the effect for one option decision. `queue` = current T81 actions (with delivery)."""
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    who = f" by {by}" if by else ""
    if status == "review":
        return {"at": at, "by": by, "sent": False, "threadId": None,
                "lines": [f"Sent back for review{who} at {_clock(at)}. Nothing was sent or ordered."]}
    head = auto or f"Approved by {by or 'the team'} at {_clock(at)}."
    lines, sent, thread_id = [head], False, None
    supplier_id, material = option.get("supplier_id"), option.get("material")
    follow = next((a for a in (queue or []) if a.get("optionId") == option.get("id")), None)
    email = None
    if delivery:  # this click sent (or tried to send) the supplier email
        more, sent = _delivery_lines(delivery)
        if delivery.get("status") == "sent" and "Dry run" in (delivery.get("note") or ""):
            more = [more[0].replace("Email sent", "Email sent (demo, nothing left the building)")]
        lines += more
        email = {"to": delivery.get("recipient"), "subject": delivery.get("subject"), "body": delivery.get("body"),
                 "status": delivery.get("status")}
        thread_id = delivery.get("chase_id")
        if sent:
            lines.append("It asks for a hold and a quote; it is not an order. "
                         f"Before any PO: {option.get('threshold') or option.get('owner') or 'its approver signs'}.")
    elif follow and follow.get("delivery"):
        more, sent = _delivery_lines(follow["delivery"])
        lines += more
    elif mail and mail.get("mode") == "conversation" and mail.get("body"):
        email = {"to": mail.get("to"), "subject": mail.get("subject"), "body": mail.get("body"), "status": "ongoing"}
    thread = None if thread_id else _latest_thread(con, supplier_id, material)
    name = _supplier_name(con, supplier_id) or "the supplier"
    if thread:
        thread_id = thread["id"] if hasattr(thread, "keys") else thread[0]
        replies = thread["replies"] if hasattr(thread, "keys") else thread[5]
        last = _clock(thread["last_time"] if hasattr(thread, "keys") else thread[3])
        if supplier_loop.managed(supplier_id, material):
            lines.append(f"The email conversation with {name} runs on its own (mail agent). "
                         f"Last message {last}; {'they have replied' if replies else 'no reply yet'}.")
        else:
            lines.append(f"Latest email with {name}: {last}; {'they have replied' if replies else 'no reply yet'}.")
    if not sent:
        if option.get("request_only"):
            lines.append("This click records the team's go-ahead. It does not place an order by itself. "
                         f"Still needed: {option.get('threshold') or option.get('owner') or 'its approver'}.")
        else:
            lines.append(f"No email or order was sent by this click. Next: {option.get('owner') or 'the owner'} acts on it.")
    if follow and not delivery and not follow.get("delivery") and follow.get("status") == "pending":
        lines.append(f"Follow-up in Actions: “{follow.get('title')}”.")
    return {"at": at, "by": by, "sent": sent, "lines": lines, "threadId": thread_id, "email": email}


def record(con, option, status, by=None, queue=None, *, auto=None, delivery=None, mail=None):
    effect = describe(con, option, status, by, queue, auto=auto, delivery=delivery, mail=mail)
    effects = get_state(con, KEY, {}) or {}
    effects[option["id"]] = effect
    with con:
        save_state(con, KEY, effects)
    return effect


def attach(con, options):
    effects = get_state(con, KEY, {}) or {}
    for option in options:
        if option.get("id") in effects and option.get("status") not in (None, "pending"):
            option["effect"] = effects[option["id"]]
    return options
