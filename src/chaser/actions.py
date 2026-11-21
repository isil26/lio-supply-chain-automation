"""T83: send path for approved actions (mail-agent, for Gülşah).

The action queue (T81, GET /api/actions) ranks do-now actions. When a person approves one,
call `on_approve(con, action, approved_by)`. This module then:

  * supplier action  -> one email in the supplier's language through the normal chaser path
                        (allowlist, guardrails, team Gmail sender). Live mode sends for real
                        (CHASER_REAL_SMTP=1), otherwise it is a dry run.
                        Cases owned by the supplier loop (supplier_loop.CASES) are not
                        mailed twice: they are recorded as "handled by supplier loop".
  * internal action  -> a prepared message to the named person (Katrin Jansen, Raj Patel,
                        Dr. Vogt, Marketing ...) with what to do, by when, the euro case and
                        the evidence. Internal addresses are not on the mail allowlist, so it
                        is prepared, not emailed; the UI shows it with a copy button and the
                        person marks it sent / done.

T94 (IMPORTANT.md section 3): every dispatch first passes `gate()`, which uses the approval engine
(src/decide/approvals.py, T93) when present, else ONE-CLICK. AUTO goes out only under a delegation
confirmed in writing and only for information-only actions; ONE-CLICK waits for a named person;
ESCALATE prepares a message to the next authority and sends nothing; NEVER blocks. The mode,
approver, delegation and SLA are stored per action, and AUTO is logged as "delegation of <name>, record <id>".
`auto_dispatch(con, action)` is the automatic entry point (no person clicked).

`refresh(con)` follows supplier replies: an answer with a quantity and a date, or a document
or booking reference, marks the action done; any other answer marks it "replied" for a look.
`status(con)` returns every dispatched action for the T82 Actions screen.

Action fields read (T81 schema, tolerant to camelCase/snake_case):
  id, kind ("supplier" | "internal"), title, why|detail, person|owner, deadline|dueAt, approver,
  eurAtStake (or copiesStd / copiesCe -> EUR 32 / EUR 120 per copy, docs/NUMBERS.md),
  costEur|price, evidence [str | {text, source}], supplierId, material, qty,
  draft {subject, body, language, to}.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone

from .guardrails import Guardrails

EUR_PER_CE = 120   # missing Collector's copy (Dr. Vogt, recorded by Isil, docs/NUMBERS.md)
EUR_PER_STD = 32   # missing Standard copy
OPEN = ("prepared", "sent", "queued", "replied", "handled by supplier loop", "awaiting approval", "escalated")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get(action, *names, default=None):
    for name in names:
        if action.get(name) not in (None, ""):
            return action[name]
    return default


def schema(con):
    con.execute("""CREATE TABLE IF NOT EXISTS action_sends (
        action_id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, person TEXT, deadline TEXT,
        eur_at_stake REAL, approved_by TEXT, chase_id TEXT, recipient TEXT, subject TEXT, body TEXT,
        status TEXT NOT NULL, note TEXT, created TEXT NOT NULL, updated TEXT NOT NULL, action TEXT NOT NULL)""")
    have = {row[1] for row in con.execute("PRAGMA table_info(action_sends)")}
    for column in ("mode", "approver", "delegation", "sla"):  # T94
        if column not in have:
            con.execute(f"ALTER TABLE action_sends ADD COLUMN {column} TEXT")


def eur_at_stake(action):
    value = _get(action, "eurAtStake", "eur_at_stake")
    if value is not None:
        return float(value)
    std, ce = _get(action, "copiesStd", "copies_std", default=0), _get(action, "copiesCe", "copies_ce", default=0)
    return float(std * EUR_PER_STD + ce * EUR_PER_CE) if (std or ce) else None


def _euro(value):
    return f"EUR {value:,.0f}" if value is not None else "not yet computed"


def _evidence(action):
    lines = []
    for item in _get(action, "evidence", default=[]) or []:
        if isinstance(item, dict):
            text, source = item.get("text") or item.get("quote") or "", item.get("source") or item.get("path") or ""
            lines.append(f"- {text} ({source})" if source else f"- {text}")
        else:
            lines.append(f"- {item}")
    return lines or ["- see the action queue entry"]


def internal_message(action):
    """Plain message for a colleague: what, by when, the euro case, evidence, approver."""
    person = _get(action, "person", "owner", default="team")
    title = _get(action, "title", "what", default="Action")
    eur, cost = eur_at_stake(action), _get(action, "costEur", "cost_eur", "price")
    case = f"At stake if we do nothing: {_euro(eur)}"
    if eur is not None and cost is not None:
        case += f". Cost: {_euro(float(cost))}, so it {'clears' if eur > float(cost) else 'does not clear'} its cost"
    elif cost is not None:
        case += f". Cost: {_euro(float(cost))}"
    elif eur is not None:
        case += " (cost not quoted yet)"
    lines = [f"Hello {person.split(' (')[0]},", "", f"Please: {title}."]
    if why := _get(action, "why", "reason", "detail"):
        lines.append(f"Why: {why}")
    if deadline := _get(action, "deadline", "by", "dueAt"):
        lines.append(f"By: {deadline}")
    lines += [case + ".", "", "Facts:", *_evidence(action)]
    if approver := _get(action, "approver"):
        lines += ["", f"Approval needed from: {approver} (PP-07)."]
    lines += ["", "Please reply when it is done or if something blocks it.", "", "Soony launch team"]
    return f"[ACTION {_get(action, 'id')}] {title}", "\n".join(lines)


def _record(con, action, kind, status, approved_by, **extra):
    now = _now()
    row = {"chase_id": None, "recipient": None, "subject": None, "body": None, "note": None, **extra}
    with con:
        con.execute("""INSERT INTO action_sends(action_id,kind,title,person,deadline,eur_at_stake,approved_by,chase_id,
                       recipient,subject,body,status,note,created,updated,action) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(action_id) DO UPDATE SET status=excluded.status, note=excluded.note,
                       chase_id=coalesce(excluded.chase_id, action_sends.chase_id),
                       recipient=coalesce(excluded.recipient, action_sends.recipient),
                       subject=coalesce(excluded.subject, action_sends.subject),
                       body=coalesce(excluded.body, action_sends.body),
                       approved_by=coalesce(excluded.approved_by, action_sends.approved_by), updated=excluded.updated""",
                    (str(action["id"]), kind, _get(action, "title", "what", default=""), _get(action, "person", "owner"),
                     _get(action, "deadline", "by", "dueAt"), eur_at_stake(action), approved_by, row["chase_id"], row["recipient"],
                     row["subject"], row["body"], status, row["note"], now, now, json.dumps(action, ensure_ascii=False)))
    return get(con, action["id"])


def get(con, action_id):
    schema(con)
    cur = con.execute("SELECT * FROM action_sends WHERE action_id=?", (str(action_id),))
    row = cur.fetchone()
    return dict(zip([c[0] for c in cur.description], row)) if row else None


def _supplier_email(con, action, approved_by, demo):
    from . import activity, schema as chaser_schema, send, supplier_loop, LANGUAGE
    chaser_schema(con)
    supplier_id, material = _get(action, "supplierId", "supplier_id"), _get(action, "material", default="")
    if supplier_loop.managed(supplier_id, material):
        return _record(con, action, "supplier", "handled by supplier loop", approved_by,
                       note="This supplier case runs in the supplier loop; no second email.")
    profile = {}
    try:
        cur = con.execute("SELECT * FROM suppliers WHERE supplier_id=?", (supplier_id,))
        found = cur.fetchone()
        profile = dict(zip([c[0] for c in cur.description], found)) if found else {}
    except Exception:  # suppliers table only exists after ingest
        pass
    draft = _get(action, "draft", default={}) or {}
    address = profile.get("contact_email") or draft.get("to")
    if not address:
        return _record(con, action, "supplier", "blocked", approved_by, note="No supplier email address on file.")
    language = draft.get("language") or profile.get("preferred_language") or "en"
    qty = int(_get(action, "qty", "quantity", default=0) or 0)
    subject, body = draft.get("subject"), draft.get("body")
    if not body:
        subject, template = LANGUAGE.get(language, LANGUAGE["en"])
        body = template.format(name=profile.get("contact_name") or profile.get("name") or "", part=material,
                               quantity=qty, deadline=_get(action, "deadline", default="the cut-off"))
    check = Guardrails().validate_draft(body)
    if not check.ok:
        return _record(con, action, "supplier", "blocked", approved_by, recipient=address, body=body,
                       note="Email failed the information-only check: " + "; ".join(check.errors))
    ref = hashlib.sha256(f"action:{action['id']}".encode()).hexdigest()[:10].upper()
    subject = f"[SOONY-{ref}] {subject or 'Launch supply request'}"
    with con:
        con.execute("""INSERT OR IGNORE INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (ref, supplier_id or "", profile.get("name") or supplier_id or address, address, language, subject,
                     "draft", material, qty, body, _get(action, "deadline", default="")))
        activity(con, "Mail Agent", f"Action {action['id']} approved by {approved_by}: email to {address} prepared.", "analysis")
    common = dict(chase_id=ref, recipient=address, subject=subject, body=body)
    try:
        send(con, ref, demo=demo)
    except ValueError as exc:  # cooldown, missing live settings: the draft stays for the next mail cycle
        return _record(con, action, "supplier", "queued", approved_by, note=f"Not sent yet: {exc}", **common)
    note = "Dry run (demo): nothing left the building." if demo else "Sent from the team mailbox."
    return _record(con, action, "supplier", "sent", approved_by, note=note, **common)


