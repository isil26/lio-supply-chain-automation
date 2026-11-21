import os
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import smtplib
import unittest
from email.message import EmailMessage
from unittest.mock import Mock, patch

from src import chaser
from src.chaser import mail_history
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

    def test_read_only_gmail_worker_keeps_verified_history_separate_and_deduplicated(self):
        with closing(connect(self.path)) as con, con:
            con.execute("UPDATE chases SET address='fixture@suppliers.juliansibbing.de' WHERE id='AB12'")
        sent = EmailMessage()
        sent["From"] = "team@example.invalid"
        sent["To"] = "fixture@suppliers.juliansibbing.de"
        sent["Subject"] = "[SOONY-AB12] Test"
        sent["Message-ID"] = "<sent@team.invalid>"
        sent["Date"] = "Sat, 21 Nov 2026 12:00:00 +0000"
        sent.set_content("Please confirm availability.")
        unrelated = EmailMessage()
        unrelated["From"] = str(sent["From"])
        unrelated["To"] = str(sent["To"])
        unrelated["Subject"] = str(sent["Subject"])
        unrelated["Message-ID"] = "<manual@team.invalid>"
        unrelated.set_content("A manually composed message that does not match the Chaser draft.")
        inbound = EmailMessage()
        inbound["From"] = "fixture@suppliers.juliansibbing.de"
        inbound["To"] = "team@example.invalid"
        inbound["Subject"] = "Re: [SOONY-AB12] Test"
        inbound["Message-ID"] = "<genuine-reply@fixture.invalid>"
        inbound["In-Reply-To"] = "<sent@team.invalid>"
        inbound.set_content("SHIP-1 delayed.\nRevised ETA: 2026-11-22T22:00:00+01:00")
        inbox = Mock()
        mailbox = None
        def select(name, *, readonly):
            self.assertTrue(readonly)
            nonlocal mailbox
            mailbox = name
            return "OK", []
        def uid(action, *args):
            records = {b"11": sent, b"12": unrelated} if mailbox == '"[Gmail]/Sent Mail"' else {b"21": inbound}
            if action == "search":
                return "OK", [b" ".join(records)]
            self.assertEqual(action, "fetch")
            self.assertIn("BODY.PEEK", args[1])
            return "OK", [(b"message", records[args[0]].as_bytes())]
        inbox.select.side_effect = select
        inbox.uid.side_effect = uid
        inbox.list.return_value = ("OK", [b'(\\Sent) "/" "[Gmail]/Sent Mail"'])
        history_path = self.path.with_name("gmail.db")
        settings = {"user": "team@example.invalid", "password": "test-only"}
        stop = Mock()
        stop.is_set.side_effect = [False, False, True]
        with patch("src.chaser.mail_history.imaplib.IMAP4_SSL") as client:
            client.return_value.__enter__.return_value = inbox
            mail_history.run(stop, self.path, history_path, settings)
        with closing(connect(history_path)) as history:
            outbound, reply = next(chaser.list_threads(history))["messages"]
            self.assertEqual(outbound["transport"]["status"], "gmail_sent")
            self.assertEqual(reply["transport"]["inReplyTo"], "<sent@team.invalid>")
            self.assertEqual(reply["parsed"]["reply_plan"]["editions"][0]["after"], 0)
        with closing(connect(self.path)) as source:
            self.assertEqual(next(chaser.list_threads(source))["status"], "draft")
            self.assertEqual(source.execute("SELECT count(*) FROM messages").fetchone()[0], 0)

    def test_live_inbox_poll_matches_already_read_replies_without_changing_imap_flags(self):
        with closing(connect(self.path)) as con, patch("src.chaser.smtplib.SMTP") as smtp:
            smtp.return_value.__enter__.return_value.send_message.return_value = {}
            chaser.send(con, "AB12")
            outbound = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
            reply = EmailMessage()
            reply["From"] = "supplier@example.invalid"
            reply["Subject"] = str(outbound["Subject"])
            reply["In-Reply-To"] = str(outbound["Message-ID"])
            reply["Message-ID"] = "<already-read@example.invalid>"
            reply.set_content("SHIP-1 delayed.\nRevised ETA: 2026-11-22T22:00:00+01:00")
            with patch.dict(os.environ, {"SOONY_IMAP_HOST": "imap.example.invalid", "SOONY_IMAP_USER": "team@example.invalid"}), \
                    patch("src.chaser.imaplib.IMAP4_SSL") as imap:
                inbox = imap.return_value.__enter__.return_value
                inbox.select.return_value = ("OK", [])
                inbox.uid.side_effect = [("OK", [b"11"]), ("OK", [(b"message", reply.as_bytes())])] * 2
                self.assertEqual(chaser.poll(con), 1)
                self.assertEqual(chaser.poll(con), 0)
                inbox.select.assert_called_with("INBOX", readonly=True)
                self.assertEqual([c.args[0] for c in inbox.uid.call_args_list], ["search", "fetch"] * 2)
                self.assertNotIn("UNSEEN", inbox.uid.call_args_list[0].args[2])
            self.assertEqual(con.execute("SELECT count(*) FROM messages WHERE side='in'").fetchone()[0], 1)

    def test_verified_sent_lookup_uses_recorded_id_for_a_followup_with_its_parents_subject(self):
        thread = {"address": "fixture@suppliers.juliansibbing.de", "subject": "Re: [SOONY-AB12] Test"}
        parent = {**thread, "subject": "[SOONY-AB12] Test"}
        outbound = EmailMessage()
        outbound["From"], outbound["To"] = "team@example.invalid", thread["address"]
        outbound["Subject"], outbound["Message-ID"] = thread["subject"], "<followup@example.invalid>"
        threads = {"CD34": thread, "AB12": parent}
        self.assertTrue(mail_history._belongs_to_sent(outbound, threads, {"<followup@example.invalid>": "CD34"}, "team@example.invalid"))
        self.assertFalse(mail_history._belongs_to_sent(outbound, threads, {}, "team@example.invalid"))

    def test_ambiguous_hold_reply_leaves_offer_pending_without_an_eta_request(self):
        thread = {"material": "PART", "supplier_id": "SUP-TEST", "qty": 80}
        offer = {"id": "offer", "kind": "partial", "supplier_id": "SUP-TEST", "material": "PART"}
        for text in ("We cannot hold 80.", "We can hold 80 or we can hold 20."):
            with self.subTest(text=text):
                plan = plan_reply({}, thread, text, options=[offer])
                self.assertNotIn("holdUnits", plan)
                self.assertNotIn("shipmentId", plan)
                self.assertIn("hold expiry", plan["nextAction"])

    def test_live_constraints_block_an_option_after_a_matched_reply(self):
        from src.chaser.negotiate import compare
        from src.orchestrator.__main__ import supplier_option_block

        thread = {"material": "PART", "supplier_id": "SUP-TEST", "qty": 80}
        cases = {
            "We cannot make 80 units available in Hamburg before the launch deadline.": "no_launch_cover",
            "The 80 units are on hold pending written confirmation of EXW.": "supplier_hold",
            "Our 80 units cannot be made available by the 22 November cut-off.": "no_launch_cover",
        }
        for text, disposition in cases.items():
            with self.subTest(disposition=disposition):
                plan = plan_reply({}, thread, text)
                self.assertEqual(plan["disposition"], disposition)
                self.assertTrue(all(quote in text for quote in plan["evidence"]))
        generic = plan_reply({}, thread, "We cannot provide a delivered quote before the deadline.")
        self.assertNotIn("disposition", generic)

        with closing(connect(self.path)) as con, con:
            text = "Qty: 80. ETA 2026-11-22 08:00. The units are on hold pending written confirmation of EXW."
            con.execute("""INSERT INTO messages(chase_id,external_id,side,sender,body,time,transport,parsed)
                           VALUES('AB12','example','in','supplier@example.invalid',?,
                           '2026-11-21T13:00:00+00:00','{"mode":"inbox"}','{"reply_plan":{"id":"existing"}}')""", (text,))
            option = {"kind": "alternate", "material": "PART", "supplier_id": "SUP-TEST"}
            self.assertIsNone(supplier_option_block(option, chaser.live_reply_constraints(con)))
            con.commit()
            chaser.reconcile_reply_constraints(con)
            active = chaser.live_reply_constraints(con)
            self.assertEqual(supplier_option_block(option, active)["disposition"], "supplier_hold")
            self.assertEqual(active["SUP-TEST", "PART"]["id"], "existing")
            report = compare(con, "2026-11-22T20:00:00+01:00")["materials"][0]
            self.assertIsNone(report["pick"])
            self.assertTrue(any("release is blocked" in reason for reason in report["ranking"][0]["reasons"]))

    def test_rejected_smtp_attempt_does_not_become_a_sent_email(self):
        with closing(connect(self.path)) as con, patch("src.chaser.smtplib.SMTP") as smtp:
            transport = smtp.return_value.__enter__.return_value
            transport.send_message.side_effect = smtplib.SMTPRecipientsRefused({"supplier@example.invalid": (550, b"rejected")})
            with self.assertRaisesRegex(ValueError, "SMTP rejected"):
                chaser.send(con, "AB12", demo=False)
            thread = next(chaser.list_threads(con))
            self.assertEqual(thread["status"], "send failed")
            self.assertEqual(thread["messages"][0]["transport"]["status"], "failed")
