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
"""
from __future__ import annotations

import os
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
        activity(con, "Mail Agent", f"{supplier}: sent automatically.", "sent")
        results.append({"id": chase_id, "supplier": supplier, "result": "sent"})
    return results
