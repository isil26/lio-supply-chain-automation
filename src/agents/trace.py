"""SQLite-backed agent trace and dashboard activity projection."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone


def _redact_text(value):
    text = str(value)
    for name in ("SOONY_LLM_KEY", "SOONY_LLM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        secret = os.getenv(name)
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def ensure_trace(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS agent_trace (
      id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, model TEXT, step INTEGER,
      tool TEXT, args TEXT, result TEXT, reason TEXT, cost REAL, latency_ms REAL,
      input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0, created_at REAL
    );
    CREATE TABLE IF NOT EXISTS activity (
      id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, action TEXT, type TEXT,
      tool TEXT, input_ref TEXT, output_ref TEXT, status TEXT, citation TEXT, created_at REAL
    );
    """)
    # An older database may already hold these tables with fewer columns (CREATE IF NOT EXISTS never upgrades them).
    wanted = {
        "agent_trace": {"agent": "TEXT", "model": "TEXT", "step": "INTEGER", "tool": "TEXT", "args": "TEXT",
                        "result": "TEXT", "reason": "TEXT", "cost": "REAL", "latency_ms": "REAL",
                        "input_tokens": "INTEGER DEFAULT 0", "output_tokens": "INTEGER DEFAULT 0",
                        "created_at": "REAL", "status": "TEXT"},
        "activity": {"time": "TEXT", "agent": "TEXT", "action": "TEXT", "type": "TEXT", "tool": "TEXT", "input_ref": "TEXT",
                     "output_ref": "TEXT", "status": "TEXT", "citation": "TEXT", "created_at": "REAL"},
    }
    for table, columns in wanted.items():
        have = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        for name, kind in columns.items():
            if name not in have:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")


def record(db, *, agent, model, step, tool=None, args=None, result=None, reason="",
           cost=0.0, latency_ms=0.0, status="completed", input_tokens=0, output_tokens=0):
    ensure_trace(db)
    now = time.time()
    summary = result if isinstance(result, str) else json.dumps(result, sort_keys=True, default=str)
    if isinstance(result, dict) and len(summary) > 8000:
        summary = json.dumps({"preview": summary[:1000], "citations": result.get("citations", [])[:8]},
                             ensure_ascii=False, default=str)
    summary = _redact_text(summary)
    args_json = _redact_text(json.dumps(args or {}, default=str))
    reason = _redact_text(reason)
    columns = {row[1] for row in db.execute("PRAGMA table_info(agent_trace)").fetchall()}
    for name, definition in (
        ("input_tokens", "INTEGER DEFAULT 0"),
        ("output_tokens", "INTEGER DEFAULT 0"),
    ):
        if name not in columns:
            db.execute(f"ALTER TABLE agent_trace ADD COLUMN {name} {definition}")
    db.execute("""INSERT INTO agent_trace
        (agent,model,step,tool,args,result,reason,cost,latency_ms,input_tokens,output_tokens,created_at,status)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
               (agent, model or os.getenv("SOONY_AGENT_MODEL"), step, tool, args_json, summary, reason,
                cost, latency_ms, input_tokens, output_tokens, now, status))
    db.execute("INSERT INTO activity(time,agent,action,type,tool,status,created_at) VALUES(?,?,?,?,?,?,?)",
               (datetime.now(timezone.utc).isoformat(timespec="seconds"), agent, f"{tool or 'model'}: {reason}".strip(), "analysis", tool, status, now))
    db.commit()


def activity(db, limit=50):
    ensure_trace(db)
    return [dict(row) for row in db.execute("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,))]
