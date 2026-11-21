"""Background autonomy runner and its persisted run/trace projection."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from .team import build_team


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_object(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _citations(value: Any) -> list[dict]:
    found = []
    if isinstance(value, dict):
        if value.get("file") or value.get("source_file") or value.get("source"):
            found.append({
                "file": value.get("file") or value.get("source_file") or value.get("source"),
                "page": value.get("page"),
                "quote": value.get("quote"),
                "sheet": value.get("sheet"),
                "row": value.get("row"),
            })
        for key in ("citations", "citation", "evidence", "sources"):
            found.extend(_citations(value.get(key)))
    elif isinstance(value, list):
        for item in value:
            found.extend(_citations(item))
    elif isinstance(value, str):
        try:
            found.extend(_citations(json.loads(value)))
        except json.JSONDecodeError:
            pass
    unique = []
    for item in found:
        if item and item not in unique:
            unique.append(item)
    return unique


def _trace_steps(rows: list[dict]) -> list[dict]:
    steps = []
    for row in rows:
        args = _json_object(row.get("args"))
        result = _json_object(row.get("result"))
        result_text = str(row.get("result") or "")
        try:
            parsed_result = json.loads(result_text)
        except (json.JSONDecodeError, TypeError):
            parsed_result = row.get("result")
        citations = _citations(parsed_result)
        result_summary = result_text
        if len(result_summary) > 240:
            result_summary = result_summary[:237] + "..."
        args_summary = json.dumps(args, ensure_ascii=False, sort_keys=True) if args else ""
        if len(args_summary) > 240:
            args_summary = args_summary[:237] + "..."
        steps.append({
            "agent": row.get("agent") or "unknown",
            "tool": row.get("tool") or "",
            "args_summary": args_summary,
            "result_summary": result_summary,
            "reason": row.get("reason") or "",
            "cost": float(row.get("cost") or 0),
            "latency": float(row.get("latency_ms") or 0),
            "citations": citations,
            "status": row.get("status") or "completed",
        })
    return steps


class AutonomyLoop:
    """Run one bounded agent team per distinct event without blocking the pipeline."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        enabled: bool | None = None,
        budget_usd: float | None = None,
        timer_minutes: float | None = None,
        team_factory: Callable[..., Any] = build_team,
    ):
        self.db_path = str(db_path)
        self.enabled = (os.getenv("SOONY_AGENTS") == "1") if enabled is None else bool(enabled)
        self.budget_usd = max(0.0, float(
            budget_usd if budget_usd is not None
            else os.getenv("SOONY_AGENT_BUDGET_USD", "0.10")
        ))
        self.timer_minutes = max(0.0, float(
            timer_minutes if timer_minutes is not None
            else os.getenv("SOONY_AGENT_TIMER_MINUTES", "30")
        ))
        self.team_factory = team_factory
        self._stop = threading.Event()
        self._last_timer = time.monotonic()
        self._threads: set[threading.Thread] = set()
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self):
        con = sqlite3.connect(self.db_path, timeout=30)
        con.row_factory = sqlite3.Row
        return con

    def _ensure_schema(self):
        with self._connect() as con:
            con.execute(
                """CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    event TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    cost REAL NOT NULL DEFAULT 0,
                    started REAL,
                    finished REAL,
                    harness_report TEXT,
                    trace_json TEXT NOT NULL DEFAULT '[]',
                    reason TEXT,
                    trace_start INTEGER NOT NULL DEFAULT 0
                )"""
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_hash ON agent_runs(event_hash)")
            con.execute(
                """CREATE TABLE IF NOT EXISTS agent_trace (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, model TEXT, step INTEGER,
                    tool TEXT, args TEXT, result TEXT, reason TEXT, cost REAL, latency_ms REAL,
                    input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
                    created_at REAL, status TEXT
                )"""
            )

    def _event_hash(self, event: dict) -> str:
        return hashlib.sha256(_json(event).encode("utf-8")).hexdigest()

    def submit(self, event: dict | str, *, force: bool = False) -> dict:
        """Queue an event and return immediately with its persisted run id."""
        if isinstance(event, str):
            event = {"kind": "drop", "summary": event, "changed_files": []}
        if not isinstance(event, dict):
            raise ValueError("event must be an object")
        event = {
            "kind": str(event.get("kind") or "drop"),
            "changed_files": list(event.get("changed_files") or []),
            "summary": str(event.get("summary") or ""),
        }
        if not self.enabled or os.getenv("SOONY_AGENTS") == "0" or self._stop.is_set():
            return {"ok": False, "status": "offline", "reason": "agents disabled", "event": event}
        digest = self._event_hash(event)
        with self._connect() as con:
            if not force:
                previous = con.execute(
                    "SELECT id,status FROM agent_runs WHERE event_hash=? ORDER BY started DESC LIMIT 1",
                    (digest,),
                ).fetchone()
                if previous:
                    return {"ok": True, "status": "deduped", "run": previous["id"], "event": event}
            run_id = uuid.uuid4().hex
            con.execute(
                "INSERT INTO agent_runs(id,event,event_hash,status,started) VALUES(?,?,?,'queued',?)",
                (run_id, _json(event), digest, time.time()),
            )
        thread = threading.Thread(target=self._worker, args=(run_id, event), daemon=True,
                                  name=f"soony-agent-{run_id[:8]}")
        with self._lock:
            self._threads.add(thread)
        thread.start()
        return {"ok": True, "status": "queued", "run": run_id, "event": event}

    def _worker(self, run_id: str, event: dict):
        started = time.monotonic()
        try:
            team = self.team_factory(self.db_path)
            with self._connect() as con:
                con.execute("UPDATE agent_runs SET status='running' WHERE id=?", (run_id,))
                trace_start = int(con.execute("SELECT COALESCE(MAX(id), 0) FROM agent_trace").fetchone()[0])
            # Keep each specialist within the per-cycle cap; the harness still
            # evaluates the complete persisted trace after the team finishes.
            for agent in team.agents.values():
                agent.budget_usd = min(float(agent.budget_usd), self.budget_usd)
            result = team.run_event(_json(event))
            with self._connect() as con:
                trace = [dict(row) for row in con.execute(
                    "SELECT agent,tool,args,result,reason,cost,latency_ms,"
                    "input_tokens,output_tokens,created_at FROM agent_trace WHERE id>? ORDER BY id",
                    (trace_start,)
                )]
                cost = sum(float(row.get("cost") or 0) for row in trace)
                report = result.get("harness") if isinstance(result, dict) else None
                status = "blocked by harness" if report and not report.get("ok", False) else "completed"
                if cost > self.budget_usd:
                    status = "budget_exceeded"
                con.execute(
                    "UPDATE agent_runs SET status=?,cost=?,finished=?,harness_report=?,trace_json=?,reason=?,trace_start=? WHERE id=?",
                    (status, cost, time.time(), _json(report or {}),
                     _json(trace), result.get("live_failed", {}).get("reason") if isinstance(result, dict) else None,
                     trace_start, run_id),
                )
        except Exception as exc:
            with self._connect() as con:
                con.execute(
                    "UPDATE agent_runs SET status='error',finished=?,reason=? WHERE id=?",
                    (time.time(), f"{exc.__class__.__name__}: {exc}", run_id),
                )
        finally:
            with self._lock:
                self._threads.discard(threading.current_thread())
            _ = started

    def stop(self):
        """Disable new work; an in-flight model request is bounded by the runtime timeout."""
        self.enabled = False
        self._stop.set()
        return {"ok": True, "status": "stopped"}

    def tick(self) -> dict | None:
        """Submit the chaser timer event when its configured interval elapses."""
        if self.timer_minutes <= 0 or time.monotonic() - self._last_timer < self.timer_minutes * 60:
            return None
        self._last_timer = time.monotonic()
        return self.submit({"kind": "timer", "changed_files": [], "summary": "Advance open supplier chaser threads"})

    def runs(self, limit: int = 20) -> list[dict]:
        limit = max(1, min(int(limit), 100))
        with self._connect() as con:
            rows = con.execute(
                "SELECT id,event,status,cost,started,finished,harness_report,trace_json,reason "
                "FROM agent_runs ORDER BY COALESCE(started,0) DESC LIMIT ?", (limit,)
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            event = json.loads(item["event"])
            item["event"] = event.get("summary") or event.get("kind") or "agent run"
            item["harness"] = json.loads(item.pop("harness_report") or "{}")
            trace = json.loads(item.pop("trace_json") or "[]")
            item["step_count"] = len(trace)
            item["summary"] = item.pop("reason") or ""
            result.append(item)
        return result

    def trace(self, run_id: str) -> dict:
        with self._connect() as con:
            row = con.execute(
                "SELECT id,event,status,cost,started,finished,harness_report,trace_json,reason "
                "FROM agent_runs WHERE id=?", (run_id,)
            ).fetchone()
        if not row:
            raise KeyError("unknown agent run")
        item = dict(row)
        item["event"] = json.loads(item["event"])
        item["harness"] = json.loads(item.pop("harness_report") or "{}")
        raw_trace = json.loads(item.pop("trace_json") or "[]")
        item["steps"] = _trace_steps(raw_trace)
        item["trace"] = raw_trace
        item["summary"] = item.pop("reason") or ""
        item["step_count"] = len(item["steps"])
        with self._connect() as con:
            approvals = []
            tables = {row[0] for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if "agent_approvals" in tables:
                for approval in con.execute(
                    "SELECT id,agent,tool,args,status FROM agent_approvals WHERE status='pending' ORDER BY id"
                ):
                    args = _json_object(approval["args"])
                    approvals.append({
                        "id": str(approval["id"]),
                        "title": args.get("title") or args.get("file") or approval["tool"],
                        "detail": args.get("detail") or args.get("reason") or args.get("rationale")
                                  or "Human decision required before action.",
                        "agent": approval["agent"],
                        "tool": approval["tool"],
                    })
        item["approvals_pending"] = approvals
        return item
