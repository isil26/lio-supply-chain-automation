"""T83: send path for Action Queue actions (contract in coord/DECISIONS.md).

An action is a dict: id, kind, title, owner_role, person, deadline, eur_at_stake, evidence, approver,
draft, target ('supplier' | 'internal'), plus for supplier actions supplier_id, material, qty and
optionally supplier {name, email, language}. Optional `binding: true` marks a purchase commitment.

- supplier: becomes a normal draft chase (stable id from the action id). Sending reuses the existing
  mail-agent path: allowlist, guardrails, anti-spam (cooldown and duplicate text) and `send()`.
- internal: stored as a prepared message/task (facts and EUR case). Never sent by this module.
  A human hands it over and calls mark_handed_over().
- status: prepared -> sent -> replied -> done. Binding actions need a recorded approver (PP-07).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from . import LANGUAGE, activity, rows, schema as chaser_schema
from . import send as chaser_send
from .guardrails import Guardrails

STATUSES = ("prepared", "sent", "replied", "done")
BINDING_KINDS = {"purchase", "purchase_commitment", "po", "air_freight", "concession", "exception"}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def schema(con):
    chaser_schema(con)
    con.execute("""CREATE TABLE IF NOT EXISTS action_sends (
        action_id TEXT PRIMARY KEY, target TEXT NOT NULL, kind TEXT, status TEXT NOT NULL,
        action TEXT NOT NULL, message TEXT, chase_id TEXT, approved_by TEXT, approved_at TEXT,
        sent_at TEXT, replied_at TEXT, reply_message_id TEXT, done_at TEXT, done_by TEXT, note TEXT,
        updated_at TEXT NOT NULL)""")


def is_binding(action):
    return bool(action.get("binding")) or action.get("kind") in BINDING_KINDS


def _evidence_lines(action):
    ev = action.get("evidence") or []
    return [str(e) for e in ([ev] if isinstance(ev, str) else ev)]


def internal_message(action):
    """Facts and the EUR case for a person inside Soony."""
    eur = action.get("eur_at_stake")
    lines = [f"To: {action.get('person') or action.get('owner_role') or 'owner'}"
             + (f" ({action['owner_role']})" if action.get("owner_role") and action.get("person") else ""),
             f"Subject: {action.get('title', action['id'])}",
             f"Do by: {action.get('deadline') or 'as soon as possible'}"]
    if eur is not None:
        lines.append(f"At stake: EUR {float(eur):,.0f}")
    lines.append(f"Approver: {action.get('approver') or 'not set'}")
    if action.get("draft"):
        draft = action["draft"]
        lines += ["", draft if isinstance(draft, str) else draft.get("body", "")]
    if ev := _evidence_lines(action):
        lines += ["", "Evidence:"] + [f"- {e}" for e in ev]
    return {"to": action.get("person") or action.get("owner_role"), "subject": action.get("title", action["id"]),
            "body": "\n".join(lines), "sent_by_system": False}


def _row(con, action_id):
    row = con.execute("SELECT * FROM action_sends WHERE action_id=?", (action_id,)).fetchone()
    return row


def get(con, action_id):
    schema(con)
    row = _row(con, action_id)
    if not row:
        return None
    out = dict(row)
    out["action"] = json.loads(out["action"])
    out["message"] = json.loads(out["message"]) if out["message"] else None
    return out


def list_actions(con, status=None):
    schema(con)
    q, args = "SELECT action_id FROM action_sends", ()
    if status:
        q, args = q + " WHERE status=?", (status,)
    return [get(con, r[0]) for r in con.execute(q + " ORDER BY rowid", args).fetchall()]


def _supplier(con, action):
    info = dict(action.get("supplier") or {})
    sid = action.get("supplier_id") or info.get("id")
    profile = {}
    try:
        profile = next((r for r in rows(con, "suppliers") if r["supplier_id"] == sid), {})
    except Exception:  # no suppliers table in this store
        pass
    name = info.get("name") or profile.get("name") or sid
    email = info.get("email") or profile.get("contact_email")
    language = info.get("language") or profile.get("preferred_language") or "en"
    if not (sid and email):
        raise ValueError("supplier action needs supplier_id and a supplier email")
    return sid, name, email, language, profile.get("contact_name") or name


def chase_ref(action_id):
    return hashlib.sha256(f"action:{action_id}".encode()).hexdigest()[:10].upper()


def prepare(con, action):
    """Store an action as prepared. Supplier actions also get a draft chase. Idempotent."""
    schema(con)
    for key in ("id", "target"):
        if not action.get(key):
            raise ValueError(f"action needs {key}")
    if action["target"] not in ("supplier", "internal"):
        raise ValueError("target must be 'supplier' or 'internal'")
    existing = _row(con, action["id"])
    if existing:
        return get(con, action["id"])
    chase_id = message = None
    with con:
        if action["target"] == "internal":
            message = internal_message(action)
        else:
            sid, name, email, language, contact = _supplier(con, action)
            draft = action.get("draft")
            subject_default, template = LANGUAGE.get(language, LANGUAGE["en"])
            if isinstance(draft, dict):
                subject, body = draft.get("subject") or subject_default, draft.get("body")
            else:
                subject, body = subject_default, draft
            if not body:
                if not action.get("qty"):
                    raise ValueError("supplier action needs a draft or a qty")
                due = datetime.fromisoformat(action["deadline"]).strftime("%d %b %H:%M") if action.get("deadline") else "launch"
                body = template.format(name=contact, part=action.get("material", ""),
                                       quantity=int(action["qty"]), deadline=due)
            chase_id = chase_ref(action["id"])
            con.execute("""INSERT OR IGNORE INTO chases
                (id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (chase_id, sid, name, email, language, f"[SOONY-{chase_id}] {subject}", "action prepared",
                         action.get("material", ""), int(action.get("qty") or 0), body,
                         action.get("deadline") or ""))
            message = {"to": email, "subject": subject, "body": body, "sent_by_system": True}
        con.execute("""INSERT INTO action_sends(action_id,target,kind,status,action,message,chase_id,updated_at)
            VALUES(?,?,?,?,?,?,?,?)""", (action["id"], action["target"], action.get("kind"), "prepared",
                                         json.dumps(action, ensure_ascii=False), json.dumps(message, ensure_ascii=False),
                                         chase_id, _now()))
        activity(con, "Mail Agent", f"Action {action['id']}: prepared ({action['target']}).", "analysis")
    return get(con, action["id"])


