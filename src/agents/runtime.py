"""Minimal ReAct runtime with closed tools, budgets and human gates."""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable

from .llm_adapter import FakeLLM, HTTPAdapter, LLMError
from .trace import ensure_trace, record


@dataclass
class Tool:
    name: str
    function: Callable[..., Any]
    schema: dict | None = None
    needs_approval: bool = False

    def validate(self, args):
        schema = self.schema or {}
        required = schema.get("required", [])
        unknown = set(args) - set(schema.get("properties", args))
        if any(name not in args for name in required) or unknown:
            raise ValueError(f"invalid arguments for {self.name}")
        for name, spec in schema.get("properties", {}).items():
            if name in args and spec.get("type") == "integer" and not isinstance(args[name], int):
                raise ValueError(f"{name} must be integer")


def _tool(item):
    if isinstance(item, Tool):
        return item
    if callable(item):
        return Tool(getattr(item, "__name__", "tool"), item)
    return Tool(item["name"], item["function"], item.get("schema"), item.get("needs_approval", False))


class Agent:
    def __init__(self, name, system_prompt, tools=(), model=None, max_steps=3, budget_usd=1.0,
                 llm=None, timeout_seconds=60):
        self.name, self.system_prompt, self.model = name, system_prompt, model
        self.tools = {_tool(t).name: _tool(t) for t in tools}
        self.max_steps, self.budget_usd, self.llm = max_steps, budget_usd, llm or HTTPAdapter()
        self.timeout_seconds = timeout_seconds

    def run(self, task, db=None):
        db = db or sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        ensure_trace(db)
        started, messages, total_cost = time.monotonic(), [{"role": "user", "content": task}], 0.0
        for step in range(1, self.max_steps + 1):
            if time.monotonic() - started > self.timeout_seconds:
                return {"status": "timeout", "reason": "wall-clock budget exceeded"}
            try:
                response = self.llm.chat(messages, [self._spec(t) for t in self.tools.values()],
                                         self.system_prompt, self.model)
                calls = response.get("tool_calls", [])
                usage = response.get("usage", {})
                cost = (usage.get("input_tokens", 0) + usage.get("output_tokens", 0)) * 0.000001
                total_cost += cost
                if total_cost > self.budget_usd:
                    return {"status": "budget_exceeded", "reason": "token budget exceeded"}
            except Exception as exc:
                record(db, agent=self.name, model=self.model, step=step, reason=str(exc), status="error")
                if step == 1:
                    messages.append({"role": "user", "content": "Return a valid response with tool_calls as an array."})
                    continue
                return {"status": "error", "reason": str(exc)}
            if not calls:
                text = response.get("text", "")
                record(db, agent=self.name, model=self.model, step=step, result=text, reason="final")
                return {"status": "completed", "text": text, "cost": total_cost}
            for call in calls:
                name, args = call.get("name"), call.get("arguments", {})
                tool = self.tools.get(name)
                try:
                    if not tool:
                        raise ValueError(f"tool not allowed: {name}")
                    tool.validate(args)
                    if tool.needs_approval:
                        db.execute("CREATE TABLE IF NOT EXISTS agent_approvals (id INTEGER PRIMARY KEY, agent TEXT, tool TEXT, args TEXT, status TEXT)")
                        db.execute("INSERT INTO agent_approvals(agent,tool,args,status) VALUES(?,?,?,'pending')",
                                   (self.name, name, json.dumps(args)))
                        db.commit()
                        result = {"status": "pending_approval"}
                    else:
                        result = tool.function(**args)
                    reason = call.get("reason", "model selected tool")
                    record(db, agent=self.name, model=self.model, step=step, tool=name, args=args,
                           result=result, reason=reason)
                except Exception as exc:
                    result = {"error": str(exc)}
                    record(db, agent=self.name, model=self.model, step=step, tool=name, args=args,
                           result=result, reason="tool rejected", status="error")
                messages.extend([{"role": "assistant", "content": response.get("text", "")},
                                 {"role": "tool", "name": name, "content": json.dumps(result, default=str)}])
        return {"status": "max_steps", "reason": "step budget exceeded", "cost": total_cost}

    @staticmethod
    def _spec(tool):
        return {"type": "function", "function": {"name": tool.name, "description": tool.name,
                "parameters": tool.schema or {"type": "object", "properties": {}}}}


class Team:
    def __init__(self, agents, db_path=":memory:"):
        self.agents = {agent.name: agent for agent in agents}
        self.db = sqlite3.connect(db_path)
        self.db.row_factory = sqlite3.Row
        ensure_trace(self.db)
        self.db.executescript("""CREATE TABLE IF NOT EXISTS agent_state
            (key TEXT PRIMARY KEY, value TEXT, author TEXT, ts REAL);
            CREATE TABLE IF NOT EXISTS agent_mailbox
            (id INTEGER PRIMARY KEY, sender TEXT, recipient TEXT, task TEXT, result TEXT, status TEXT, ts REAL);""")
        self.db.commit()

    def delegate(self, sender, agent, task):
        if agent not in self.agents:
            raise ValueError(f"unknown agent: {agent}")
        self.db.execute("INSERT INTO agent_mailbox(sender,recipient,task,status,ts) VALUES(?,?,?,?,?)",
                        (sender, agent, task, "running", time.time()))
        self.db.commit()
        result = self.agents[agent].run(task, self.db)
        self.db.execute("UPDATE agent_mailbox SET result=?, status=? WHERE id=(SELECT max(id) FROM agent_mailbox)",
                        (json.dumps(result, default=str), result.get("status", "completed")))
        self.db.commit()
        return result

    def put(self, key, value, author):
        self.db.execute("INSERT OR REPLACE INTO agent_state VALUES(?,?,?,?)",
                        (key, json.dumps(value, default=str), author, time.time()))
        self.db.commit()

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM agent_state WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default
