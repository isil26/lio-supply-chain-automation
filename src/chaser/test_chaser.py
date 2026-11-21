import os
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from .agent import SupplierChaser
from .llm import DeterministicFakeLLM
from .models import Issue
from .store import ChaserStore
from .supplier import load_supplier


ROOT = Path(__file__).resolve().parents[2]
DEADLINE = datetime.fromisoformat("2026-11-22T20:00:00+01:00")


class SupplierChaserTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ChaserStore(Path(self.tmp.name) / "chaser.sqlite")
        self.chaser = SupplierChaser(store=self.store, data_root=ROOT / "data")
        os.environ.pop("CHASER_SENDER", None)
        os.environ.pop("CHASER_REAL_SMTP", None)

    def tearDown(self):
        os.environ.pop("CHASER_SENDER", None)
        os.environ.pop("CHASER_REAL_SMTP", None)

    def issue(self, supplier_id="SUP-0019", **overrides):
        payload = {
            "supplier_id": supplier_id,
            "component": "CMP-GAM-006",
            "PO": "4500000001",
            "what_we_need": "confirmed quantity and launch ETA",
            "deadline": DEADLINE,
        }
        payload.update(overrides)
        return Issue.from_dict(payload)

    def test_profile_languages_from_data(self):
        expected = {
            "SUP-0010": "ko",
            "SUP-0011": "en",
            "SUP-0018": "en",
            "SUP-0019": "zh",
            "SUP-0028": "pl",
            "SUP-0029": "zh",
        }
        for supplier_id, language in expected.items():
            supplier = load_supplier(supplier_id, ROOT / "data")
            self.assertEqual(supplier.preferred_language, language)

    def test_draft_guardrail_states_and_dry_run(self):
        thread = self.chaser.draft(self.issue())
        self.assertEqual(thread["state"], "pending")
        self.assertEqual(thread["language"], "zh")
        with self.assertRaises(PermissionError):
            self.chaser.send(thread["thread_id"])

        approved = self.chaser.approve(thread["thread_id"])
        os.environ["CHASER_SENDER"] = "launch@registered.example"
        result = self.chaser.send(thread["thread_id"], "dry-run")
        self.assertFalse(result["sent"])
        self.assertEqual(result["state"], "approved")
        self.assertEqual(self.store.get_thread(thread["thread_id"])["state"], "approved")

    def test_price_premium_guardrail_rejects_overage(self):
        with self.assertRaisesRegex(ValueError, "exceeds max_price_premium_pct"):
            self.chaser.draft(self.issue(
                max_price_premium_pct=5,
                proposed_price_premium_pct=6,
            ))

    def test_mock_send_and_reply_parser(self):
        os.environ["CHASER_SENDER"] = "launch@registered.example"
        thread = self.chaser.draft(self.issue())
        self.chaser.approve(thread["thread_id"])
        sent = self.chaser.send(thread["thread_id"], "mock")
        self.assertTrue(sent["sent"])
        self.assertEqual(self.store.get_thread(thread["thread_id"])["state"], "sent")

        parsed = self.chaser.parse_reply(
            thread["thread_id"],
            "Shipped Friday, maybe 5000 pcs.",
        )
        self.assertEqual(parsed["status"], "unconfirmed")
        self.assertEqual(parsed["new_eta"], "Friday")
        self.assertEqual(parsed["quantity"], 5000)
        self.assertTrue(parsed["needs_human"])

    def test_real_smtp_requires_explicit_flag(self):
        thread = self.chaser.draft(self.issue())
        self.chaser.approve(thread["thread_id"])
        os.environ["CHASER_SENDER"] = "launch@registered.example"
        with self.assertRaisesRegex(PermissionError, "CHASER_REAL_SMTP=1"):
            self.chaser.send(thread["thread_id"], "smtp")

    def test_fake_llm_iso_eta_and_blocked_status(self):
        llm = DeterministicFakeLLM()
        parsed = llm.parse_reply("We cannot ship 2000 pieces before 2026-11-23.")
        self.assertEqual(parsed.status, "blocked")
        self.assertEqual(parsed.quantity, 2000)
        self.assertEqual(parsed.new_eta, "2026-11-23")
        self.assertTrue(parsed.needs_human)

    def test_action_log_persists(self):
        thread = self.chaser.draft(self.issue())
        actions = self.store.action_log(thread["thread_id"])
        self.assertEqual([row["action"] for row in actions], ["draft_created"])


if __name__ == "__main__":
    unittest.main()
