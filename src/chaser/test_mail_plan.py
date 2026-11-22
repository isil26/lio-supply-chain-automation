import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch

from src import chaser
from src.chaser import autosend, mail_plan
from src.chaser.followup import answer_replies
from src.ingest.store import connect


class MailPlanningTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "procurement.db"
        self.db = connect(self.path)
        self.addCleanup(lambda: self.db.close())
        chaser.schema(self.db)
        self.add_thread("A1")

    def add_thread(self, ref, parent=None):
        with self.db:
            self.db.execute("""INSERT INTO chases
                (id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline,message_id,parent_thread_id)
                VALUES(?, 'SUP-74','North Works','sales@suppliers.juliansibbing.de','en',?,'awaiting reply',
                       'HINGE-7',80,'Please quote the hinges.','2031-08-12T12:00:00+00:00',?,?)""",
                            (ref, f"[SOONY-{ref}] Hinges", f"<out-{ref}>", parent))
            self.db.execute("""INSERT INTO messages(chase_id,external_id,side,sender,body,time,transport)
                VALUES(?,?,'out','team@example.test','Please quote the hinges.','2031-08-09T08:00:00Z',?)""",
                            (ref, f"<out-{ref}>", json.dumps({"mode":"smtp", "status":"smtp_accepted"})))

    def receive(self, ref, body, mid, hour=9):
        msg = EmailMessage()
        msg["From"] = "sales@suppliers.juliansibbing.de"
        msg["To"] = "team@example.test"
        msg["Subject"] = f"Re: [SOONY-{ref}] Hinges"
        msg["Date"] = f"Sat, 09 Aug 2031 {hour:02}:00:00 +0000"
        msg["Message-ID"] = f"<{mid}>"
        msg["In-Reply-To"] = f"<out-{ref}>"
        msg.set_content(body)
        return chaser.receive(self.db, msg)

    def current(self, ref="A1"):
        return mail_plan.contexts(self.db, ref)[ref]["plan"]

    def test_approval_and_wait_survive_restart_and_out_of_order_replies(self):
        self.receive("A1", "Collection requires a written buyer release under the existing order.", "release", 10)
        self.assertEqual(self.current()["owner"], "Procurement")
        self.assertEqual(answer_replies(self.db, save=True), [])
        self.db.close()
        self.db = connect(self.path)
        self.receive("A1", "We will check the truck time.", "older", 9)
        self.assertEqual(self.current()["state"], "approval")
        self.add_thread("B2", parent="A1")
        self.receive("B2", "We will forward the timed trucking proposal tomorrow morning.", "promise", 11)
        self.assertEqual(self.current()["state"], "waiting")
        self.assertEqual(self.current("B2"), self.current())
        self.assertFalse(self.receive("B2", "We will forward the timed trucking proposal tomorrow morning.", "promise", 11))
        before = datetime(2031, 8, 9, 11, 10, tzinfo=timezone.utc)
        after = datetime(2031, 8, 11, 15, tzinfo=timezone.utc)
        for clock in [before, after, after]:
            with self.db:
                mail_plan.record_checkpoints(self.db, mail_plan.contexts(self.db), clock)
        self.assertEqual(self.db.execute("SELECT count(*) FROM activity WHERE action LIKE '%update is due%'").fetchone()[0], 1)
        thread = next(row for row in chaser.list_threads(self.db) if row["id"] == "B2")
        self.assertEqual(thread["mailPlan"]["owner"], "Supplier")
        self.add_thread("C3")
        self.receive("C3", "No expedited service is available.", "refused", 12)
        self.assertEqual(self.current("C3")["state"], "unavailable")
        self.assertEqual(self.current()["state"], "waiting")

    def test_new_reply_retires_queued_question_before_transport(self):
        self.receive("A1", "Here is the preliminary shipment reference SHP-7.", "partial")
        planned, = answer_replies(self.db, save=True)
        self.receive("A1", "Please approve the freight charge before we book the carrier.", "approval", 10)
        sent = []
        results = autosend.run(self.db, prepare=False, send=lambda _, ref: sent.append(ref))
        self.assertFalse(sent)
        self.assertEqual(results[0]["result"], "superseded")
        self.assertEqual(self.current()["owner"], "Logistics and Procurement")
        self.assertEqual(self.db.execute("SELECT status FROM chases WHERE id=?", (planned["draft_id"],)).fetchone()[0],
                         "superseded draft")

    def test_backfill_and_courtesy_ack_leave_the_actionable_reply_answerable(self):
        self.receive("A1", "Hinges ready for pickup at our warehouse.", "pickup", 11)
        self.receive("A1", "We will check the truck time.", "late-import", 9)
        self.receive("A1", "Thanks for the update.", "thanks", 12)
        draft, = answer_replies(self.db, save=True)
        source = self.db.execute("""SELECT m.external_id FROM chases c JOIN messages m ON m.id=c.based_on_reply_id
                                    WHERE c.id=?""", (draft["draft_id"],)).fetchone()
        self.assertEqual(source[0], "<pickup>")

    def test_received_answer_retires_an_unsent_reminder(self):
        from .followup import due_reminders
        due = datetime(2031, 8, 10, 11, tzinfo=timezone.utc)
        reminder, = due_reminders(self.db, due, save=True)
        self.receive("A1", "Hinges ready for pickup at our warehouse.", "pickup")
        sent = []
        outcomes = autosend.run(self.db, prepare=False, send=lambda _, ref: sent.append(ref))
        self.assertFalse(sent)
        self.assertEqual([(result["id"], result["result"]) for result in outcomes], [(reminder["draft_id"], "superseded")])

    def promise_forecast(self, gap=24):
        from src.ingest.store import save_state
        with self.db:
            save_state(self.db, "truth", {"deadline": "2031-08-12T12:00:00Z", "parts": {
                "HINGE-7": {"shortfall": gap, "suppliers": [{"supplier_id": "SUP-74", "supplier": {"status": "active"}}]}}})

    def test_due_nonbinding_followup_uses_current_scenario_and_sends_once(self):
        from . import promise_watch
        self.promise_forecast()
        self.receive("A1", "We will send the quotation tomorrow morning CET.", "offered-update")
        early = datetime(2031, 8, 10, 10, tzinfo=timezone.utc)
        due = datetime(2031, 8, 10, 11, tzinfo=timezone.utc)
        self.assertEqual(promise_watch.opportunities(self.db, early), {})
        planned, = promise_watch.opportunities(self.db, due).values()
        self.assertEqual(planned[1], 24)
        self.assertIn("HINGE-7", planned[2])
        self.assertNotIn("Hamburg", planned[2])
        env = {"CHASER_REAL_SMTP":"1", "CHASER_SENDER":"team@example.test", "CHASER_SMTP_PORT":"587",
               "CHASER_SMTP_HOST":"unused.test", "CHASER_AUTO_COOLDOWN_MIN":"0"}
        class AtDueTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return due
        with patch.dict(os.environ, env), patch("src.chaser.mailenv.load_team_mail_env"), patch(
                "src.chaser.datetime", AtDueTime), patch("src.chaser.deadlines.datetime", AtDueTime), patch(
                "src.chaser.smtplib.SMTP") as smtp:
            client = smtp.return_value.__enter__.return_value
            client.send_message.return_value = {}
            autosend.run(self.db, now=due)
            self.db.close()
            self.db = connect(self.path)
            autosend.run(self.db, now=due)
            self.assertEqual(client.send_message.call_count, 1)
            message = client.send_message.call_args.args[0]
            self.assertEqual(message["In-Reply-To"], "<offered-update>")
            self.assertEqual(message["To"], "sales@suppliers.juliansibbing.de")

    def test_promise_yields_to_closed_gap_new_decision_or_source_removal(self):
        from . import promise_watch
        self.promise_forecast()
        self.receive("A1", "We will check the carrier availability.", "waiting")
        clock = datetime(2031, 8, 10, 16, tzinfo=timezone.utc)
        promise_watch.prepare(self.db, clock)
        draft = self.db.execute("SELECT * FROM chases WHERE status='promise draft'").fetchone()
        self.assertTrue(promise_watch.current(self.db, draft, clock))
        self.promise_forecast(gap=0)
        self.assertFalse(promise_watch.current(self.db, draft, clock))
        from src.ingest.store import save_state
        with self.db:
            save_state(self.db, "truth", {"deadline": "2031-08-12T12:00:00Z", "parts": {
                "HINGE-7": {"shortfall": 24, "suppliers": [{"supplier_id": "OTHER", "supplier": {"status": "active"}}]}}})
        self.assertFalse(promise_watch.current(self.db, draft, clock))
        self.promise_forecast()
        self.receive("A1", "Please approve the freight charge before booking.", "authority", 11)
        self.assertFalse(promise_watch.current(self.db, draft, clock))
        sent = []
        autosend.run(self.db, now=clock, prepare=False, send=lambda _, ref: sent.append(ref))
        self.assertEqual(sent, [])
        self.assertEqual(self.db.execute("SELECT status FROM chases WHERE id=?", (draft["id"],)).fetchone()[0], "superseded draft")

    def test_relative_promises_and_other_timezones(self):
        from .promise_watch import checkpoint
        received = datetime(2031, 8, 9, 22, tzinfo=timezone.utc)
        cutoff = datetime(2031, 8, 12, 12, tzinfo=timezone.utc)
        self.assertEqual(checkpoint("We will reply within 3 hours.", received, cutoff),
                         (datetime(2031, 8, 10, 1, tzinfo=timezone.utc), True))
        self.assertEqual(checkpoint("We will reply tomorrow at 09:00 JST.", received, cutoff),
                         (datetime(2031, 8, 11, tzinfo=timezone.utc), True))
        self.assertEqual(checkpoint("We will reply on 2031-08-11 at 14:00 UTC.", received, cutoff),
                         (datetime(2031, 8, 11, 14, tzinfo=timezone.utc), True))
        self.assertFalse(checkpoint("We will reply next business day.", received, cutoff)[1])

    def test_generic_answer_replies_in_original_mail_chain(self):
        self.receive("A1", "Hinges ready for pickup at our warehouse.", "offer")
        planned, = answer_replies(self.db, save=True)
        env = {"CHASER_AUTO_COOLDOWN_MIN":"0", "CHASER_REAL_SMTP":"1", "CHASER_SENDER":"team@example.test", "CHASER_SMTP_HOST":"unused.test"}
        with patch.dict(os.environ, env), patch("src.chaser.mailenv.load_team_mail_env"), patch("src.chaser.smtplib.SMTP") as smtp:
            client = smtp.return_value.__enter__.return_value
            client.send_message.return_value = {}
            chaser.send(self.db, planned["draft_id"], auto=True)
            message = client.send_message.call_args.args[0]
            self.assertEqual(message["In-Reply-To"], "<offer>")
            self.assertIn("<out-A1>", message["References"])

    def test_late_reply_to_revised_offer_to_approved_response_survives_restart(self):
        from . import deals
        from .negotiate import compare

        clock = datetime(2031, 8, 9, 14, tzinfo=timezone.utc)
        cutoff = "2031-08-12T12:00:00Z"
        self.receive("A1", "80 units. ETA 2031-08-14 10:00Z. EUR 4 per unit.", "late")
        case = compare(self.db, cutoff, save=True, model=False, now=clock)["materials"][0]
        self.assertEqual(case["plan"]["uncovered"], 80)
        expedite = case["negotiations"][0]
        self.assertEqual(expedite["asks"][0]["lever"], "expedite")
        self.receive("A1", "80 units. ETA 2031-08-11 10:00Z. EUR 5 per unit. AWB 020-12345678.", "faster", 10)
        env = {"CHASER_AUTO_COOLDOWN_MIN":"0", "CHASER_REAL_SMTP":"1", "CHASER_SENDER":"team@example.test",
               "CHASER_SMTP_HOST":"unused.test", "CHASER_SMTP_PORT":"587"}
        with patch.dict(os.environ, env), patch("src.chaser.mailenv.load_team_mail_env"), patch(
                "src.chaser.smtplib.SMTP") as smtp, patch.object(deals, "_now", return_value=clock.isoformat()):
            client = smtp.return_value.__enter__.return_value
            client.send_message.return_value = {}
            deals.sync(self.db, cutoff, now=clock, model=False)
            firm, = deals.list_deals(self.db)["best"]
            self.assertEqual(firm["total_eur"], 400)
            decision = deals.decide(self.db, firm["id"], "approve", "Buyer", revision=firm["revision"])
            preview = firm["drafts"]["approve"]
            self.assertEqual(tuple(self.db.execute("SELECT subject, body FROM chases WHERE id=?", (decision["email_id"],)).fetchone()),
                             (preview["subject"], preview["body"]))
            first = autosend.run(self.db, now=clock)
            self.assertEqual([r["id"] for r in first if r["result"]=="sent"], [decision["email_id"]])
            message = client.send_message.call_args.args[0]
            self.assertEqual(message["In-Reply-To"], "<faster>")
            self.db.close()
            self.db = connect(self.path)
            deals.decide(self.db, firm["id"], "approve", "Buyer", revision=firm["revision"])
            autosend.run(self.db, now=clock)
            self.assertEqual(client.send_message.call_count, 1)

    def test_quoted_or_simulated_text_does_not_block_real_conversation(self):
        self.assertIsNone(mail_plan.classify("Thank you.\n> Please approve the freight charge."))
        with self.db:
            self.db.execute("""INSERT INTO messages(chase_id,side,external_id,sender,body,time,transport)
              VALUES('A1','in','<mock>','fixture','Please issue a formal PO.','2031-08-09T11:00:00Z','{"mode":"simulated"}')""")
        self.assertFalse(mail_plan.blocks_automation(self.db, "A1"))
        self.assertEqual(mail_plan.contexts(self.db, "A1", simulated=True)["A1"]["plan"]["state"], "approval")