# ---- T94: approval modes (IMPORTANT.md section 3) -------------------------------------------
MODES = ("AUTO", "ONE-CLICK", "ESCALATE", "NEVER")
BINDING = re.compile(r"\b(?:we accept|accepted|purchase order|we (?:hereby )?order|please (?:reserve|book|ship)|"
                     r"zamawiamy|akceptujemy|발주합니다|确认订购)\b", re.I)


def _engine_decision(action):
    """Ask the T93 approval engine (src/decide/approvals.py) when it exists; None if it does not."""
    try:
        from src.decide import approvals
    except ImportError:
        return None
    try:
        return approvals.evaluate(action)
    except TypeError:  # signature not settled yet; fall back to ONE-CLICK rather than guess
        return None


def gate(action, approved_by=None, decision=None):
    """Decide how this action may go out. Returns {mode, approver, delegation, sla, reason}.

    AUTO only with a delegation confirmed in writing and an information-only, reversible action.
    Without an engine decision the default is ONE-CLICK: a named person must approve.
    """
    decision = decision or action.get("approval") or _engine_decision(action) or {}
    mode = str(decision.get("mode") or "ONE-CLICK").upper().replace("_", "-").replace("ONECLICK", "ONE-CLICK")
    if mode not in MODES:
        mode = "ONE-CLICK"
    delegation = decision.get("delegation") or None
    out = {"mode": mode, "approver": decision.get("approver") or _get(action, "approver"),
           "delegation": delegation, "sla": decision.get("sla") or decision.get("dueAt"),
           "escalateTo": decision.get("escalateTo") or decision.get("escalate_to"),
           "reason": decision.get("reason") or ""}
    if mode == "AUTO":
        body = ((_get(action, "draft", default={}) or {}).get("body") or "")
        confirmed = isinstance(delegation, dict) and (delegation.get("confirmed") is True
                                                       or delegation.get("confirmedInWriting") is True)
        binding = bool(action.get("binding")) or bool(BINDING.search(body))
        if not confirmed or binding:
            out.update(mode="ONE-CLICK", reason=("delegation not confirmed in writing" if not confirmed
                                                 else "binding action: needs a person") + "; " + out["reason"])
    return out


