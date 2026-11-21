import sqlite3
import unittest
from unittest.mock import Mock, patch

from src.agents import Agent, Team, Tool
from src.agents.llm_adapter import FakeLLM, HTTPAdapter, usage_cost


class RuntimeTests(unittest.TestCase):
    def test_openai_messages_preserve_parallel_tool_protocol(self):
        adapter = HTTPAdapter(mode="live")
        neutral = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "call-a", "name": "alpha", "arguments": {"x": 1}},
                {"id": "call-b", "name": "beta", "arguments": {"x": 2}},
            ]},
            {"role": "tool", "name": "alpha", "tool_call_id": "call-a", "content": "{\"ok\":true}"},
            {"role": "tool", "name": "beta", "tool_call_id": "call-b", "content": "{\"ok\":true}"},
        ]
        converted = adapter._openai_messages(neutral)
        self.assertEqual(converted[1]["tool_calls"][0]["id"], "call-a")
        self.assertEqual(converted[2]["role"], "tool")
        self.assertEqual(converted[2]["tool_call_id"], "call-a")

    def test_auth_and_real_cost_accounting(self):
        with patch.dict("os.environ", {"SOONY_LLM_API_KEY": "test-key", "OPENAI_API_KEY": ""}, clear=False):
            adapter = HTTPAdapter(mode="live")
            with patch("urllib.request.urlopen") as urlopen:
                response = Mock()
                response.read.return_value = b'{"model":"gpt-4.1-mini","choices":[{"message":{"content":"ok","tool_calls":[]}}],"usage":{"prompt_tokens":1000,"completion_tokens":500}}'
                urlopen.return_value = response
                result = adapter._openai({"model": "gpt-4.1-mini", "messages": [],
                                          "tools": [], "system": ""}, "https://api.openai.com/v1/chat/completions")
                authorization = urlopen.call_args.args[0].headers["Authorization"]
                self.assertIn("test-key", authorization)
        self.assertAlmostEqual(usage_cost("gpt-4.1-mini", {"input_tokens": 1000, "output_tokens": 500}),
                               0.0004 + 0.0008)

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
