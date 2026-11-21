import os
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import smtplib
import unittest
from email.message import EmailMessage
from unittest.mock import patch

from src import chaser
from src.chaser.reply_plan import plan_reply
from src.decide import authorize, decisions
from src.ingest.store import connect, get_state, save_state


class ReplyHistoryTests(unittest.TestCase):
    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "history.db"
        self.truth = {
            "shifts": [["2026-11-22T12:00:00+01:00", "2026-11-22T20:00:00+01:00"]],
            "editions": {"CE": {"edition": "Collector's", "target": 80, "packed": 0, "rate": 20}},
            "parts": {"PART": {"on_hand": 0, "unit_usage": {"CE": 1}}},
            "inbound": [{"id": "SHIP-1", "reference": "123-12345678", "material": "PART", "supplier": "SUP-TEST",
                         "earliest": "2026-11-22T08:00:00+01:00", "mode": "road", "held": False, "quantity": 100}],
            "model": {"runs": 30, "lag_hours": {"road": [0, 0, 0]}},
        }
        with closing(connect(self.path)) as con:
            chaser.schema(con)
            with con:
                save_state(con, "truth", self.truth)
                con.execute("""INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            ("AB12", "SUP-TEST", "Test supplier", "supplier@example.invalid", "en",
                             "[SOONY-AB12] Test", "draft", "PART", 80, "Please confirm availability.", "2026-11-22"))
        environment = patch.dict(os.environ, {
            "CHASER_SENDER": "team@example.invalid", "CHASER_REAL_SMTP": "1", "CHASER_SMTP_HOST": "smtp.example.invalid",
            "CHASER_SMTP_PORT": "587", "CHASER_ALLOWED_RECIPIENTS": "supplier@example.invalid",
        }, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_mock_smtp_and_matched_inbox_persist_exact_evidence_and_decision(self):
        with closing(connect(self.path)) as con, patch("src.chaser.smtplib.SMTP") as smtp:
            transport = smtp.return_value.__enter__.return_value
            transport.send_message.return_value = {}
            chaser.send(con, "AB12", demo=False)
            outbound, = transport.send_message.call_args.args
            incoming = EmailMessage()
            incoming["From"] = "supplier@example.invalid"
            incoming["To"] = "team@example.invalid"
            incoming["Subject"] = str(outbound["Subject"])
            incoming["In-Reply-To"] = str(outbound["Message-ID"])
            incoming["Message-ID"] = "<reply@test.invalid>"
            incoming.set_content("Flight delayed for SHIP-1.\nRevised ETA: 2026-11-22T22:00:00+01:00")
            self.assertFalse(chaser.receive(con, incoming, simulated=True))
            self.assertTrue(chaser.receive(con, incoming))
            self.assertFalse(chaser.receive(con, incoming))
        with closing(connect(self.path)) as con:
            outbound, reply = next(chaser.list_threads(con))["messages"]
            self.assertEqual(outbound["transport"]["status"], "smtp_accepted")
            self.assertEqual(outbound["transport"]["from"], "team@example.invalid")
            self.assertEqual(outbound["transport"]["to"], "supplier@example.invalid")
            self.assertEqual(outbound["text"], "Please confirm availability.")
            self.assertEqual(reply["transport"]["inReplyTo"], outbound["transport"]["messageId"])
            self.assertEqual(reply["transport"]["mode"], "inbox")
            plan = reply["parsed"]["reply_plan"]
            self.assertEqual(plan["editions"][0]["before"], 80)
            self.assertEqual(plan["editions"][0]["after"], 0)
            self.assertEqual(plan["evidence"], ["SHIP-1", "Revised ETA: 2026-11-22T22:00:00+01:00"])
            self.assertEqual(plan["status"], "proposed")
            self.assertEqual(authorize(con, chaser.reply_decision(con, reply["id"]), "approve"), "approved")
            self.assertEqual(get_state(con, "truth"), self.truth)
        with closing(connect(self.path)) as con:
            plan_after = next(chaser.list_threads(con, decisions(con)))["messages"][-1]["parsed"]["reply_plan"]
            self.assertEqual(plan_after["id"], plan["id"])
            self.assertEqual(plan_after["status"], "approved")

    def test_ambiguous_hold_reply_leaves_offer_pending_without_an_eta_request(self):
        thread = {"material": "PART", "supplier_id": "SUP-TEST", "qty": 80}
        offer = {"id": "offer", "kind": "partial", "supplier_id": "SUP-TEST", "material": "PART"}
        for text in ("We cannot hold 80.", "We can hold 80 or we can hold 20."):
            with self.subTest(text=text):
                plan = plan_reply({}, thread, text, options=[offer])
                self.assertNotIn("holdUnits", plan)
                self.assertNotIn("shipmentId", plan)
                self.assertIn("hold expiry", plan["nextAction"])

    def test_rejected_smtp_attempt_does_not_become_a_sent_email(self):
        with closing(connect(self.path)) as con, patch("src.chaser.smtplib.SMTP") as smtp:
            transport = smtp.return_value.__enter__.return_value
            transport.send_message.side_effect = smtplib.SMTPRecipientsRefused({"supplier@example.invalid": (550, b"rejected")})
            with self.assertRaisesRegex(ValueError, "SMTP rejected"):
                chaser.send(con, "AB12", demo=False)
            thread = next(chaser.list_threads(con))
            self.assertEqual(thread["status"], "send failed")
            self.assertEqual(thread["messages"][0]["transport"]["status"], "failed")