def _with_mode(con, action, row, g, approved_by):
    who = approved_by
    if g["mode"] == "AUTO":
        d = g["delegation"]
        who = f'delegation of {d.get("from") or d.get("delegator") or g["approver"]}, record {d.get("id", "?")}'
    with con:
        con.execute("UPDATE action_sends SET mode=?, approver=?, delegation=?, sla=?, approved_by=coalesce(?, approved_by) "
                    "WHERE action_id=?", (g["mode"], g["approver"], json.dumps(g["delegation"]) if g["delegation"] else None,
                                          g["sla"], who, str(action["id"])))
        try:
            from . import activity
            activity(con, "Mail Agent", f'Action {action["id"]}: {g["mode"]} ({who or "no approver yet"}) -> {row["status"]}.',
                     "analysis")
        except Exception:  # activity table only exists once the chaser schema ran
            pass
    return get(con, action["id"])


def on_approve(con, action, approved_by, *, demo=None, decision=None):
    """Dispatch one approved T81 action. Safe to call twice: an action is only sent once.

    approved_by: the person who clicked (ONE-CLICK), or None for an automatic run (only AUTO goes out).
    decision: the approval engine's verdict; looked up from src/decide/approvals.py when omitted.
    """
    schema(con)
    if not action.get("id"):
        raise ValueError("action needs an id")
    if (existing := get(con, action["id"])) and existing["status"] not in ("blocked", "dismissed", "awaiting approval"):
        return existing
    if demo is None:
        demo = os.getenv("CHASER_REAL_SMTP") != "1"
    g = gate(action, approved_by, decision)
    kind = _get(action, "kind", "channel", default="internal")
    supplier = kind == "supplier" or bool(_get(action, "supplierId", "supplier_id"))
    kind = "supplier" if supplier else "internal"
    if g["mode"] == "NEVER":
        row = _record(con, action, kind, "blocked", approved_by,
                      note="Blocked by policy: " + (g["reason"] or "this action is never automatic"))
        return _with_mode(con, action, row, g, approved_by)
    if g["mode"] == "ESCALATE":
        target = g["escalateTo"] or g["approver"] or "the next authority per PP-07"
        subject, body = internal_message(dict(action, person=target))
        row = _record(con, action, kind, "escalated", approved_by, recipient=target, subject="[ESCALATED] " + subject,
                      body=body, note=f"Escalated to {target}. " + g["reason"])
        return _with_mode(con, action, row, g, approved_by)
    if g["mode"] == "ONE-CLICK" and not approved_by:
        subject, body = internal_message(action)
        row = _record(con, action, kind, "awaiting approval", None, recipient=g["approver"], subject=subject, body=body,
                      note=f"Waiting for one click from {g['approver'] or 'the named approver'}. " + g["reason"])
        return _with_mode(con, action, row, g, None)
    if supplier:
        import sqlite3
        con.row_factory = sqlite3.Row  # the chaser send path reads rows by column name
        row = _supplier_email(con, action, approved_by, demo)
    else:
        subject, body = internal_message(action)
        row = _record(con, action, "internal", "prepared", approved_by, recipient=_get(action, "person", "owner"),
                      subject=subject, body=body, note="Ready to copy and send to the named person.")
    return _with_mode(con, action, row, g, approved_by)


