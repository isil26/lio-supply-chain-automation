"""T40 Triage, Analyst, Verifier, Planner and Chaser team."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .llm_adapter import FakeLLM, HTTPAdapter
from .prompts import ANALYST_PROMPT, CHASER_PROMPT, PLANNER_PROMPT, ROLE_TOOLS, TRIAGE_PROMPT, VERIFIER_PROMPT
from .runtime import Agent, Team, Tool
from .tools import all_tools
from .trace import activity


def _registry_tools(db_path: str | Path, allowed: Iterable[str]) -> list[Tool]:
    allowed = set(allowed)
    result = []
    for item in all_tools(db_path):
        if item["name"] not in allowed:
            continue
        name = item["name"]
        schema = item["input_schema"]

        def handler(fn=item["handler"], **kwargs):
            return fn(kwargs)

        result.append(Tool(name, handler, schema, needs_approval=item["needs_approval"],
                           description=item["description"]))
    return result


def verify_claims(claims: Iterable[str], evidence: Iterable[dict]) -> dict:
    """Accept a claim only if a source quote or document name supports it."""
    evidence = list(evidence)
    accepted = []
    rejected = []
    for claim in claims:
        text = str(claim).strip()
        if not text:
            continue
        matched = False
        for source in evidence:
            quote = str(source.get("quote") or "").strip().casefold()
            file_name = str(source.get("file") or source.get("source") or "").strip().casefold()
            if quote and quote in text.casefold():
                matched = True
            elif file_name and file_name in text.casefold():
                matched = True
        (accepted if matched else rejected).append({
            "claim": text,
            "status": "accepted" if matched else "rejected",
            "reason": "matching source evidence" if matched else "no matching source quote",
        })
    return {"accepted": [x for x in accepted if x["status"] == "accepted"],
            "rejected": [x for x in rejected if x["status"] == "rejected"]}


class AgentTeam(Team):
    def __init__(self, agents, db_path=":memory:", llm=None):
        super().__init__(agents, db_path)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(activity)").fetchall()}
        time_column = next((row for row in self.db.execute("PRAGMA table_info(activity)").fetchall()
                            if row[1] == "time"), None)
        if time_column and time_column[4] is None:
            rows = [dict(row) for row in self.db.execute(
                "SELECT id,time,agent,action,type,tool,input_ref,output_ref,status,citation,created_at FROM activity"
            ).fetchall()]
            self.db.execute("""CREATE TABLE activity_team_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                time TEXT NOT NULL DEFAULT '',
                agent TEXT, action TEXT, type TEXT,
                tool TEXT, input_ref TEXT, output_ref TEXT, status TEXT, citation TEXT,
                created_at REAL
            )""")
            for row in rows:
                self.db.execute(
                    """INSERT INTO activity_team_new
                       (id,time,agent,action,type,tool,input_ref,output_ref,status,citation,created_at)
                       VALUES (:id,:time,:agent,:action,:type,:tool,:input_ref,:output_ref,:status,:citation,:created_at)""",
                    row,
                )
            self.db.execute("DROP TABLE activity")
            self.db.execute("ALTER TABLE activity_team_new RENAME TO activity")
            columns = {row[1] for row in self.db.execute("PRAGMA table_info(activity)").fetchall()}
        for name, definition in (
            ("tool", "TEXT"),
            ("input_ref", "TEXT"),
            ("output_ref", "TEXT"),
            ("status", "TEXT"),
            ("citation", "TEXT"),
            ("created_at", "REAL"),
        ):
            if name not in columns:
                self.db.execute(f"ALTER TABLE activity ADD COLUMN {name} {definition}")
        self.db.commit()
        self.llm = llm
        self.rounds = 0

    def run_event(self, event: str) -> dict:
        """Triage an event; fall back to a fixed specialist order if no model plan exists."""
        event_lower = event.casefold()
        triage = self.agents["triage"]
        triage_result = triage.run(event, self.db)
        before = self.db.execute("SELECT count(*) FROM agent_mailbox").fetchone()[0]

        mailbox_before = before
        # A model can delegate specialists through the triage tool.
        if mailbox_before <= self.db.execute("SELECT count(*) FROM agent_mailbox").fetchone()[0] and self.rounds == 0:
            pass

        results = {}
        results["triage"] = triage_result

        if triage_result.get("status") in {"error", "timeout", "budget_exceeded"}:
            results["live_failed"] = {
                "reason": triage_result.get("reason", "live triage model failed"),
            }
            results["verified"] = self._verification_summary(event_lower)
            results["trace"] = activity(self.db, 100)
            results["pending_approvals"] = [
                dict(row) for row in self.db.execute(
                    "SELECT * FROM agent_approvals WHERE status='pending' ORDER BY id"
                ).fetchall()
            ]
            return results

        # Fixed, honest fallback: no LLM response means deterministic specialist order.
        if not self.db.execute(
            "SELECT 1 FROM agent_mailbox WHERE recipient != 'triage' LIMIT 1"
        ).fetchone():
            results.update(self._fixed_fallback(event_lower))

        results["verified"] = self._verification_summary(event_lower)
        results["trace"] = activity(self.db, 100)
        results["pending_approvals"] = [
            dict(row) for row in self.db.execute(
                "SELECT * FROM agent_approvals WHERE status='pending' ORDER BY id"
            ).fetchall()
        ]
        return results

    def _fixed_fallback(self, event_lower: str) -> dict:
        results = {}
        if "german" in event_lower or "notice" in event_lower:
            results["analyst"] = self.delegate("triage", "analyst",
                                               "Search documents for the unseen notice and flag the review if facts are incomplete.")
            results["verifier"] = self.delegate("triage", "verifier",
                                                "Verify only cited notice facts; reject unsupported claims.")
            results["planner"] = self.delegate("triage", "planner",
                                               "Do not move the forecast. Propose no option until a human reviews the notice.")
            results["chaser"] = self.delegate("triage", "chaser",
                                              "Request human review of the German notice; do not draft or send supplier email.")
        elif "statue" in event_lower or "pune" in event_lower or "quality" in event_lower:
            results["analyst"] = self.delegate("triage", "analyst",
                                               "Compare the statue quality hold and identify the cited shortfall.")
            results["verifier"] = self.delegate("triage", "verifier",
                                                "Verify the quality-hold claim against inspection and release documents.")
            results["planner"] = self.delegate("triage", "planner",
                                               "Check Plan B assumptions and escalate because Supplier Quality/Category Lead release is required.")
            results["chaser"] = self.delegate("triage", "chaser",
                                              "Escalate Pune review to a human; do not treat the statue lot as released.")
        else:
            results["analyst"] = self.delegate("triage", "analyst",
                                               "Report readiness, shortfalls and source citations for the launch event.")
            results["verifier"] = self.delegate("triage", "verifier",
                                                "Independently verify every shortage claim against matching source quotes.")
            results["planner"] = self.delegate("triage", "planner",
                                               "Check Plan B assumptions and preserve unknown cost per missing copy.")
            results["chaser"] = self.delegate("triage", "chaser",
                                              "For the cited art-book issue, draft a guarded R0/R1 supplier request and create pending approval.")
        return results

    def _verification_summary(self, event_lower: str) -> dict:
        evidence = []
        try:
            tool = next(item for item in all_tools(self.db_path) if item["name"] == "search_documents")
            result = tool["handler"]({"query": "art book" if "art" in event_lower else "launch"})
            evidence = result.get("citations", [])
        except Exception:
            evidence = []
        claim = "launch shortage requires cited source evidence"
        return verify_claims([claim, "unsupported supplier guarantee"], evidence)


def build_team(db_path="store/soony.db", llm=None) -> AgentTeam:
    db_path = str(db_path)
    llm = llm or HTTPAdapter()

    team_ref = {"team": None}

    def delegate_tool(sender):
        def delegate(agent: str, task: str):
            if agent not in {"analyst", "verifier", "planner", "chaser"}:
                raise ValueError("unknown specialist")
            return team_ref["team"].delegate(sender, agent, task)
        return Tool(
            "delegate",
            delegate,
            {"type": "object",
             "properties": {"agent": {"type": "string"}, "task": {"type": "string"}},
             "required": ["agent", "task"]},
            False,
        )

    triage = Agent("triage", TRIAGE_PROMPT, [delegate_tool("triage")],
                   llm=llm, max_steps=3, budget_usd=0.50)
    analyst = Agent("analyst", ANALYST_PROMPT,
                    _registry_tools(db_path, ROLE_TOOLS["analyst"]),
                    llm=llm, max_steps=3, budget_usd=0.40)
    verifier = Agent("verifier", VERIFIER_PROMPT,
                     _registry_tools(db_path, ROLE_TOOLS["verifier"]),
                     llm=llm, max_steps=3, budget_usd=0.40)
    planner = Agent("planner", PLANNER_PROMPT,
                    _registry_tools(db_path, ROLE_TOOLS["planner"]),
                    llm=llm, max_steps=3, budget_usd=0.40)
    chaser = Agent("chaser", CHASER_PROMPT,
                   _registry_tools(db_path, ROLE_TOOLS["chaser"]),
                   llm=llm, max_steps=3, budget_usd=0.40)

    team = AgentTeam([triage, analyst, verifier, planner, chaser], db_path, llm)
    team_ref["team"] = team
    return team


class _ScenarioLLM:
    def __init__(self, scenario: str):
        self.scenario = scenario
        self.used = set()

    def chat(self, messages, tools=(), system="", model=None):
        names = {item["function"]["name"] for item in tools}
        prompt = system.casefold()
        text = str(messages[-1].get("content", "")) if messages else ""

        if "triage" in prompt:
            if "triage" in self.used:
                return {"text": "Triage plan complete.", "tool_calls": [], "usage": {}}
            self.used.add("triage")
            return {"text": "Delegating to analysts, verifier, planner and chaser.",
                    "tool_calls": [
                        {"name": "delegate", "arguments": {"agent": role, "task": text},
                         "reason": "specialist hand-off"}
                        for role in ("analyst", "verifier", "planner", "chaser")
                        if "delegate" in names
                    ], "usage": {}}

        if "analyst" in prompt:
            if "analyst" in self.used:
                return {"text": "Analyst evidence complete.", "tool_calls": [], "usage": {}}
            self.used.add("analyst")
            calls = []
            if "list_shortfalls" in names:
                calls.append({"name": "list_shortfalls", "arguments": {}, "reason": "identify gaps"})
            if "get_readiness" in names:
                calls.append({"name": "get_readiness", "arguments": {}, "reason": "read cited forecast"})
            return {"text": "Analyst found the launch shortfall.", "tool_calls": calls, "usage": {}}

        if "independent" in prompt or "verifier" in prompt:
            if "verifier" in self.used:
                return {"text": "Verifier check complete.", "tool_calls": [], "usage": {}}
            self.used.add("verifier")
            calls = []
            if "search_documents" in names:
                calls.append({"name": "search_documents",
                              "arguments": {"query": "art book" if self.scenario == "art_book" else "quality"},
                              "reason": "verify each claim"})
            return {"text": "Verifier checked source evidence.", "tool_calls": calls, "usage": {}}

        if "planner" in prompt:
            if "planner" in self.used:
                return {"text": "Planner result complete.", "tool_calls": [], "usage": {}}
            self.used.add("planner")
            calls = []
            if "propose_option" in names:
                calls.append({"name": "propose_option",
                              "arguments": {"kind": "plan_b", "title": "Pending Plan B",
                                            "rationale": "Assumptions unknown; human approval required.",
                                            "evidence": []},
                              "reason": "keep option pending"})
            return {"text": "Planner proposed only a pending option.", "tool_calls": calls, "usage": {}}

        if "chaser" in prompt:
            if "chaser" in self.used:
                return {"text": "Chaser action complete.", "tool_calls": [], "usage": {}}
            self.used.add("chaser")
            calls = []
            if self.scenario == "german_notice" and "request_review" in names:
                calls.append({"name": "request_review",
                              "arguments": {"file": "unseen_german_notice.pdf",
                                            "reason": "unknown format requiring human review"},
                              "reason": "do not guess"})
            elif "draft_email" in names:
                supplier = "SUP-0028" if self.scenario == "art_book" else "SUP-0018"
                calls.append({"name": "draft_email",
                              "arguments": {"supplier_id": supplier,
                                            "issue": {"supplier_id": supplier,
                                                      "component": "CMP-GAM-008",
                                                      "po": "4500318768" if supplier == "SUP-0028" else "4500318727",
                                                      "what_we_need": "Verify a verifiable dated lot and quantity"}},
                              "reason": "create guarded draft"})
            if "escalate_to_human" in names and self.scenario in {"quality_hold", "german_notice"}:
                calls.append({"name": "escalate_to_human",
                              "arguments": {"role": "Supplier Quality / Category Lead",
                                            "reason": "internal release or unknown notice requires signer",
                                            "evidence": []},
                              "reason": "human gate"})
            return {"text": "Chaser prepared guarded action.", "tool_calls": calls, "usage": {}}
        return {"text": "No action.", "tool_calls": [], "usage": {}}


def _scenario_team(db_path: str | Path, scenario: str) -> AgentTeam:
    team = build_team(db_path, llm=_ScenarioLLM(scenario))
    for agent in team.agents.values():
        agent.llm = _ScenarioLLM(scenario)
    return team


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("art_book", "quality_hold", "german_notice"), required=True)
    parser.add_argument("--db", type=Path, default=Path("store/soony.db"))
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)

    if args.fake:
        team = _scenario_team(args.db, args.scenario)
    else:
        team = build_team(args.db, HTTPAdapter())

    result = team.run_event(f"{args.scenario} data-drop event")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if args.fake:
        return 0

    errors = []
    if result.get("live_failed"):
        errors.append(str(result["live_failed"]["reason"]))
    for name, value in result.items():
        if isinstance(value, dict) and value.get("status") in {"error", "timeout", "budget_exceeded"}:
            errors.append(f"{name}: {value.get('reason', value['status'])}")
    if errors:
        print("NO LIVE MODEL RAN", file=os.sys.stderr)
        print("; ".join(errors), file=os.sys.stderr)
        return 1

    try:
        row = team.db.execute(
            "SELECT COALESCE(SUM(cost),0), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0) FROM agent_trace"
        ).fetchone()
        cost, input_tokens, output_tokens = float(row[0]), int(row[1]), int(row[2])
        print(f"LIVE RUN: cost=${cost:.6f} input_tokens={input_tokens} output_tokens={output_tokens}",
              file=os.sys.stderr)
    except Exception as exc:
        print(f"LIVE RUN accounting unavailable: {exc}", file=os.sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
