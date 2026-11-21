"""Exercise shipment changes through the ordinary worker and SMTP claim."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from src import chaser
from src.chaser import recovery
from src.ingest.store import connect, get_state, save_state
from src.orchestrator import __main__ as runner


ENV = {
    "CHASER_NO_TEAM_MAIL": "1", "CHASER_REAL_SMTP": "1", "CHASER_AUTO_SEND": "1",
    "CHASER_SENDER": "test@example.invalid", "CHASER_ALLOWED_DOMAINS": "supplier.invalid",
    "CHASER_SMTP_HOST": "never-connect.invalid", "CHASER_SMTP_PORT": "587", "SOONY_AGENTS": "0",
}


class RecoveryTests(TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "test.db"
        self.clock = datetime.now(timezone.utc).replace(microsecond=0)
        self.deadline = self.clock + timedelta(days=1)
        self.start = self.clock - timedelta(hours=2)
        self.arrival = self.clock + timedelta(hours=3)
        self.opts = SimpleNamespace(data=self.path.parent, db=self.path, demo=False, online=False, once=False)
        self.lot = {"id": "SHP-TEST", "material": "PART-A", "supplier": "ORIGIN",
                    "reference": "CARR-123", "earliest": self.arrival, "quantity": 80, "held": False,
                    "sourceCancelled": False, "sourceUpdatedAt": self.start.isoformat(), "evidence": [{"file": "shipments.csv"}]}
        with closing(connect(self.path)) as con, con:
            chaser.schema(con)
            con.execute("""INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline,message_id)
                           VALUES('A123','ORIGIN','Original','origin@supplier.invalid','en','[SOONY-A123] Plan',
                                  'awaiting reply','PART-A',80,'CARR-123',?,'<sent@example.invalid>')""", (self.deadline.isoformat(),))
            con.execute("""INSERT INTO messages(chase_id,external_id,side,sender,body,time,transport)
                           VALUES('A123','<sent@example.invalid>','out','test@example.invalid','CARR-123',?,?)""",
                        (self.start.isoformat(), json.dumps({"mode": "smtp", "status": "smtp_accepted"})))
            save_state(con, "sourceChecks", {"filesSeen": 1, "rejections": [], "warnings": {}})

    def reply(self, body, unique, minutes, *, chaser_ref="A123"):
        with closing(connect(self.path)) as con:
            chase = con.execute("SELECT * FROM chases WHERE id=?", (chaser_ref,)).fetchone()
            message = EmailMessage()
            message["From"], message["Subject"], message["In-Reply-To"] = chase["address"], chase["subject"], chase["message_id"]
            message["Message-ID"] = f"<{unique}@example.invalid>"
            message["Date"] = format_datetime(self.clock + timedelta(minutes=minutes))
            message.set_content(body)
            return chaser.receive(con, message)

    def truth(self, con, root, *, reconcile_shipments):
        lots, changes = reconcile_shipments([self.lot], self.deadline)
        gap = 100 - 10 - sum(lot["quantity"] for lot in lots if not lot["held"] and lot["earliest"] < self.deadline)
        lots = [{**lot, "earliest": lot["earliest"].isoformat()} for lot in lots]
        suppliers = [{"supplier": dict(
            supplier_id=sid, name=name, contact_email=email, status="active",
            qualification_status=quality, preferred_language="en",
        )} for sid, name, email, quality in (
            ("ORIGIN", "Original", "origin@supplier.invalid", "qualified"),
            ("ALT", "Alternative", "alt@supplier.invalid", "qualified"),
            ("NEW", "Unqualified", "new@supplier.invalid", "conditional"),
        )]
        return {**changes, "deadline": self.deadline.isoformat(), "inbound": lots, "editions": {},
                "shifts": [[self.start.isoformat(), self.deadline.isoformat()]], "parts": {
                    "PART-A": {"shortfall": gap, "suppliers": suppliers}}, "issues": []}

    def test_worker_replans_and_sends_once_per_qualified_supplier(self):
        cancellation = "Shipment CARR-123 has been cancelled."
        self.assertTrue(self.reply(cancellation, "cancel", 1))
        with (
            patch.dict("os.environ", ENV),
            patch.object(runner, "ingest", return_value=[]),
            patch.object(runner, "extract", return_value=0),
            patch.object(runner, "reconcile_handwriting", return_value=0),
            patch.object(runner, "readiness", side_effect=self.truth),
            patch.object(runner, "choose", return_value=[]),
            patch("src.chaser.draft", return_value=0),
            patch("src.chaser.poll", return_value=0),
            patch("src.chaser.authenticate"),
            patch("src.chaser.smtplib.SMTP") as smtp,
        ):
            transport = smtp.return_value.__enter__.return_value.send_message
            transport.return_value = {}
            runner.Loop(self.opts).cycle()
            runner.Loop(self.opts).cycle()
            self.assertEqual(transport.call_count, 2)
            sent = {call.args[0]["To"]:call.args[0] for call in transport.call_args_list}
            self.assertEqual(set(sent), {"origin@supplier.invalid", "alt@supplier.invalid"})
            self.assertEqual(sent["origin@supplier.invalid"]["In-Reply-To"], "<cancel@example.invalid>")
            self.assertIsNone(sent["alt@supplier.invalid"]["In-Reply-To"])
            with closing(connect(self.path)) as con:
                truth = get_state(con, "truth")
                self.assertEqual(truth["parts"]["PART-A"]["shortfall"], 90)
                self.assertEqual(truth["inbound"], [])
                actions = recovery.view(con)
                self.assertEqual([a["status"] for a in actions], ["escalated", "awaiting_reply", "awaiting_reply"])
                alternative = actions[-1]["threadId"]
            confirmed = (self.arrival + timedelta(hours=2)).isoformat()
            self.assertTrue(self.reply(f"Quantity: 90\nDC-HAM ETA: {confirmed}\nEUR 2.00 per unit.",
                                       "backup-offer", 3, chaser_ref=alternative))
            runner.Loop(self.opts).cycle()
            self.assertEqual(transport.call_count, 2)
            with closing(connect(self.path)) as con:
                offer = next(action for action in recovery.view(con) if action["threadId"] == alternative)
                self.assertEqual(offer["status"], "approval_required")
                self.assertEqual(get_state(con, "truth")["parts"]["PART-A"]["shortfall"], 90)
            self.assertTrue(self.reply("Shipment CARR-123 is reinstated.", "restore", 5))
            self.assertTrue(self.reply(cancellation, "older-retransmit", 2))
            runner.Loop(self.opts).cycle()
            with closing(connect(self.path)) as con:
                self.assertEqual(get_state(con, "truth")["parts"]["PART-A"]["shortfall"], 10)
                self.assertEqual(recovery.view(con), [])
            self.assertEqual(transport.call_count, 2)

    def test_late_erp_and_exact_email_revisions(self):
        with closing(connect(self.path)) as con:
            _, previous = recovery.reconcile(con, [self.lot], self.deadline, {})
            late = {**self.lot, "earliest": self.deadline + timedelta(hours=1)}
            _, state = recovery.reconcile(con, [late], self.deadline, previous)
            self.assertEqual(state["shipmentChanges"][0]["lostUnits"], 80)
            cancelled = {**self.lot, "sourceCancelled": True, "quantity": 0, "earliest": None}
            inbound, state = recovery.reconcile(con, [cancelled], self.deadline, previous)
            self.assertEqual((inbound, state["shipmentChanges"][0]["kind"]), ([], "cancelled"))
        self.assertTrue(self.reply("The other shipment was cancelled. We will update CARR-555.", "other", 1))
        self.assertTrue(self.reply("The other shipment was cancelled. CARR-123 is still moving.", "unrelated", 1))
        self.assertTrue(self.reply("CARR-123 was not cancelled.\n-----Original Message-----\nCARR-123 was cancelled.", "quote", 2))
        self.assertTrue(self.reply(f"CARR-123\nShipment quantity: 34\nDC-HAM ETA: {self.arrival.isoformat()}", "reduced", 3))
        with closing(connect(self.path)) as con:
            inbound, state = recovery.reconcile(con, [self.lot], self.deadline, {})
        self.assertEqual(inbound[0]["quantity"], 34)
        self.assertEqual(state["shipmentChanges"][0]["lostUnits"], 46)

    def test_unchanged_shipments_keep_the_forecast_draw_order(self):
        lots = [self.lot, {**self.lot, "id": "SHP-ALT", "supplier": "ALT"},
                {**self.lot, "id": "SHP-NEXT"}]
        with closing(connect(self.path)) as con:
            revised, state = recovery.reconcile(con, lots, self.deadline, {})
        self.assertEqual([lot["id"] for lot in revised], [lot["id"] for lot in lots])
        self.assertEqual(state["shipmentChanges"], [])

    def test_withdrawn_offer_stays_out_of_the_approval_queue(self):
        self.assertTrue(self.reply("Quantity: 12\nEUR 2.00 per unit.", "quote", 1))
        self.assertTrue(self.reply("Our offer has been withdrawn.", "withdraw", 2))
        with closing(connect(self.path)) as con:
            truth = self.truth(con, None, reconcile_shipments=lambda lots, due: recovery.reconcile(con, lots, due, {}))
            recovery.advance(con, truth, clock=self.clock)
            self.assertEqual(truth["parts"]["PART-A"]["shortfall"], 10)
            self.assertIn("withdrawn", recovery.view(con)[0]["title"])
            con.execute("CREATE TABLE deals(id,thread_id)")
            con.execute("INSERT INTO deals VALUES('offer','A123')")
            self.assertTrue(recovery.superseded_offer(con, "offer"))
