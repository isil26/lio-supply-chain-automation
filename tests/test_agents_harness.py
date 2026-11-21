import sqlite3
import tempfile
import unittest

from src.agents.harness import (
    citation_check,
    language_check,
    numeric_grounding,
    policy_check,
    stop_check,
)


class HarnessTests(unittest.TestCase):
    def test_numeric_grounding_catches_hallucination_and_accepts_grounding(self):
        trace = [{"tool": "list_shortfalls", "args": {}, "result": '{"value":[{"shortfall":5900}]}'}]
        good = numeric_grounding("The shortfall is 5,900 units.", trace)
        bad = numeric_grounding("The shortfall is 7,777 units.", trace)
        self.assertTrue(good["ok"])
        self.assertFalse(bad["ok"])

    def test_numeric_grounding_accepts_explicit_assumption(self):
        trace = [{"tool": "breakeven", "result": "{}"}]
        result = numeric_grounding("Assumption: missing-copy cost is EUR 42,000.", trace)
        self.assertTrue(result["ok"])

    def test_citation_check_requires_verbatim_quote(self):
        trace = [{"tool": "search_documents", "result":
                  '{"citations":[{"file":"art.pdf","page":1,"quote":"ordered 8,000"}]}'}]
        good = citation_check([{"text": "The order was for 8,000 units.",
                                "file": "art.pdf", "quote": "ordered 8,000"}], trace)
        bad = citation_check(["The order was for 9,000 units."], trace)
        self.assertTrue(good["ok"])
        self.assertFalse(bad["ok"])

    def test_policy_check_blocks_send_and_pune_concession(self):
        send = policy_check([{"action": "send_email", "status": "pending"}])
        pune = policy_check([{"action": "release", "status": "approved",
                             "approver": "Supplier Quality", "value": 100,
                             "text": "Pune lot release"}])
        forbidden = policy_check([{"action": "draft", "text": "Our max premium is EUR 100"}])
        self.assertFalse(send["ok"])
        self.assertFalse(pune["ok"])
        self.assertFalse(forbidden["ok"])

    def test_policy_check_allows_approved_buyer_action_under_limit(self):
        result = policy_check([{"action": "PO", "status": "approved",
                                "approver": "Buyer", "value_eur": 49_000}])
        self.assertTrue(result["ok"])

    def test_stop_check_catches_repeat_and_oscillation(self):
        trace = [{"tool": "delegate", "args": '{"agent":"analyst"}', "result": "{}"}] * 3
        trace += [{"tool": "propose_option", "result": "Pending Plan B"}] * 2
        result = stop_check(trace)
        self.assertFalse(result["ok"])

    def test_language_check_accepts_polish_and_rejects_missing_ask(self):
        good = language_check("Proszę potwierdzić ilość i dokument partii PO-4500318768.",
                              "SUP-0028")
        bad = language_check("Możemy kontynuować.", "SUP-0028")
        self.assertTrue(good["ok"])
        self.assertFalse(bad["ok"])


if __name__ == "__main__":
    unittest.main()
