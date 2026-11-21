import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from src.agents.loop import AutonomyLoop


class _FakeTeam:
    def __init__(self, path):
        self.agents = {}
        self.path = path
        with sqlite3.connect(path) as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS agent_trace "
                "(id INTEGER PRIMARY KEY, agent TEXT, tool TEXT, args TEXT, result TEXT, "
                "reason TEXT, cost REAL, latency_ms REAL, input_tokens INTEGER, output_tokens INTEGER, created_at REAL)"
            )

    def run_event(self, event):
        with sqlite3.connect(self.path) as con:
            con.execute(
                "INSERT INTO agent_trace(agent,tool,args,result,reason,cost,latency_ms,created_at,status) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                ("triage", "search_documents",
                 '{"query":"unseen notice"}',
                 '{"citations":[{"file":"tests/fixtures/unseen_german_notice.txt","quote":"Lieferverzogerung"}]}',
                 "searched review evidence", 0.01, 12.0, time.time(), "completed"),
            )
            con.execute(
                "CREATE TABLE IF NOT EXISTS agent_approvals "
                "(id INTEGER PRIMARY KEY, agent TEXT, tool TEXT, args TEXT, status TEXT)"
            )
            con.execute(
                "INSERT INTO agent_approvals(agent,tool,args,status) VALUES(?,?,?,?)",
                ("chaser", "request_review",
                 '{"file":"tests/fixtures/unseen_german_notice.txt","reason":"human review required"}',
                 "pending"),
            )
        return {"harness": {"ok": True, "violations": []}}


class AgentLoopTests(unittest.TestCase):
    def test_deduplicates_and_persists_background_run(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agents.db"
            loop = AutonomyLoop(path, enabled=True, team_factory=_FakeTeam)
            event = {"kind": "drop", "changed_files": ["new.csv"], "summary": "new data"}
            first = loop.submit(event)
            second = loop.submit(event)
            self.assertEqual(first["status"], "queued")
            self.assertEqual(second["status"], "deduped")
            deadline = time.time() + 2
            while time.time() < deadline and loop.runs()[0]["status"] == "queued":
                time.sleep(0.01)
            self.assertEqual(loop.runs()[0]["status"], "completed")
            self.assertEqual(loop.trace(first["run"])["trace"][0]["agent"], "triage")
            trace = loop.trace(first["run"])
            self.assertEqual(len(trace["steps"]), 1)
            self.assertEqual(trace["steps"][0]["agent"], "triage")
            self.assertEqual(trace["steps"][0]["tool"], "search_documents")
            self.assertIn("args_summary", trace["steps"][0])
            self.assertIn("result_summary", trace["steps"][0])
            self.assertIn("citations", trace["steps"][0])
            self.assertEqual(len(trace["approvals_pending"]), 1)
            listed = loop.runs()[0]
            self.assertEqual(listed["step_count"], 1)
            self.assertIn("harness", listed)

    def test_stop_is_a_kill_switch(self):
        with tempfile.TemporaryDirectory() as directory:
            loop = AutonomyLoop(Path(directory) / "agents.db", enabled=True, team_factory=_FakeTeam)
            loop.stop()
            self.assertEqual(loop.submit({"kind": "timer", "summary": "tick"})["status"], "offline")


if __name__ == "__main__":
    unittest.main()
