"""SQLite-backed agent trace and dashboard activity projection."""
from __future__ import annotations

import json
import time


def ensure_trace(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS agent_trace (
      id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, model TEXT, step INTEGER,
      tool TEXT, args TEXT, result TEXT, reason TEXT, cost REAL, latency_ms REAL, created_at REAL
    );
    CREATE TABLE IF NOT EXISTS activity (
      id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, action TEXT, type TEXT,
      tool TEXT, input_ref TEXT, output_ref TEXT, status TEXT, citation TEXT, created_at REAL
    );
    """)


def record(db, *, agent, model, step, tool=None, args=None, result=None, reason="",
           cost=0.0, latency_ms=0.0, status="completed"):
    ensure_trace(db)
    now = time.time()
    summary = result if isinstance(result, str) else json.dumps(result, sort_keys=True, default=str)[:1000]
    db.execute("INSERT INTO agent_trace(agent,model,step,tool,args,result,reason,cost,latency_ms,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (agent, model, step, tool, json.dumps(args or {}, default=str), summary, reason, cost, latency_ms, now))
    db.execute("INSERT INTO activity(agent,action,type,tool,status,created_at) VALUES(?,?,?,?,?,?)",
               (agent, f"{tool or 'model'}: {reason}".strip(), "analysis", tool, status, now))
    db.commit()


def activity(db, limit=50):
    ensure_trace(db)
    return [dict(row) for row in db.execute("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,))]