def auto_dispatch(con, action, *, demo=None, decision=None):
    """Automatic run: only AUTO actions (confirmed delegation, information-only) go out; others wait or escalate."""
    return on_approve(con, action, None, demo=demo, decision=decision)


def mark(con, action_id, status, note=None):
    """Human updates: 'sent' (internal message passed on), 'done', 'dismissed'."""
    if status not in ("sent", "done", "dismissed"):
        raise ValueError("status must be sent, done or dismissed")
    schema(con)
    with con:
        changed = con.execute("UPDATE action_sends SET status=?, note=coalesce(?, note), updated=? WHERE action_id=?",
                              (status, note, _now(), str(action_id))).rowcount
    if not changed:
        raise ValueError("unknown action")
    return get(con, action_id)


def refresh(con):
    """Follow supplier replies on sent actions. Returns the ids that changed."""
    schema(con)
    changed = []
    for action_id, chase_id in con.execute(
            "SELECT action_id, chase_id FROM action_sends WHERE kind='supplier' AND chase_id IS NOT NULL "
            "AND status IN ('sent','queued','replied')").fetchall():
        chase = con.execute("SELECT status FROM chases WHERE id=?", (chase_id,)).fetchone()
        reply = con.execute("SELECT body, parsed FROM messages WHERE chase_id=? AND side='in' ORDER BY id DESC LIMIT 1",
                            (chase_id,)).fetchone()
        if reply:
            parsed = json.loads(reply[1] or "{}")
            facts = [f"{k}: {parsed[k]['value']}" for k in ("quantity", "stated_time", "tracking", "cost") if k in parsed]
            firm = "tracking" in parsed or parsed.get("attachments") or {"quantity", "stated_time"} <= parsed.keys()
            status = "done" if firm else "replied"
            note = ("Supplier answered: " + ", ".join(facts)) if facts else "Supplier answered; please read the reply."
        elif chase and chase[0] in ("awaiting reply", "sending"):
            status, note = "sent", None
        else:
            continue
        with con:
            if con.execute("UPDATE action_sends SET status=?, note=coalesce(?, note), updated=? WHERE action_id=? AND status!=?",
                           (status, note, _now(), action_id, status)).rowcount:
                changed.append(action_id)
    return changed