def approve(con, action_id, approved_by):
    """Record who approved. Must be the named approver when the action names one."""
    rec = get(con, action_id)
    if not rec:
        raise ValueError(f"unknown action {action_id}")
    who = (approved_by or "").strip()
    if not who:
        raise PermissionError("approval needs a named person")
    named = (rec["action"].get("approver") or "").strip()
    if named and who.lower() not in named.lower() and named.lower() not in who.lower():
        raise PermissionError(f"approver must be {named}, not {who}")
    with con:
        con.execute("UPDATE action_sends SET approved_by=?, approved_at=?, updated_at=? WHERE action_id=?",
                    (who, _now(), _now(), action_id))
    return get(con, action_id)


def send_supplier(con, action_id, *, demo=False, send=None, now=None):
    """Send an approved supplier action through the mail agent. Returns {id, result}.

    result: sent | blocked (guardrails) | cooldown | duplicate | failed. Raises PermissionError for
    internal actions, missing approval, binding actions without a recorded approver, or a managed case.
    """
    from . import autosend
    from .allowlist import check_recipient
    from .supplier_loop import managed

    rec = get(con, action_id)
    if not rec:
        raise ValueError(f"unknown action {action_id}")
    if rec["target"] != "supplier":
        raise PermissionError("internal actions are never sent by the system")
    action = rec["action"]
    if not rec["approved_by"]:
        raise PermissionError("no recorded approver: refusing to send" + (
            " a binding purchase commitment (PP-07)" if is_binding(action) else ""))
    if is_binding(action) and not (action.get("approver") or "").strip():
        raise PermissionError("binding action has no PP-07 approver on record: refusing to send")
    if rec["status"] != "prepared":
        return {"id": action_id, "result": rec["status"]}
    chase = con.execute("SELECT * FROM chases WHERE id=?", (rec["chase_id"],)).fetchone()
    if managed(chase["supplier_id"], chase["material"]):
        raise PermissionError("this case is handled by the supplier loop")
    address = chase["address"].strip().lower()
    if not demo:
        check_recipient(address)
    if not Guardrails().validate_draft(chase["body"]).ok:
        activity(con, "Mail Agent", f"Action {action_id}: draft blocked by guardrails.", "warning")
        return {"id": action_id, "result": "blocked"}
    if autosend.duplicate_body(con, address, chase["body"]):
        return {"id": action_id, "result": "duplicate"}
    busy = autosend.recent_cases(con, autosend.cooldown_minutes(), now or datetime.now(timezone.utc))
    if (address, chase["material"]) in busy:
        return {"id": action_id, "result": "cooldown"}
    with con:
        con.execute("UPDATE chases SET status='draft' WHERE id=? AND status='action prepared'", (chase["id"],))
    try:
        (send or (lambda c, i: chaser_send(c, i, demo=demo, auto=True)))(con, chase["id"])
    except (PermissionError, ValueError) as exc:
        with con:
            con.execute("UPDATE chases SET status='action prepared' WHERE id=? AND status='draft'", (chase["id"],))
            activity(con, "Mail Agent", f"Action {action_id}: send failed ({exc}).", "warning")
        return {"id": action_id, "result": "failed", "error": str(exc)}
    with con:
        con.execute("UPDATE action_sends SET status='sent', sent_at=?, updated_at=? WHERE action_id=?",
                    (_now(), _now(), action_id))
    return {"id": action_id, "result": "sent"}


