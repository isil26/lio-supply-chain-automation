"""The last useful time to dispatch a queued supplier email."""

import json
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


QUEUED = ("draft", "loop draft", "recovery draft", "awaiting click")
HAMBURG = ZoneInfo("Europe/Berlin")


class DeadlineHandoff(ValueError):
    """Dispatch was stopped and Procurement owns the next decision."""


def timestamp(value):
    if not value:
        return None
    try:
        if len(value) == 10:
            # Older threads stored a Hamburg calendar date without an hour.
            return datetime.combine(date.fromisoformat(value) + timedelta(days=1), time.min, HAMBURG)
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=HAMBURG)
    except (ValueError, TypeError, OverflowError):
        return None


def current_plan(con):
    """Read launch and fallback windows from the last published forecast."""
    from src.decide import decisions

    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='state'").fetchone():
        return None, {}, {}
    snapshot = {key: json.loads(value) for key, value in con.execute(
        "SELECT key,value FROM state WHERE key IN ('truth','options')"
    )}
    truth = snapshot.get("truth") or {}
    shifts = truth.get("shifts") or []
    cutoff = min(filter(None, (timestamp(truth.get("deadline")),
                               timestamp(shifts[-1][1]) if shifts else None)), default=None)
    statuses = decisions(con)
    by_material = {}
    for option in snapshot.get("options") or []:
        material = option.get("material")
        status = statuses.get(option.get("id"), option.get("status"))
        if not material or option.get("approval_block") or status not in (None, "pending", "review"):
            continue
        if latest := timestamp(option.get("latest_action")):
            by_material[material] = min(latest, by_material.get(material, latest))
    return cutoff, by_material, truth.get("parts") or {}


def record_if_expired(con, chase, clock, plan, *, message_id=None):
    """Run inside the dispatch transaction. Return a durable handoff reason if blocked."""
    if chase["status"] == "escalated":
        return handoff_reason(con, chase["id"])
    if chase["status"] not in QUEUED and not message_id:
        return None

    cutoff, fallback, parts = plan
    deadline = timestamp(chase["deadline"])
    if deadline:
        deadline = min(filter(None, (deadline, cutoff, fallback.get(chase["material"]))))
        if clock < deadline:
            return None
        reason = f"The supplier decision deadline passed at {deadline.astimezone(HAMBURG):%d %b %Y %H:%M %Z}."
    else:
        reason = "The queued supplier email has no usable decision deadline."

    gap = parts.get(chase["material"], {}).get("shortfall")
    detail = f"{chase['supplier']} / {chase['material']}. {reason} Email was not sent."
    if gap is not None:
        detail += f" Latest forecast: {gap:,} units uncovered."
    detail += " Procurement should review the supplier thread and any remaining recovery options."
    con.execute("UPDATE chases SET status='escalated' WHERE id=?", (chase["id"],))
    if message_id:
        # The SMTP session opened, but send_message has not been called.
        con.execute("DELETE FROM messages WHERE chase_id=? AND external_id=?", (chase["id"], message_id))
        con.execute("UPDATE chases SET due_at=NULL,message_id=NULL WHERE id=?", (chase["id"],))
    con.execute("INSERT INTO chaser_deadline_handoffs(chase_id,deadline,detail) VALUES(?,?,?)",
                (chase["id"], deadline.isoformat() if deadline else None, detail))
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='action_sends'").fetchone():
        con.execute("""UPDATE action_sends SET status='escalated',note=?,updated=?
                       WHERE chase_id=? AND kind='supplier' AND status='queued'""",
                    (detail, clock.isoformat(), chase["id"]))
    con.execute("INSERT INTO activity(time,agent,action,type) VALUES(?,?,?,'warning')",
                (clock.isoformat(), "Supplier Chaser", f"SOONY-{chase['id']}: {detail}"))
    return detail


def expire_queued(con, clock):
    """Hand off expired items even when cooldown, approval or a batch limit prevents a claim."""
    from .deals import is_decision_draft
    from .supplier_loop import managed

    results = []
    with con:
        if not con.in_transaction:
            con.execute("BEGIN IMMEDIATE")
        plan = current_plan(con)
        drafts = con.execute("SELECT * FROM chases WHERE status IN (?,?,?,?) ORDER BY rowid", QUEUED).fetchall()
        for chase in drafts:
            if (chase["status"] == "draft" and managed(chase["supplier_id"], chase["material"])
                    and not is_decision_draft(con, chase["id"])):
                continue
            if record_if_expired(con, chase, clock, plan):
                results.append(dict(id=chase["id"], supplier=chase["supplier"], result="escalated"))
    return results


def expire_transport_claim(con, chase_id, message_id):
    with con:
        con.execute("BEGIN IMMEDIATE")
        chase = con.execute("SELECT * FROM chases WHERE id=? AND message_id=? AND status='sending'",
                            (chase_id, message_id)).fetchone()
        if not chase:
            raise ValueError("The email is no longer claimed for dispatch")
        reason = record_if_expired(con, chase, datetime.now(timezone.utc), current_plan(con), message_id=message_id)
    if reason:
        raise DeadlineHandoff(reason)


def handoffs(con):
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='chaser_deadline_handoffs'").fetchone():
        yield from con.execute("""SELECT c.id,c.material,c.supplier,c.parent_thread_id,c.based_on_reply_id,h.deadline,h.detail
                                  FROM chaser_deadline_handoffs h JOIN chases c ON c.id=h.chase_id""")


def handoff_reason(con, chase_id):
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='chaser_deadline_handoffs'").fetchone():
        row = con.execute("SELECT detail FROM chaser_deadline_handoffs WHERE chase_id=?", (chase_id,)).fetchone()
        return row[0] if row else None
