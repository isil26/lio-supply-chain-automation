import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.agents.triage_policy import classify_event, dashboard_decisions, deterministic_pass


class TriagePolicyTests(unittest.TestCase):
    def test_12_synthetic_events_and_categories(self):
        event_dir = Path("tests/agent_eval/events")
        events = sorted(event_dir.glob("*.json"))
        self.assertEqual(12, len(events))
        for path in events:
            fixture = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(fixture["synthetic"])
            result = classify_event(fixture, truth_summary=None, db_path=":memory:")
            self.assertIn(result["category"], {"logistics", "supplier", "customer_request", "news", "noise"})
            self.assertIn(result["decision"], {"ignore", "watch", "act", "escalate"})
            self.assertGreaterEqual(result["materiality"], 0)
            self.assertLessEqual(result["materiality"], 100)
            self.assertTrue(result["reason"])
            self.assertTrue(result["evidence"])

    def test_decision_is_persisted_and_returned(self):
        event = {
            "synthetic": True,
            "title": "Customs hold",
            "text": "The game-card air lot is held by customs before launch.",
        }
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "triage.sqlite"
            result = classify_event(event, truth_summary=None, db_path=db_path)
            with sqlite3.connect(db_path) as con:
                row = con.execute(
                    "SELECT event, category, score, decision, reason, evidence, ts "
                    "FROM event_decisions"
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(result["category"], row[1])
            self.assertEqual(result["materiality"], row[2])
            returned = dashboard_decisions(db_path)[0]
            self.assertEqual(result["decision"], returned["decision"])

    def test_duplicate_is_ignore_and_has_evidence(self):
        event = {
            "title": "Duplicate notice",
            "text": "This is a duplicate copy; it was already received and processed.",
        }
        result = deterministic_pass(event)
        self.assertEqual("noise", result["category"])
        self.assertEqual("ignore", result["decision"])
        self.assertTrue(result["evidence"])

    def test_sensitive_synthetic_fixture_markers(self):
        for path in sorted(Path("tests/agent_eval/events").glob("*.json")):
            fixture = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(True, fixture["synthetic"])


if __name__ == "__main__":
    unittest.main()