def mark_handed_over(con, action_id, by):
    """A person delivered an internal message (no system send). prepared -> sent."""
    rec = get(con, action_id)
    if not rec or rec["target"] != "internal":
        raise ValueError("only internal actions can be handed over")
    if not (by or "").strip():
        raise PermissionError("name the person who handed it over")
    if rec["status"] == "prepared":
        with con:
            con.execute("UPDATE action_sends SET status='sent', sent_at=?, approved_by=coalesce(approved_by,?),"
                        " updated_at=? WHERE action_id=?", (_now(), by, _now(), action_id))
    return get(con, action_id)


def link_replies(con):
    """Mark sent supplier actions as replied when their chase got a real supplier reply."""
    schema(con)
    changed = []
    for rec in list_actions(con, "sent"):
        if not rec["chase_id"]:
            continue
        reply = con.execute("""SELECT external_id, time FROM messages WHERE chase_id=? AND side='in'
            AND coalesce(json_extract(transport,'$.mode'),'') <> 'simulated' ORDER BY id LIMIT 1""",
                            (rec["chase_id"],)).fetchone()
        if reply:
            with con:
                con.execute("UPDATE action_sends SET status='replied', replied_at=?, reply_message_id=?, updated_at=?"
                            " WHERE action_id=?", (reply[1], reply[0], _now(), rec["action_id"]))
                activity(con, "Mail Agent", f"Action {rec['action_id']}: supplier replied.", "analysis")
            changed.append(rec["action_id"])
    return changed


def mark_done(con, action_id, by=None, note=None):
    rec = get(con, action_id)
    if not rec:
        raise ValueError(f"unknown action {action_id}")
    with con:
        con.execute("UPDATE action_sends SET status='done', done_at=?, done_by=?, note=?, updated_at=? WHERE action_id=?",
                    (_now(), by, note, _now(), action_id))
    return get(con, action_id)
