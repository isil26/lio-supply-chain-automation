import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.agents.team import build_team, verify_claims


class AgentTeamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "team.db"
        con = sqlite3.connect(self.db)
        con.executescript("""
        CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE agent_approvals (id INTEGER PRIMARY KEY, agent TEXT, tool TEXT, args TEXT, status TEXT);
        """)
        con.commit()
        con.close()

    def tearDown(self):
        self.temp.cleanup()

    def _team(self, scenario):
        from src.agents.team import _scenario_team
        return _scenario_team(self.db, scenario)

    def test_three_fake_scenarios_keep_send_blocked(self):
        for scenario in ("art_book", "quality_hold", "german_notice"):
            team = self._team(scenario)
            result = team.run_event(f"{scenario} data-drop event")
            self.assertIn("triage", result)
            self.assertIn("trace", result)
            sent = [row for row in result["trace"] if row.get("tool") == "send_email"]
            self.assertEqual(sent, [])

    def test_verifier_rejects_unmatched_claim(self):
        result = verify_claims(
            ["The supplier confirmed 10,000 units", "The stock is 800 units"],
            [{"file": "receipt.pdf", "page": 1, "quote": "8,000"}],
        )
        self.assertTrue(result["rejected"])
        self.assertEqual(len(result["rejected"]), 2)

    def test_build_team_has_role_whitelists(self):
        team = build_team(self.db)
        self.assertEqual(set(team.agents), {"triage", "analyst", "verifier", "planner", "chaser"})


if __name__ == "__main__":
    unittest.main()
