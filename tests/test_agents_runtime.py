import sqlite3
import unittest

from src.agents import Agent, Team, Tool
from src.agents.llm_adapter import FakeLLM


class RuntimeTests(unittest.TestCase):
    def test_tool_call_and_trace(self):
        seen = []
        llm = FakeLLM([
            {"text": "", "tool_calls": [{"name": "add", "arguments": {"a": 2, "b": 3}, "reason": "calculate"}], "usage": {}},
            {"text": "done", "tool_calls": [], "usage": {}},
        ])
        agent = Agent("analyst", "use tools", [Tool("add", lambda a, b: seen.append(a + b) or {"sum": a + b},
                         {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                          "required": ["a", "b"]})], llm=llm)
        db = sqlite3.connect(":memory:")
        self.assertEqual(agent.run("go", db)["status"], "completed")
        self.assertEqual(seen, [5])
        self.assertEqual(db.execute("select count(*) from agent_trace").fetchone()[0], 2)

    def test_gate_and_whitelist(self):
        called = []
        llm = FakeLLM([{"text": "", "tool_calls": [
            {"name": "send", "arguments": {"x": 1}},
            {"name": "secret", "arguments": {}},
        ], "usage": {}}, {"text": "stopped", "tool_calls": [], "usage": {}}])
        db = sqlite3.connect(":memory:")
        agent = Agent("chaser", "", [Tool("send", lambda x: called.append(x),
                         {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
                         needs_approval=True)], llm=llm)
        agent.run("send", db)
        self.assertEqual(called, [])
        self.assertEqual(db.execute("select count(*) from agent_approvals").fetchone()[0], 1)

    def test_team_blackboard(self):
        agent = Agent("worker", "", llm=FakeLLM([{"text": "ok", "tool_calls": [], "usage": {}}]))
        team = Team([agent])
        team.put("risk", {"part": "X"}, "lead")
        self.assertEqual(team.get("risk")["part"], "X")
        self.assertEqual(team.delegate("lead", "worker", "check")["status"], "completed")


if __name__ == "__main__":
    unittest.main()
