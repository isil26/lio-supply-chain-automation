#!/usr/bin/env python3
"""Export the latest redacted agent run for the static/hosted UI replay."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "agent_runs"
DEST = ROOT / "web" / "public" / "snapshot" / "agent_run.json"

def main() -> None:
    runs = sorted(SOURCE.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not runs:
        raise SystemExit("No recorded agent run found under docs/agent_runs")
    payload = json.loads(runs[0].read_text())
    summary = payload.get("summary", {})
    steps = []
    for index, agent in enumerate(["Triage", "Analyst", "Verifier", "Planner", "Chaser"]):
        status = summary.get(f"{agent.lower()}_status", "completed")
        citations = []
        if agent in {"Analyst", "Verifier"} and summary.get("receipt_discrepancy"):
            citations = [{"file": f'{summary["receipt_discrepancy"]["document"]}.jpg', "page": 1, "quote": "Handwritten quantity overrides the SAP booking"}]
        steps.append({
            "agent": agent,
            "tool": "recorded_run",
            "args_summary": payload.get("scenario", "recorded"),
            "result_summary": status,
            "reason": "Replayed from a redacted recorded run",
            "cost": round(float(payload.get("cost_usd", 0)) / 5, 6),
            "latency": 0,
            "citations": citations,
            "status": status,
        })
    export = {
        "steps": steps,
        "approvals_pending": [{"id": "recorded-approval", "title": "Recorded human approval", "detail": "Replay only; no supplier email was sent."}]
        if summary.get("pending_approvals") else [],
    }
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps(export, indent=2) + "\n")
    print(f"Exported {runs[0].name} -> {DEST.relative_to(ROOT)}")

if __name__ == "__main__":
    main()
