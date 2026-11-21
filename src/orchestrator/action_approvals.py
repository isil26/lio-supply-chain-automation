"""Bridge the queue, PP-07 approval engine and guarded mail dispatcher."""

import os

from src.chaser import activity
from src.chaser import actions as delivery
from src.decide import approvals
from src.decide.actions import mark_action

CATEGORIES = {
    "CMP-GAM-001": "Game Media",
    "CMP-GAM-003": "Print & Packaging",
    "CMP-GAM-004": "Print & Packaging",
    "CMP-GAM-008": "Print & Packaging",
    "CMP-GAM-010": "Collector's Items",
}


def policy_input(action):
    """Authorize the documented action, keeping internal exposure out of supplier mail."""
    kind = action.get("approvalKind")
    if kind is None:
        kind = "supplier_info_request" if action["kind"] == "supplier" else "internal_message"
    result = {
        "id": action["id"], "kind": kind, "title": action["title"], "site": "DC-HAM",
        "category": CATEGORIES.get(action.get("material")), "evidence": action["evidence"],
        "value_eur": action.get("costEur"), "binding": bool(action.get("binding")),
    }
    if kind == "supplier_info_request":
        result["draft_body"] = (action.get("draft") or {}).get("body", "")
    return result


def project(con, actions, *, include_history, demo=False):
    """Project policy without registering reviews or running delivery on a read."""
    pending = {}
    if include_history and con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='approvals_pending'").fetchone():
        pending = {row["action_id"]: row for row in con.execute(
            "SELECT action_id,requested_at,due_at,status FROM approvals_pending")}
    delegations = approvals.load_delegations()
    for action in actions:
        policy = policy_input(action)
        row = pending.get(action["id"])
        if row and row["status"] == "pending":
            policy["requested_at"] = row["requested_at"]
        ev = approvals.evaluate(policy, delegations=delegations, allow_simulated=demo)
        ev.pop("evaluated_at")
        action["approval"] = ev
        action["mode"] = ev["mode"]
        action["approverName"] = (ev["approver"] or {}).get("name")
        action["slaMinutes"] = ev["sla_minutes"]
        action["delegationId"] = ev["delegation_id"]
        if row:
            action["approvalStatus"] = row["status"]
            action["approvalDueAt"] = row["due_at"]
    return actions


def _mail_decision(ev, delegations):
    delegation = next((row for row in delegations if row["id"] == ev["delegation_id"]), None)
    return {
        "mode": ev["mode"], "approver": (ev["approver"] or {}).get("name"),
        "reason": ev["reason"], "sla": ev["sla_minutes"],
        "delegation": {
            "id": delegation["id"], "from": delegation["delegator"],
            "confirmed": delegation.get("confirmed_in_writing") is True,
        } if delegation else None,
    }


def register(con, queue, *, automatic):
    """Start SLAs on current proposals and dispatch only independently confirmed AUTO decisions."""
    con.executescript(approvals.SCHEMA)
    active = {action["id"] for action in queue}
    pending = {row["action_id"]: row["status"] for row in con.execute(
        "SELECT action_id,status FROM approvals_pending")}
    retired = [(key,) for key in pending.keys() - active if pending[key] == "pending"]
    if retired:
        with con:
            con.executemany("UPDATE approvals_pending SET status='superseded' WHERE action_id=?", retired)
    delegations = approvals.load_delegations()
    auto_logged = {tuple(row) for row in con.execute(
        "SELECT action_id,delegation_id FROM approvals_log WHERE mode='AUTO'")}
    for action in queue:
        if action["status"] != "pending":
            continue
        policy = policy_input(action)
        ev = action["approval"]
        if ev["mode"] == approvals.AUTO:
            ev = approvals.evaluate(policy, delegations=delegations)
            verdict = _mail_decision(ev, delegations)
            if (automatic and os.getenv("CHASER_AUTO_SEND") != "0"
                    and delivery.gate(action, decision=verdict)["mode"] == "AUTO"):
                key = action["id"], ev["delegation_id"]
                if key not in auto_logged:
                    logged = approvals.submit(con, policy, delegations=delegations)
                    if logged["mode"] != approvals.AUTO:
                        continue
                delivery.auto_dispatch(con, action, demo=False, decision=verdict)
        elif pending.get(action["id"]) in (None, "superseded"):
            approvals.submit(con, policy, delegations=delegations)
    for escalation in approvals.escalate_due(con, delegations=delegations):
        activity(con, "Approvals", escalation["reminder"], "analysis")


def approve(con, action, actor, note, *, demo):
    """Record a named click and pass the checked route to T83."""
    ev = action["approval"]
    policy = policy_input(action)
    if ev["mode"] == approvals.NEVER and policy["kind"] != "quality_exception":
        raise ValueError(ev["reason"])
    primary = (ev["approver"] or {}).get("name")
    names = {primary, *ev["required_signers"], *(signer["name"] for signer in ev["co_signers"])}
    if policy["kind"] == "dock_slot" and primary == "Katrin Jansen":
        names.add("Raj Patel")
    if actor not in names:
        raise PermissionError("This decision requires the listed approver, deputy or co-signer.")
    con.executescript(approvals.SCHEMA)
    # A manual click has its own audit record, even when a delegation is available.
    row = con.execute("SELECT status FROM approvals_pending WHERE action_id=?", (action["id"],)).fetchone()
    if row is None or row["status"] == "superseded":
        approvals.submit(con, policy, delegations=())
    if row is None or row["status"] != "approved":
        reviewed = approvals.record_human_decision(con, action["id"], actor, "approve", note or "")
        if reviewed["status"] != "approved":
            return {"status": "pending", "waitingFor": reviewed["waiting_for"]}
    if policy["kind"] == "quality_exception":
        # The review records the signers. Quality release remains a separate operation.
        mark_action(con, action["id"], "reviewed", actor, note)
        return {"status": "reviewed"}
    verdict = _mail_decision(ev, ())
    # Keep the original route in the approval audit. T83 receives the completed human decision.
    if ev["mode"] in {approvals.AUTO, approvals.ESCALATE}:
        verdict["mode"] = approvals.ONE_CLICK
    return delivery.on_approve(con, action, actor, demo=demo, decision=verdict)


def close(con, action_id, state):
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='approvals_pending'").fetchone():
        with con:
            con.execute("UPDATE approvals_pending SET status=? WHERE action_id=?", (state, action_id))
