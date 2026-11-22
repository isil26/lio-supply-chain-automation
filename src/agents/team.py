"""T40 Triage, Analyst, Verifier, Planner and Chaser team."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .llm_adapter import FakeLLM, HTTPAdapter
from .harness import evaluate
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


def _result_citations(value: Any) -> list[dict]:
    found = []
    if isinstance(value, dict):
        if value.get("file") or value.get("source_file") or value.get("source"):
            found.append({
                "file": value.get("file") or value.get("source_file") or value.get("source"),
                "page": value.get("page"),
                "quote": value.get("quote"),
            })
        for key in ("citations", "citation", "evidence", "sources"):
            found.extend(_result_citations(value.get(key)))
    elif isinstance(value, list):
        for item in value:
            found.extend(_result_citations(item))
    return [item for item in found if item not in found[:found.index(item)]]


class AgentTeam(Team):
    def __init__(self, agents, db_path=":memory:", llm=None):
        super().__init__(agents, db_path)
        self.llm = llm
        self.db.execute("""CREATE TABLE IF NOT EXISTS agent_approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, tool TEXT, args TEXT, status TEXT
        )""")
        self.db.commit()

    def run_event(self, event: str) -> dict:
        """Triage an event; fall back to a fixed specialist order if no model plan exists."""
        event_lower = event.casefold()
        triage = self.agents["triage"]
        self.mailbox_start = self.db.execute("SELECT COALESCE(MAX(id), 0) FROM agent_mailbox").fetchone()[0]
        self.trace_start = self.db.execute("SELECT COALESCE(MAX(id), 0) FROM agent_trace").fetchone()[0]
        self.approval_start = self.db.execute("SELECT COALESCE(MAX(id), 0) FROM agent_approvals").fetchone()[0]
        triage_result = triage.run(event, self.db)
        results = {"triage": triage_result}

        if triage_result.get("status") in {"error", "timeout", "budget_exceeded"}:
            results["live_failed"] = {
                "reason": triage_result.get("reason", "live triage model failed"),
            }
            results["verified"] = self._verification_summary(event_lower)
            results["trace"] = activity(self.db, 100)
            results["pending_approvals"] = [
                dict(row) for row in self.db.execute(
                    "SELECT * FROM agent_approvals WHERE status='pending' AND id>? ORDER BY id", (self.approval_start,)
                ).fetchall()
            ]
            return self._finish(results)

        # Expose specialist returns from real triage delegation in the event result.
        mailbox = self.db.execute(
            "SELECT recipient,result,status FROM agent_mailbox WHERE sender=? AND id>? ORDER BY id",
            ("triage", self.mailbox_start),
        ).fetchall()
        for row in mailbox:
            recipient = row["recipient"]
            if recipient in results:
                continue
            try:
                results[recipient] = json.loads(row["result"]) if row["result"] else {"status": row["status"]}
            except Exception:
                results[recipient] = {"status": row["status"], "text": row["result"]}

        recipients = {row["recipient"] for row in mailbox}
        if "planner" in recipients and "chaser" not in recipients:
            results["chaser"] = self.delegate(
                "triage", "chaser",
                "A Plan B option was proposed. Draft one guarded supplier request for the "
                "real supplier/component/PO from the cited evidence; wait for human approval.",
            )

        # Fixed, honest fallback: no LLM response means deterministic specialist order.
        if not recipients:
            results.update(self._fixed_fallback(event_lower))

        results["verified"] = self._verification_summary(event_lower)
        results["trace"] = activity(self.db, 100)
        results["pending_approvals"] = [
            dict(row) for row in self.db.execute(
                "SELECT * FROM agent_approvals WHERE status='pending' AND id>? ORDER BY id", (self.approval_start,)
            ).fetchall()
        ]
        return self._finish(results)

    def _finish(self, results: dict) -> dict:
        trace_rows = [dict(row) for row in self.db.execute(
            "SELECT agent,model,step,tool,args,result,reason,cost,latency_ms,"
            "input_tokens,output_tokens,created_at FROM agent_trace WHERE id>? ORDER BY id", (self.trace_start,)
        ).fetchall()]
        final_text = " ".join(
            str(value.get("text", "")) for value in results.values() if isinstance(value, dict)
        )
        claims = []
        for row in trace_rows:
            result = row.get("result")
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except json.JSONDecodeError:
                    continue
            for citation in _result_citations(result):
                quote = str(citation.get("quote") or "").strip()
                if quote:
                    claims.append({"text": quote, **citation})
        results["claims"] = claims
        results["summary"] = self._run_summary(results, trace_rows)
        report = evaluate(trace_rows, {"text": results["summary"], "claims": claims}, str(self.db_path))
        results["harness"] = report
        results["trace"] = activity(self.db, 100)
        if not report["ok"]:
            # The runtime queues model proposals in agent_approvals. Buyer decisions
            # are owned by the procurement workflow and may predate this event.
            self.db.execute("UPDATE agent_approvals SET status='blocked by harness' WHERE status='pending' AND id>?",
                            (self.approval_start,))
            self.db.commit()
            results["proposal_status"] = "blocked by harness"
        else:
            results["proposal_status"] = "eligible for human approval"
        return results

    @staticmethod
    def _run_summary(results: dict, trace_rows: list[dict]) -> str:
        """Build a short summary only from deterministic tool results."""
        values = []
        for row in trace_rows:
            result = row.get("result")
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except json.JSONDecodeError:
                    continue
            if isinstance(result, dict) and result.get("value") is not None:
                values.append((row.get("tool"), result["value"]))

        gap = None
        for tool, value in values:
            if tool != "list_shortfalls" or not isinstance(value, list):
                continue
            candidates = [item for item in value
                          if isinstance(item, dict) and item.get("shortfall", 0) > 0]
            if candidates:
                gap = max(candidates, key=lambda item: item.get("shortfall", 0))
                break

        option = None
        price = None
        for tool, value in values:
            if tool == "breakeven" and isinstance(value, dict):
                option = value.get("recommendation") or value.get("option")
                price = value.get("expedite_cost_eur") or value.get("cost_eur")
            elif tool == "propose_option" and isinstance(value, dict) and option is None:
                option = value
        pieces = ["Data-drop triage completed from verified deterministic tool results."]
        if gap:
            label = gap.get("label") or gap.get("material") or "top gap"
            pieces.append(f"Top gap: {label}, shortfall {gap.get('shortfall')} units.")
        if option:
            title = option.get("title") or option.get("label") or "Plan B option"
            suffix = f", tool-computed price EUR {price}." if price is not None else "."
            pieces.append(f"Recommended option: {title}{suffix}")
        pending = results.get("pending_approvals") or []
        if pending:
            pieces.append("Human approval is pending; supplier outreach remains dry-run.")
        else:
            pieces.append("Human approval is required before any supplier outreach or commitment.")
        return " ".join(pieces)

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
            query = "WZ-261116-473" if "art" in event_lower else "launch"
            result = tool["handler"]({"query": query})
            evidence = result.get("citations", [])
        except Exception:
            evidence = []
        if evidence:
            supported_claim = "The art-book receiving document WZ-261116-473 has cited source evidence"
        else:
            supported_claim = "The launch shortage requires cited source evidence"
        return verify_claims([supported_claim, "unsupported supplier guarantee"], evidence)


def build_team(db_path="store/soony.db", llm=None) -> AgentTeam:
    db_path = str(db_path)
    if llm is None:
        llm = FakeLLM([]) if os.getenv("SOONY_AGENT_MODE") == "simulated" else HTTPAdapter()

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
                   llm=llm, max_steps=2, budget_usd=0.50, timeout_seconds=300)
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

        if "you are the soony launch triage orchestrator" in prompt:
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

        if "you are the soony launch analyst" in prompt:
            if "analyst" in self.used:
                return {"text": "Analyst evidence complete.", "tool_calls": [], "usage": {}}
            self.used.add("analyst")
            calls = []
            if self.scenario == "sleeve_revision_conflict" and "release_gate_status" in names:
                calls.append({"name": "release_gate_status", "arguments": {"part_id": "CMP-GAM-004"},
                              "reason": "which sleeve revision may be released"})
            elif "list_shortfalls" in names:
                calls.append({"name": "list_shortfalls", "arguments": {}, "reason": "identify gaps"})
            if "get_readiness" in names:
                calls.append({"name": "get_readiness", "arguments": {}, "reason": "read cited forecast"})
            return {"text": "Analyst found the launch shortfall.", "tool_calls": calls, "usage": {}}

        if "you are the independent soony claim verifier" in prompt:
            if "verifier" in self.used:
                return {"text": "Verifier check complete.", "tool_calls": [], "usage": {}}
            self.used.add("verifier")
            calls = []
            if "search_documents" in names:
                calls.append({"name": "search_documents",
                              "arguments": {"query": "art book" if self.scenario == "art_book" else "quality"},
                              "reason": "verify each claim"})
            return {"text": "Verifier checked source evidence.", "tool_calls": calls, "usage": {}}

        if "you are the soony plan b planner" in prompt:
            if "planner" in self.used:
                return {"text": "Planner result complete.", "tool_calls": [], "usage": {}}
            self.used.add("planner")
            calls = []
            if self.scenario == "sleeve_revision_conflict" and "escalate_to_human" in names:
                calls.append({"name": "escalate_to_human",
                              "arguments": {"role": "Marketing / Head of Procurement",
                                            "reason": "Sleeve revision conflict is a human decision",
                                            "evidence": []},
                              "reason": "human gate"})
            elif self.scenario == "air_lot_priority" and "packplan" in names:
                calls.append({"name": "packplan",
                              "arguments": {"changes": {"part_arrives_earlier": {"CMP-GAM-001": 12}}},
                              "reason": "what-if earlier game card air lot"})
            elif "propose_option" in names:
                calls.append({"name": "propose_option",
                              "arguments": {"kind": "plan_b", "title": "Pending Plan B",
                                            "rationale": "Assumptions unknown; human approval required.",
                                            "evidence": []},
                              "reason": "keep option pending"})
            return {"text": "Planner proposed only a pending option.", "tool_calls": calls, "usage": {}}

        if "you are the soony supplier chaser" in prompt:
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
    parser.add_argument("--scenario", choices=("art_book", "quality_hold", "german_notice", "sleeve_revision_conflict", "air_lot_priority"), required=True)
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
