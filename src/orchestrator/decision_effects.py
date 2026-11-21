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
        if delivery.get("status") == "sent" and str(delivery.get("supplier_id") or delivery.get("kind")) == "internal":
            more = [f"Message sent to {delivery.get('recipient')} via the team mailbox. Waiting for their reply."]
        if delivery.get("status") == "sent" and "Dry run" in (delivery.get("note") or ""):
            more = [more[0].replace(". Waiting", " (demo, nothing left the building). Waiting")]
        lines += more
        email = {"to": delivery.get("recipient"), "subject": delivery.get("subject"), "body": delivery.get("body"),
                 "status": delivery.get("status")}
        thread_id = delivery.get("chase_id")
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
    if mail and mail.get("mode") == "conversation" and mail.get("note"):
        lines.append(mail["note"])
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


OLD_LINES = ("This click records", "No email or order was sent", "It asks for a hold and a quote")


def _clean(effects):
    for effect in effects.values():  # wording from before 22 Nov 00:30: the approver is the decision-maker
        effect["lines"] = [line for line in effect.get("lines", []) if not line.startswith(OLD_LINES)]
    return effects


def _decided(con):
    if not _table(con, "decisions"):
        return {}
    return {row[0]: (row[1], row[2], row[3]) for row in con.execute("SELECT id,status,decided_at,payload FROM decisions")}


def _reply(con, thread_id):
    """Newest answer in the thread the decision's message went to (supplier or colleague)."""
    if not (thread_id and _table(con, "messages")):
        return None
    row = con.execute("SELECT sender, body, time FROM messages WHERE chase_id=? AND side='in' ORDER BY time DESC LIMIT 1",
                      (thread_id,)).fetchone()
    return {"from": row[0], "body": row[1], "at": row[2]} if row else None


def attach(con, options):
    effects = _clean(get_state(con, KEY, {}) or {})
    decided = _decided(con)
    for option in options:
        if option.get("id") in decided and option.get("status") not in (None, "pending"):
            option["decidedAt"] = decided[option["id"]][1]
        if option.get("id") in effects and option.get("status") not in (None, "pending"):
            option["effect"] = dict(effects[option["id"]], reply=_reply(con, effects[option["id"]].get("threadId")))
    return options


def past(con, days=7):
    """Approved / sent-back decisions of the last `days` days, with their full details, newest first.

    Built from the decisions table (full decision payload), so a decision stays listed even after a new
    data drop replaced the option on the open list.
    """
    import json
    from datetime import timedelta
    effects = _clean(get_state(con, KEY, {}) or {})
    since = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for decision_id, (status, decided_at, payload) in _decided(con).items():
        try:
            when = datetime.fromisoformat(str(decided_at).replace("Z", "+00:00"))
            when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if when < since:
            continue
        item = json.loads(payload or "{}")
        effect = effects.get(decision_id)
        out.append({"id": decision_id, "status": status, "decidedAt": when.isoformat(timespec="seconds"),
                    "title": item.get("title"), "owner": item.get("owner"), "kind": item.get("kind"),
                    "recommendation": item.get("recommendation"), "impact": item.get("impact"), "price": item.get("price"),
                    "evidence": [e for e in item.get("evidence", []) if isinstance(e, dict)][:3],
                    "effect": dict(effect, reply=_reply(con, effect.get("threadId"))) if effect else None})
    return sorted(out, key=lambda row: row["decidedAt"], reverse=True)