def status(con):
    schema(con)
    refresh(con)
    cur = con.execute("""SELECT action_id, kind, title, person, deadline, eur_at_stake, approved_by, recipient, subject,
                         body, status, note, updated, mode, approver, delegation, sla FROM action_sends ORDER BY coalesce(eur_at_stake,0) DESC, created""")
    names = [c[0] for c in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


# First actions from coord/OPEN_TASKS.md T81, for the demo command only. Copies are from the 18:20 break-even
# table (docs/VOGT_BREAKEVEN.md, decision A) and are stale after the 19:25 drop until T88 recomputes them.
EXAMPLES = [
    {"id": "A-dock-slot", "kind": "internal", "title": "Book a Hamburg dock slot and early customs for the 28,000-card air lot",
     "why": "AWB 020-48113256 lands Sun 12:00; every hour of unloading delay costs packed copies.",
     "person": "Katrin Jansen (site lead DC-HAM)", "deadline": "Sun 22 Nov 10:00", "approver": "Katrin Jansen (deputy Raj Patel)",
     "copiesStd": 21216, "copiesCe": 3133, "evidence": [{"text": "Decision A in the break-even table", "source": "docs/VOGT_BREAKEVEN.md"}]},
    {"id": "statue-exception", "kind": "internal", "title": "Decide the statue lot exception",
     "person": "Dr. Maren Vogt", "approver": "Daniel Okafor plus the Head of Procurement (policy section 6)",
     "evidence": [{"text": "Statue lot concession approvers", "source": "docs/AUTHORIZATIONS.md"}]},
    {"id": "sleeve-question", "kind": "internal", "title": "Confirm which sleeve revision is approved for print",
     "person": "Marketing", "evidence": [{"text": "Release Gate: CMP-GAM-004 rev B vs rev C", "source": "src/decide/release_gate.py"}]},
]


def _cli(argv=None):
    import argparse
    import sqlite3
    parser = argparse.ArgumentParser(prog="python3 -m src.chaser.actions", description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=("demo", "list"))
    parser.add_argument("--db", default=os.getenv("SOONY_DB", "store/soony.sqlite"))
    args = parser.parse_args(argv)
    con = sqlite3.connect(":memory:" if args.command == "demo" else args.db)
    con.row_factory = sqlite3.Row
    if args.command == "demo":
        from .mailenv import load_team_mail_env
        load_team_mail_env()
        os.environ.setdefault("CHASER_SENDER", "launch-team@example.invalid")
        for action in EXAMPLES:
            on_approve(con, action, "demo user", demo=True)
    for row in status(con):
        print(f"[{row['status']}] {row['title']}  ->  {row['person'] or row['recipient']}  ({_euro(row['eur_at_stake'])})")
        if args.command == "demo" and row["body"]:
            print("    " + row["body"].replace("\n", "\n    "))


if __name__ == "__main__":
    _cli()
