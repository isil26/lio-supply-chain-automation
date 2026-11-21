#!/usr/bin/env python3
"""Export allowlisted evidence from an owner-identified T38b SQLite range."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


ROLES = {"triage", "analyst", "verifier", "planner", "chaser"}
TOOLS = {
    "delegate", "get_readiness", "list_shortfalls", "whatif", "supplier_history",
    "search_documents", "get_document", "list_shipments", "get_po", "compare_sources",
    "breakeven", "draft_email", "send_email", "parse_reply", "propose_option",
    "escalate_to_human", "request_review",
}
GATED = {"send_email", "propose_option", "escalate_to_human", "request_review"}
STATUSES = {"completed", "error", "timeout", "budget_exceeded", "max_steps", "running"}
MODEL = "gpt-4.1-mini"
REPORTED = {"cost_usd": 0.057892, "input_tokens": 130117, "output_tokens": 3653}
PENDING_APPROVAL = json.dumps({"status": "pending_approval"}, sort_keys=True)


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def step(row):
    status = row["status"] if row["status"] in STATUSES else None
    if row["tool"] in GATED and row["gated_result"]:
        phase = "pending_approval"
    elif status == "completed" and row["tool"] not in GATED:
        phase = "returned"
    elif status == "error":
        phase = "error_recorded"
    else:
        phase = "unknown"
    return {
        "source_row": row["id"], "agent": row["agent"], "tool": row["tool"], "step": row["step"],
        "phase": phase, "recorded_status": status, "recorded_at": timestamp(row["created_at"]),
        "latency_ms": row["latency_ms"] if (row["latency_ms"] or 0) > 0 else None,
    }


def export(con, first, last, mailbox):
    usage = con.execute("""
        SELECT COUNT(*) AS rows,
               COUNT(CASE WHEN model = ? THEN 1 END) AS matching_model_rows,
               COUNT(CASE WHEN model IS NULL THEN 1 END) AS unspecified_model_rows,
               ROUND(COALESCE(SUM(cost),0),6) AS cost_usd,
               COALESCE(SUM(input_tokens),0) AS input_tokens,
               COALESCE(SUM(output_tokens),0) AS output_tokens
        FROM agent_trace WHERE id BETWEEN ? AND ?
    """, (MODEL, first, last)).fetchone()
    if not usage["rows"]:
        raise ValueError("No trace rows within the supplied range")
    if usage["matching_model_rows"] + usage["unspecified_model_rows"] != usage["rows"]:
        raise ValueError("The supplied range contains a conflicting stored model")
    events = con.execute("""
        SELECT t.id,t.agent,t.tool,t.step,t.created_at,t.latency_ms,
               t.result = ? AS gated_result,
               (SELECT CASE WHEN COUNT(*)=1 THEN MIN(a.status) END FROM activity a
                WHERE a.agent=t.agent AND a.tool=t.tool AND a.created_at=t.created_at
                  AND a.type='analysis') AS status
        FROM agent_trace t WHERE t.id BETWEEN ? AND ? AND t.tool IS NOT NULL ORDER BY t.id
    """, (PENDING_APPROVAL, first, last)).fetchall()
    steps = [step(row) for row in events if row["agent"] in ROLES and row["tool"] in TOOLS]
    handoffs = []
    if mailbox:
        for row in con.execute("""SELECT id,sender,recipient,status,ts FROM agent_mailbox
                                  WHERE id BETWEEN ? AND ? ORDER BY id""", mailbox):
            if row["sender"] in ROLES and row["recipient"] in ROLES:
                handoffs.append({"source_row": row["id"], "from": row["sender"], "to": row["recipient"],
                                 "recorded_status": row["status"] if row["status"] in STATUSES else None,
                                 "recorded_at": timestamp(row["ts"])})
    totals = {key: usage[key] for key in REPORTED}
    return {
        "schema_version": 1, "coverage": "owner_bounded_sqlite",
        "source": {"trace_rows_inclusive": [first, last], "mailbox_rows_inclusive": mailbox},
        "reported_model": MODEL, "matching_model_rows": usage["matching_model_rows"],
        "unspecified_model_rows": usage["unspecified_model_rows"],
        "aggregate_usage": totals, "matches_reported_usage": totals == REPORTED,
        "steps": steps, "handoffs": handoffs, "omitted_tool_rows": len(events) - len(steps),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("first_trace_row", type=int)
    parser.add_argument("last_trace_row", type=int)
    parser.add_argument("--mailbox-rows", metavar=("FIRST", "LAST"), nargs=2, type=int)
    args = parser.parse_args()
    bounds = [args.first_trace_row, args.last_trace_row]
    for first, last in filter(None, [bounds, args.mailbox_rows]):
        if first < 1 or last < first:
            parser.error("row bounds must be positive and ordered")
    source = args.database.resolve(strict=True)
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        con.execute("BEGIN")
        try:
            data = export(con, *bounds, args.mailbox_rows)
        except ValueError as error:
            parser.exit(1, f"{error}\n")
        except sqlite3.Error:
            parser.exit(1, "Could not read the legacy SQLite recording schema.\n")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
