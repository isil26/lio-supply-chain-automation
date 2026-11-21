"""Automatic sending for mail-agent (Gülşah's decision, 21 Nov 2026: no human approval per email).

Runs once per orchestrator cycle in live mode only (real SMTP on, not --demo replay):
  1. prepare: reminder drafts for silent suppliers, an answer to every unanswered supplier reply,
     negotiation drafts for the best supplier(s);
  2. send: every current draft chase, oldest first.

Safety that stays on:
  - recipients must be on the supplier allowlist (allowlist.py), checked again in send();
  - every body must pass the guardrails (no binding commitment, no maximum price, no deadline
    slack, no mention of other suppliers) or it is skipped and logged;
  - no cap per cycle (Gülşah, 21 Nov: suppliers are simulated). Set CHASER_AUTO_MAX_PER_CYCLE to cap;
  - distinct components can contact the same supplier in one cycle;
  - an unanswered request cools down the same recipient and component for
    CHASER_AUTO_COOLDOWN_MIN minutes (default 30, zero disables the wait);
  - the same text is never sent twice to the same address automatically;
  - emails are information requests; purchase commitments still follow PP-07.
Turn it off with CHASER_AUTO_SEND=0.

Send modes (IMPORTANT.md section 3 and 6, decided 21 Nov 20:50):
  AUTO       information-only request (status questions, reminders, documents, quotes,
             answers to replies). Sent without a click.
  ONE-CLICK  binding wording (accepting a price or offer, an order, a reservation on our
             terms). Sent only after a named person clicked: Approve on the offers table
             (deals.decided_by), an approved action (action_sends.approved_by), or
             approve() below (POST /api/mail/<id>/approve). Without a click the draft is
             held as 'awaiting click' and logged once.
Every send is logged with its mode, e.g. "AUTO (information request)" or
"ONE-CLICK approved by Felix".
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from functools import partial

from .guardrails import Guardrails


def enabled(demo=False):
    return (not demo and os.getenv("CHASER_AUTO_SEND", "1") != "0"
            and os.getenv("CHASER_REAL_SMTP") == "1")


def cooldown_minutes():
    return max(0, int(os.getenv("CHASER_AUTO_COOLDOWN_MIN", "30")))


def recent_cases(con, minutes, now):
    """Find recipient and component pairs with recent unanswered live mail."""
    if not minutes:
        return set()
    since = (now - timedelta(minutes=minutes)).isoformat()
    return {tuple(row) for row in con.execute("""
        SELECT DISTINCT lower(trim(c.address)), c.material
        FROM messages sent JOIN chases c ON c.id = sent.chase_id
        WHERE sent.side = 'out' AND julianday(sent.time) >= julianday(?)
          AND coalesce(json_extract(sent.transport, '$.mode'), '') <> 'dry_run'
          AND coalesce(json_extract(sent.transport, '$.status'), '') <> 'failed'
          AND NOT EXISTS (
            SELECT 1 FROM messages reply
            WHERE reply.chase_id = sent.chase_id AND reply.side = 'in'
              AND julianday(reply.time) >= julianday(sent.time)
              AND coalesce(json_extract(reply.transport, '$.mode'), '') <> 'simulated'
              AND coalesce(nullif(json_extract(reply.transport, '$.inReplyTo'), ''), sent.external_id) = sent.external_id
          )
    """, (since,))}


def duplicate_body(con, address, body):
    return con.execute("""
        SELECT 1 FROM messages m JOIN chases c ON c.id=m.chase_id
        WHERE m.side='out' AND lower(trim(c.address))=? AND m.body=?
          AND coalesce(json_extract(m.transport, '$.mode'), '') <> 'dry_run'
        LIMIT 1
    """, (address, body)).fetchone() is not None


# Wording that asks the supplier to act on a commitment from us. Our information-only
# templates say "this is not an order", so plain words like "order" are not enough.
BINDING = [re.compile(p, re.I) for p in (
    r"\bplease reserve\b", r"\bwe would like to go ahead\b", r"\bgo ahead with (?:the|your|this) (?:offer|order)\b",
    r"\bwe (?:hereby )?accept\b", r"\baccept your (?:offer|quote|price)\b", r"\bwe (?:hereby )?order\b",
    r"\bconfirm (?:the|our) (?:order|purchase)\b", r"\bplease (?:ship|proceed with (?:the|our) order)\b",
    r"\bwe confirm (?:exw|pickup|the price)\b",
    r"prosimy o rezerwacj", r"\bakceptujemy\b", r"\bzamawiamy\b", r"chcemy kontynuowa",
    r"확보해 주시기", r"진행하고자", r"수락합니다", r"주문합니다",
    r"预留", r"我们接受", r"希望推进", r"我们订购",
)]
HELD = "awaiting click"


def binding(body):
    """Return the binding phrase found in an email body, or None for an information request."""
    for pattern in BINDING:
        if match := pattern.search(body or ""):
            return match.group(0)
    return None


def _approvals_schema(con):
    con.execute("""CREATE TABLE IF NOT EXISTS send_approvals (
        chase_id TEXT PRIMARY KEY, approved_by TEXT NOT NULL, approved_at TEXT NOT NULL, prior_status TEXT)""")


def approver(con, chase_id):
    """Who clicked for this email, if anyone: offers table, approved action or a held-mail click."""
    _approvals_schema(con)
    queries = ("SELECT approved_by FROM send_approvals WHERE chase_id=?",
               "SELECT decided_by FROM deals WHERE email_id=? AND decided_by IS NOT NULL",
               "SELECT approved_by FROM action_sends WHERE chase_id=? AND status <> 'dismissed'")
    for sql in queries:
        try:
            row = con.execute(sql, (chase_id,)).fetchone()
        except Exception:  # table not created yet in this database
            continue
        if row and row[0]:
            return row[0]
    return None


def mode(con, chase_id, body):
    """{'mode': 'AUTO'|'ONE-CLICK', 'approved_by': name or None, 'phrase': binding phrase or None}."""
    who = approver(con, chase_id)
    phrase = binding(body)
    if who or phrase:
        return {"mode": "ONE-CLICK", "approved_by": who, "phrase": phrase}
    return {"mode": "AUTO", "approved_by": None, "phrase": None}


def label(info):
    if info["mode"] == "AUTO":
        return "AUTO (information request)"
    return f"ONE-CLICK approved by {info['approved_by']}" if info["approved_by"] else "ONE-CLICK needed"


def held(con):
    """Emails waiting for a click, newest first."""
    _approvals_schema(con)
    rows = con.execute(f"SELECT id, supplier, address, subject, body, material FROM chases WHERE status='{HELD}' ORDER BY rowid DESC").fetchall()
    return [{"id": r[0], "supplier": r[1], "address": r[2], "subject": r[3], "body": r[4], "material": r[5],
             "reason": binding(r[4])} for r in rows]


def approve(con, chase_id, by):
    """One click on a held email: record who approved it and put it back in the send queue."""
    if not by or not str(by).strip():
        raise ValueError("a named approver is required")
    _approvals_schema(con)
    row = con.execute("SELECT status FROM chases WHERE id=?", (chase_id,)).fetchone()
    if not row:
        raise KeyError(chase_id)
    prior = con.execute("SELECT prior_status FROM send_approvals WHERE chase_id=?", (chase_id,)).fetchone()
    restore = (prior[0] if prior and prior[0] else "draft") if row[0] == HELD else row[0]
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with con:
        con.execute("""INSERT INTO send_approvals(chase_id, approved_by, approved_at, prior_status) VALUES(?,?,?,?)
                       ON CONFLICT(chase_id) DO UPDATE SET approved_by=excluded.approved_by, approved_at=excluded.approved_at""",
                    (chase_id, str(by).strip(), stamp, restore))
        con.execute("UPDATE chases SET status=? WHERE id=? AND status=?", (restore, chase_id, HELD))
    return {"id": chase_id, "approved_by": str(by).strip(), "status": restore}


def _hold(con, chase_id, status, supplier, phrase):
    _approvals_schema(con)
    with con:
        con.execute("""INSERT INTO send_approvals(chase_id, approved_by, approved_at, prior_status) VALUES(?, '', '', ?)
                       ON CONFLICT(chase_id) DO UPDATE SET prior_status=excluded.prior_status""", (chase_id, status))
        con.execute("UPDATE chases SET status=? WHERE id=? AND status=?", (HELD, chase_id, status))
        from . import activity as _activity
        _activity(con, "Mail Agent", f"{supplier}: ONE-CLICK needed before sending (binding wording: \"{phrase}\").", "warning")


def run(con, *, send=None, now=None, prepare=True):
    """Prepare and send drafts. Returns a list of {id, supplier, result}."""
    from . import activity as _activity
    from . import send as chaser_send
    from . import deals, mail_plan
    from .supplier_loop import managed

    def activity(con, agent, text, kind):
        with con:
            _activity(con, agent, text, kind)

    send = send or partial(chaser_send, auto=True)
    now = now or datetime.now(timezone.utc)
    if prepare:
        try:
            from .followup import due_reminders
            due_reminders(con, now, save=True)
        except Exception as exc:  # never block sending on a planning error
            activity(con, "Mail Agent", f"Reminder planning skipped ({exc.__class__.__name__}).", "warning")
        try:
            from .followup import answer_replies
            answer_replies(con, save=True, now=now)
        except Exception as exc:
            activity(con, "Mail Agent", f"Reply answering skipped ({exc.__class__.__name__}).", "warning")
        try:
            row = con.execute("SELECT deadline FROM chases LIMIT 1").fetchone()
            if row:
                deals.sync(con, row[0], now=now)
        except Exception as exc:
            activity(con, "Mail Agent", f"Offer table update skipped ({exc.__class__.__name__}).", "warning")
        try:
            from .negotiate import compare
            row = con.execute("SELECT deadline FROM chases LIMIT 1").fetchone()
            if row:
                compare(con, row[0], save=True, now=now, use_thread_deadlines=True)
        except Exception as exc:
            activity(con, "Mail Agent", f"Negotiation planning skipped ({exc.__class__.__name__}).", "warning")
    limit = int(os.getenv("CHASER_AUTO_MAX_PER_CYCLE", "0")) or None
    minutes = cooldown_minutes()
    busy = recent_cases(con, minutes, now)
    drafts = con.execute("""
        SELECT id,supplier,address,body,supplier_id,material,status FROM chases
        WHERE status IN ('draft','recovery draft') ORDER BY status='recovery draft' DESC,rowid
    """).fetchall()
    results = []
    for chase_id, supplier, address, body, supplier_id, material, status in drafts:
        if status == "draft":
            try:
                decision = deals.check_draft(con, chase_id)
                if not decision:
                    if managed(supplier_id, material):
                        continue
                    draft = con.execute("SELECT * FROM chases WHERE id=?", (chase_id,)).fetchone()
                    mail_plan.check_draft(con, draft)
            except ValueError:
                with con:
                    con.execute("UPDATE chases SET status='superseded draft' WHERE id=? AND status='draft'", (chase_id,))
                results.append({"id": chase_id, "supplier": supplier, "result": "superseded"})
                continue
        if limit and len([r for r in results if r["result"] == "sent"]) >= limit:
            break
        address = address.strip().lower()
        case = (address, material)
        if case in busy:
            continue
        if duplicate_body(con, address, body):
            with con:
                con.execute("UPDATE chases SET status='duplicate' WHERE id=? AND status=?", (chase_id, status))
            results.append({"id": chase_id, "supplier": supplier, "result": "duplicate"})
            continue
        info = mode(con, chase_id, body)
        if info["mode"] == "ONE-CLICK" and not info["approved_by"]:
            _hold(con, chase_id, status, supplier, info["phrase"])
            results.append({"id": chase_id, "supplier": supplier, "result": "held", "mode": "ONE-CLICK"})
            continue
        check = Guardrails().validate_draft(body)
        if not check.ok:
            activity(con, "Mail Agent", f"{supplier}: not sent automatically ({'; '.join(check.errors)}).", "warning")
            results.append({"id": chase_id, "supplier": supplier, "result": "blocked"})
            continue
        try:
            send(con, chase_id)
        except (PermissionError, ValueError) as exc:
            activity(con, "Mail Agent", f"{supplier}: automatic send failed ({exc}).", "warning")
            results.append({"id": chase_id, "supplier": supplier, "result": "failed"})
            continue
        if minutes:
            busy.add(case)
        activity(con, "Mail Agent", f"{supplier}: sent, {label(info)}.", "sent")
        results.append({"id": chase_id, "supplier": supplier, "result": "sent", "mode": info["mode"]})
    return results
