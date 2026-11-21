import os
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from .agent import SupplierChaser
from .deadlines import DeadlineHandoff
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
        self.chaser = SupplierChaser(store=self.store, data_root=ROOT / ("data" if (ROOT / "data" / "suppliers").is_dir() else "case-data"))
        os.environ.pop("CHASER_SENDER", None)
        os.environ.pop("CHASER_REAL_SMTP", None)

    def tearDown(self):
        os.environ.pop("CHASER_SENDER", None)
        os.environ.pop("CHASER_REAL_SMTP", None)

    def test_store_uses_wal_and_busy_timeout(self):
        with self.store.connect() as db:
            self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            self.assertGreaterEqual(db.execute("PRAGMA busy_timeout").fetchone()[0], 30000)

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
            supplier = load_supplier(supplier_id)
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

    @patch.dict(os.environ, {"CHASER_SENDER": "launch@registered.example", "CHASER_REAL_SMTP": "1"})
    @patch("src.chaser.mailenv.load_team_mail_env")
    @patch("src.chaser.agent.SMTPOutbox")
    def test_expired_cli_send_is_escalated_to_procurement(self, outbox, _load_env):
        thread_id = self.chaser.draft(self.issue(deadline=datetime.fromisoformat("2000-01-01T09:00:00+01:00")))["thread_id"]
        self.chaser.approve(thread_id)
        with self.assertRaisesRegex(DeadlineHandoff, "Procurement"):
            self.chaser.send(thread_id, "smtp")
        outbox.assert_not_called()
        self.assertEqual(self.store.get_thread(thread_id)["state"], "escalated")
        self.assertEqual(self.store.action_log(thread_id)[-1]["action"], "deadline_handoff")

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

    def test_reply_commitment_strength_levels(self):
        llm = DeterministicFakeLLM()
        self.assertEqual(llm.parse_reply("Maybe Friday").commitment_strength, "date_only")
        self.assertEqual(
            llm.parse_reply("Confirmed Friday, 5000 pcs").commitment_strength,
            "date_and_quantity",
        )
        self.assertEqual(
            llm.parse_reply("Booking number AWB-12345, shipped Friday").commitment_score,
            3,
        )

    def test_r1_templates_in_supported_languages(self):
        for supplier_id in ("SUP-0010", "SUP-0019", "SUP-0028", "SUP-0011"):
            thread = self.chaser.draft(self.issue(supplier_id=supplier_id), tone="r1_document")
            self.assertIn("r1_document", thread["tone"])
            self.assertIn("PO", thread["body"] + thread["subject"])
            self.assertIn("PO" if supplier_id != "SUP-0019" else "PO", thread["body"])

    def test_draft_guardrail_blocks_secret_disclosures(self):
        from .guardrails import Guardrails

        guardrails = Guardrails()
        for text in (
            "Our deadline slack is 2 days.",
            "The maximum premium is EUR 500.",
            "We will walk away and use alternative suppliers.",
            "The cost per missing copy is EUR 35.",
        ):
            result = guardrails.validate_draft(text)
            self.assertFalse(result.ok)

    def test_send_rechecks_draft_guardrail(self):
        thread = self.chaser.draft(self.issue())
        with self.store.connect() as db:
            db.execute(
                "UPDATE threads SET body='Our deadline slack is 2 days.' WHERE thread_id=?",
                (thread["thread_id"],),
            )
        self.chaser.approve(thread["thread_id"])
        os.environ["CHASER_SENDER"] = "launch@registered.example"
        with self.assertRaisesRegex(ValueError, "draft failed send guardrail"):
            self.chaser.send(thread["thread_id"], "dry-run")

    def test_escalation_ladder_is_persisted(self):
        thread = self.chaser.draft(self.issue())
        self.assertEqual(self.store.get_escalation(thread["thread_id"])["rung"], "R0")
        parsed = self.chaser.parse_reply(
            thread["thread_id"],
            "We have a booking number AWB-12345 for 5000 pcs on 2026-11-22.",
        )
        self.assertEqual(parsed["commitment_score"], 3)
        escalation = self.store.get_escalation(thread["thread_id"])
        self.assertIn(escalation["rung"], {"R0", "R1", "R2", "R3", "R4"})
        self.assertTrue(escalation["updated_at"])


if __name__ == "__main__":
    unittest.main()
