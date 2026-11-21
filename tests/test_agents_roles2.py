import json
import sqlite3
import unittest

from src.agents.briefer import build_brief, briefer_agent, validate_brief
from src.agents.interpreter import evaluate_simulated_replies, interpret_reply, interpreter_agent
from src.agents.llm_adapter import FakeLLM


class RoleTwoTests(unittest.TestCase):
    def test_interpreter_extracts_verbatim_values_and_language(self):
        result = interpret_reply("[PL] Potwierdzamy 8 000 szt. na 2026-11-22; packing list PL-7.")
        self.assertEqual(result["language"], "PL")
        self.assertEqual(result["commitment"]["quantity"], 8000)
        self.assertEqual(result["commitment"]["date"], "2026-11-22")
        self.assertTrue(any("8 000" in quote for quote in result["quotes"]))
        self.assertEqual(result["commitment"]["strength"], "documented")

    def test_interpreter_constructor_has_closed_tools(self):
        agent = interpreter_agent(FakeLLM([{"text": "{}", "tool_calls": [], "usage": {}}]), ":memory:")
        self.assertEqual(set(agent.tools), {
            "parse_reply", "search_documents", "supplier_history",
            "escalate_to_human", "request_review",
        })

    def test_interpreter_evaluates_twelve_simulated_replies(self):
        report = evaluate_simulated_replies()
        self.assertEqual(report["replies"], 12)
        self.assertEqual(report["cost_usd"], 0.0)
        self.assertGreaterEqual(report["accuracy"], 0.75)

    def test_briefer_rejects_ungrounded_number_and_accepts_tool_number(self):
        trace = [{"result": {"price": 12390}}]
        self.assertTrue(validate_brief("Approve the option at 12390 EUR.", trace)["ok"])
        self.assertFalse(validate_brief("Approve the option at 999 EUR.", trace)["ok"])

    def test_briefer_fallback_is_short_and_cited(self):
        brief = build_brief(
            [{"text": "Art-book receiving quantity needs review.",
              "citation": {"file": "scan.jpg", "page": 1, "quote": "handwritten correction"}}],
            [{"title": "Review scan", "cost_eur": "unknown"}],
            "Evidence needs review", "Dr. Vogt",
        )
        self.assertLess(len(brief.split()), 180)
        self.assertIn("scan.jpg", brief)

    def test_briefer_uses_tool_signer_and_price_not_caller_defaults(self):
        brief = build_brief(
            [{"text": "A verified risk.", "citation": {
                "file": "risk.pdf", "page": 2, "quote": "verified risk"}}],
            [
                {"tool": "propose_option", "result": {"value": {
                    "title": "Expedite", "price": 12390}}},
                {"tool": "escalate_to_human", "result": {"value": {
                    "role": "Head of Procurement", "required_signers": ["Head of Procurement"]}}},
            ],
            "Decision", "Category Lead",
        )
        self.assertIn("12", brief)
        self.assertIn("Head of Procurement", brief)
        self.assertNotIn("Category Lead.", brief)

    def test_briefer_fake_run(self):
        agent = briefer_agent(FakeLLM([{"text": "HEADLINE: ready", "tool_calls": [], "usage": {}}]))
        result = agent.run("brief", sqlite3.connect(":memory:"))
        self.assertEqual(result["status"], "completed")


if __name__ == "__main__":
    unittest.main()
