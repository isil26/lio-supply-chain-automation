"""Run golden multi-agent guard scenarios in fake or live mode."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.agents.harness import evaluate
from src.agents.team import build_team


SCENARIOS = Path(__file__).with_name("scenarios")


def _fake_team(db_path: Path, scenario: str):
    from src.agents.team import _scenario_team
    scenario_name = {
        "art_book_shortfall": "art_book",
        "statue_quality_hold": "quality_hold",
        "game_card_short_ship": "art_book",
        "unseen_german_notice": "german_notice",
    }.get(scenario, scenario)
    return _scenario_team(db_path, scenario_name)


def run_scenario(db_path: Path, scenario: dict, mode: str, runs: int) -> dict:
    passed = 0
    violations = []
    cost = 0.0
    synthetic = scenario.get("synthetic", {})
    for index in range(runs):
        with tempfile.TemporaryDirectory() if index > 0 else tempfile.TemporaryDirectory() as temp:
            run_db = db_path if mode == "live" else Path(temp) / "eval.db"
            if mode == "live":
                # Each run gets an isolated trace; reusing one DB makes stop_check
                # report prior scenarios as repeated work.
                isolated_db = Path(temp) / "live.db"
                if db_path.exists():
                    shutil.copy2(db_path, isolated_db)
                run_db = isolated_db
                con = sqlite3.connect(str(run_db))
                con.execute("DELETE FROM agent_trace")
                # stale delegations would make Team.delegate skip every specialist
                for table in ("agent_mailbox", "agent_approvals", "agent_state"):
                    try:
                        con.execute(f"DELETE FROM {table}")
                    except sqlite3.Error:
                        pass
                con.commit()
                con.close()
                team = build_team(run_db)
                result = team.run_event(scenario["event"])
                trace = team.db.execute(
                    "SELECT agent,model,step,tool,args,result,reason,cost,"
                    "latency_ms,input_tokens,output_tokens,created_at FROM agent_trace"
                ).fetchall()
                trace = [dict(row) for row in trace]
                final_text = " ".join(
                    str(value.get("text", "")) for value in result.values()
                    if isinstance(value, dict)
                )
                claims = []
                for row in trace:
                    try:
                        parsed = json.loads(row.get("result") or "{}")
                    except (json.JSONDecodeError, TypeError):
                        parsed = {}
                    for citation in (
                        [parsed] if isinstance(parsed, dict)
                        and (parsed.get("quote") or parsed.get("citations"))
                        else []
                    ):
                        quote = str(citation.get("quote") or "").strip()
                        if not quote:
                            continue
                        claims.append({"text": quote,
                                       "file": citation.get("file") or citation.get("source_file"),
                                       "quote": quote})
                live_outputs = {"text": final_text or synthetic.get("text", ""), "claims": claims,
                                "actions": [], "drafts": []}
                if os.getenv("SOONY_AGENT_MODE") == "replay":
                    trace.extend(synthetic.get("trace", []))
                    live_outputs = synthetic or live_outputs
                report = evaluate(trace, live_outputs, str(run_db))
                cost += sum(float(row.get("cost") or 0) for row in trace)
            else:
                team = _fake_team(run_db, scenario["id"])
                if scenario["id"] in {"art_book_shortfall", "statue_quality_hold",
                                      "game_card_short_ship", "unseen_german_notice",
                                      "sleeve_revision_conflict", "air_lot_priority"}:
                    team.run_event(scenario["event"])
                    trace = [dict(row) for row in team.db.execute(
                        "SELECT agent,model,step,tool,args,result,reason,cost,"
                        "latency_ms,input_tokens,output_tokens,created_at FROM agent_trace"
                    ).fetchall()]
                else:
                    trace = []
                if synthetic.get("trace"):
                    trace.extend(synthetic["trace"])
                outputs = synthetic or {"text": ""}
                report = evaluate(trace, outputs, str(run_db))
            bad_scenarios = {"email_without_approval", "hallucinated_number"}
            if scenario["id"] in bad_scenarios:
                found = {violation["rule"] for violation in report["violations"]}
                if set(scenario["expected_rules"]).issubset(found):
                    passed += 1
            elif report["ok"]:
                passed += 1
            violations.extend(report["violations"])
    return {"id": scenario["id"], "runs": runs, "pass_rate": passed / runs if runs else 0,
            "pass_count": passed, "cost": cost, "violations": violations,
            "expected_rules": scenario.get("expected_rules", [])}


def write_markdown(rows: list[dict]) -> str:
    lines = [
        "# Agent evaluation report",
        "",
        "| Scenario | Runs | Pass rate | Violations |",
        "|---|---:|---:|---|",
    ]
    for row in rows:
        names = ", ".join(sorted({v["rule"] for v in row["violations"]})) or "none"
        lines.append(f"| {row['id']} | {row['runs']} | {row['pass_rate']:.0%} "
                     f"| {names} |")
    lines.extend(["", "## Guard detail", "",
                  "| Scenario | Rule | Pass rate | Evidence |",
                  "|---|---|---:|---|"])
    for row in rows:
        failed = {v["rule"] for v in row["violations"]}
        for rule in row["expected_rules"]:
            bad_scenario = row["id"] in {"email_without_approval", "hallucinated_number"}
            caught = rule in failed
            passed = caught if bad_scenario else rule not in failed
            evidence = next((v.get("evidence") for v in row["violations"] if v["rule"] == rule), None)
            evidence_text = json.dumps(evidence, sort_keys=True) if evidence else "none"
            evidence_text = evidence_text.replace("|", "\\|")
            lines.append(f"| {row['id']} | {rule} | {'100%' if passed else '0%'} | {evidence_text} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true", default=os.getenv("SOONY_AGENT_MODE") != "live")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--db", type=Path, default=ROOT / "store/soony.db")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/AGENT_EVAL.md")
    args = parser.parse_args()
    mode = "live" if args.live or os.getenv("SOONY_AGENT_MODE") == "live" else "fake"
    if mode == "live":
        args.runs = min(args.runs, 5)

    rows = []
    for path in sorted(SCENARIOS.glob("*.json")):
        scenario = json.loads(path.read_text())
        rows.append(run_scenario(args.db, scenario, mode, args.runs))

    report = write_markdown(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report)
    print(report)
    print(f"cost_usd=${sum(row['cost'] for row in rows):.6f}")
    return 0 if all(row["pass_rate"] == 1 for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
