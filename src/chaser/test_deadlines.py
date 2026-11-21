import os
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from src import chaser
from src.chaser import autosend, deadlines
from src.decide.actions import action_queue
from src.ingest.store import connect, save_state


class QueuedDeadlineTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "chaser.db"
        self.con = connect(self.path)
        self.addCleanup(self.con.close)
        chaser.schema(self.con)
        self.now = datetime.now(timezone.utc)
        self.cutoff = self.now + timedelta(hours=4)
        self.truth = {
            "deadline": self.cutoff.isoformat(),
            "parts": {"PART": {"shortfall": 50}},
        }
        with self.con:
            save_state(self.con, "truth", self.truth)

    def queue(self, chase_id, *, material="PART", status="draft", deadline=None):
        with self.con:
            self.con.execute("""
                INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)
                VALUES (?,'SUP','Supplier','test@suppliers.juliansibbing.de','en','Availability',?,?,60,?,?)
            """, (chase_id, status, material, f"Please confirm quantity for {material}.",
                  self.cutoff.isoformat() if deadline is None else deadline))

    def fallback(self, deadline):
        with closing(connect(self.path)) as con, con:
            save_state(con, "options", [{"id": "backup", "material": "PART", "latest_action": deadline.isoformat()}])

    def test_worker_hands_off_at_current_fallback_cutoff_even_for_held_drafts(self):
        self.queue("STALE")
        self.queue("HELD", status=autosend.HELD)
        self.queue("CURRENT", material="OTHER")
        self.fallback(self.now)
        sender = Mock()
        results = autosend.run(self.con, send=sender, now=self.now, prepare=False)
        sender.assert_called_once_with(self.con, "CURRENT")
        self.assertEqual({item["id"]: item["result"] for item in results},
                         {"STALE": "escalated", "HELD": "escalated", "CURRENT": "sent"})
        with closing(connect(self.path)) as con:
            items = action_queue(con, self.truth, [], [], [], {}, include_history=True)
            self.assertEqual(len(items), 2)
            self.assertEqual({item["threadId"] for item in items}, {"STALE", "HELD"})
            for item in items:
                self.assertEqual((item["owner"], item["kind"], item["deadline"]),
                                 ("Procurement", "internal", self.now.isoformat()))
                self.assertIn("50 units uncovered", item["detail"])
            self.assertEqual(deadlines.expire_queued(con, self.now), [])
            self.assertEqual(con.execute("SELECT count(*) FROM chaser_deadline_handoffs").fetchone()[0], 2)
            with self.assertRaises(deadlines.DeadlineHandoff):
                autosend.approve(con, "HELD", "Felix")

    @patch("src.chaser.mailenv.load_team_mail_env")
    @patch("src.chaser.smtplib.SMTP")
    def test_expired_or_undated_drafts_cannot_open_smtp(self, smtp, _load_env):
        self.queue("RECOVERY", status="recovery draft", deadline=self.now.isoformat())
        self.queue("LOOP", status="loop draft", deadline="")
        for chase_id, message in (("RECOVERY", "deadline passed"), ("LOOP", "no usable decision deadline")):
            with self.subTest(chase_id=chase_id), self.assertRaisesRegex(deadlines.DeadlineHandoff, message):
                chaser.send(self.con, chase_id, auto=True, managed=True)
        smtp.assert_not_called()
        self.assertEqual(self.con.execute("SELECT count(*) FROM messages").fetchone()[0], 0)

    @patch.dict(os.environ, {"CHASER_REAL_SMTP": "1", "CHASER_SENDER": "team@example.invalid",
                             "CHASER_SMTP_HOST": "smtp.example.invalid", "CHASER_SMTP_PORT": "587"})
    @patch("src.chaser.mailenv.load_team_mail_env")
    @patch("src.chaser.smtplib.SMTP")
    def test_plan_change_while_connecting_stops_before_send_message(self, smtp, _load_env):
        self.queue("SHIFT")
        client = smtp.return_value.__enter__.return_value

        def shorten_shift(_client):
            with closing(connect(self.path)) as con, con:
                save_state(con, "truth", dict(self.truth, shifts=[
                    [(self.now - timedelta(hours=1)).isoformat(), self.now.isoformat()]
                ]))

        with patch("src.chaser.authenticate", side_effect=shorten_shift):
            with self.assertRaises(deadlines.DeadlineHandoff):
                chaser.send(self.con, "SHIFT")
        client.send_message.assert_not_called()
        self.assertEqual(self.con.execute("SELECT count(*) FROM messages").fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT status FROM chases WHERE id='SHIFT'").fetchone()[0], "escalated")
