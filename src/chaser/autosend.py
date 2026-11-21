"""Automatic sending for mail-agent (Gülşah's decision, 21 Nov 2026: no human approval per email).

Runs once per orchestrator cycle in live mode only (real SMTP on, not --demo replay):
  1. prepare: reminder drafts for silent suppliers, negotiation drafts for the best supplier(s);
  2. send: every current draft chase, oldest first.

Safety that stays on:
  - recipients must be on the supplier allowlist (allowlist.py), checked again in send();
  - every body must pass the guardrails (no binding commitment, no maximum price, no deadline
    slack, no mention of other suppliers) or it is skipped and logged;
  - at most CHASER_AUTO_MAX_PER_CYCLE emails per cycle (default 6) and one email per supplier
    address per CHASER_AUTO_COOLDOWN_MIN minutes (default 60);
  - emails are information requests; purchase commitments still follow PP-07.
Turn it off with CHASER_AUTO_SEND=0.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from .guardrails import Guardrails


def enabled(demo=False):
    return (not demo and os.getenv("CHASER_AUTO_SEND", "1") != "0"
            and os.getenv("CHASER_REAL_SMTP") == "1")


def _recent_addresses(con, minutes, now):
    since = (now - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    rows = con.execute("""SELECT DISTINCT lower(c.address) FROM messages m JOIN chases c ON c.id = m.chase_id
                          WHERE m.side = 'out' AND m.time >= ?""", (since,)).fetchall()
    return {row[0] for row in rows}


def run(con, *, send=None, now=None, prepare=True):
    """Prepare and send drafts. Returns a list of {id, supplier, result}."""
    from . import activity as _activity
    from . import send as chaser_send

    def activity(con, agent, text, kind):
        with con:
            _activity(con, agent, text, kind)

    send = send or chaser_send
    now = now or datetime.now(timezone.utc)
    if prepare:
        try:
            from .followup import due_reminders
            due_reminders(con, now, save=True)
        except Exception as exc:  # never block sending on a planning error
            activity(con, "Mail Agent", f"Reminder planning skipped ({exc.__class__.__name__}).", "warning")
        try:
            from .negotiate import compare
            row = con.execute("SELECT deadline FROM chases LIMIT 1").fetchone()
            if row:
                compare(con, row[0], save=True)
        except Exception as exc:
            activity(con, "Mail Agent", f"Negotiation planning skipped ({exc.__class__.__name__}).", "warning")
    limit = int(os.getenv("CHASER_AUTO_MAX_PER_CYCLE", "6"))
    busy = _recent_addresses(con, int(os.getenv("CHASER_AUTO_COOLDOWN_MIN", "60")), now)
    drafts = con.execute("SELECT id, supplier, address, body FROM chases WHERE status = 'draft' ORDER BY rowid").fetchall()
    results = []
    for chase_id, supplier, address, body in drafts:
        if len([r for r in results if r["result"] == "sent"]) >= limit:
            break
        if address.lower() in busy:
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
        busy.add(address.lower())
        activity(con, "Mail Agent", f"{supplier}: sent automatically.", "sent")
        results.append({"id": chase_id, "supplier": supplier, "result": "sent"})
    return results
