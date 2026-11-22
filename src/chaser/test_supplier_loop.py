"""Regression checks for supplier decisions and at-most-once dispatch."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from src import chaser
from src.chaser import supplier_loop as loop
from src.ingest.store import connect, save_state


WHEN = datetime(2026, 11, 21, 15, tzinfo=timezone.utc)
CUT_OFF = "2026-11-22T20:00:00+01:00"
ADDRESS = "test@suppliers.juliansibbing.de"


class SupplierLoopTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "soony.db"
        self.db = connect(self.path)
        self.addCleanup(self.db.close)
        chaser.schema(self.db)
        self.truth = {
            "deadline": CUT_OFF,
            "shifts": [["2026-11-22T06:00:00+01:00", CUT_OFF]],
            "parts": {loop.CARD[1]: {"shortfall": 6800}, loop.BOOK[1]: {"shortfall": 5900}},
            "inbound": [{"id": loop.SHIPMENT, "material": loop.CARD[1], "supplier": loop.CARD[0],
                         "held": False, "quantity": 28000, "earliest": "2026-11-22T12:00:00+01:00"}],
            "model": {"runs": 4}, "editions": {"STD": {"edition": "Standard"}},
        }
        self.options = [
            {"kind": "inbound", "id": "dock", "shipment_id": loop.SHIPMENT, "owner": "Site lead"},
            {"kind": "partial", "id": "offer", "supplier_id": loop.BOOK[0], "material": loop.BOOK[1], "price": 12390},
        ]
        with self.db:
            self.db.execute("""CREATE TABLE suppliers(supplier_id TEXT,name TEXT,contact_email TEXT,
                                                      preferred_language TEXT,contact_name TEXT)""")
            self.db.executemany("INSERT INTO suppliers VALUES (?,? ,?,'en','Contact')",
                                [(loop.CARD[0], "Card supplier", ADDRESS), (loop.BOOK[0], "Karton Nowak", ADDRESS)])
            save_state(self.db, "truth", self.truth)
            save_state(self.db, "options", self.options)

    def sent(self, case, thread, body, mode):
        mid = f"<{thread}@example.invalid>"
        with self.db:
            self.db.execute("""INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,
                                 material,qty,body,deadline,message_id)
                               VALUES(?,?,?,?,'en',?,'awaiting reply',?,?,?, ?,?)""",
                            (thread, case[0], "Supplier", ADDRESS, f"[SOONY-{thread}] Test",
                             case[1], self.truth["parts"][case[1]]["shortfall"], body, CUT_OFF, mid))
            self.db.execute("""INSERT INTO messages(chase_id,external_id,side,sender,body,time,transport)
                               VALUES(?,?,'out',?,?,?,?)""",
                            (thread, mid, "test@example.invalid", body, WHEN.isoformat(),
                             json.dumps({"mode": mode, "status": "dry_run" if mode == "dry_run" else "gmail_sent"})))
        return mid

    def reply(self, thread, mid, message_id, body, offset, *, simulated=False, address=ADDRESS, docs=()):
        message = EmailMessage()
        message["From"] = address
        message["Subject"] = f"Re: [SOONY-{thread}] Test"
        message["Date"] = format_datetime(WHEN + timedelta(minutes=offset))
        message["In-Reply-To"] = mid
        message["Message-ID"] = f"<{message_id}@example.invalid>"
        message.set_content(body)
        for doc in docs:
            message.add_attachment(f"Controlled fixture: {doc}.", filename=f"{doc}.txt")
        return chaser.receive(self.db, message, simulated=simulated)

    def test_later_card_revision_wins_even_if_an_older_reply_arrives_afterward(self):
        mid = self.sent(loop.CARD, "A001", f"Please confirm {loop.SHIPMENT}.", "dry_run")
        early = loop.sample_card_reply(self.truth, "on-time")
        late = loop.sample_card_reply(self.truth, "delayed")
        metrics = {"editions": {"STD": {"p50": 600, "p90": 675, "probability": 0.1}}}
        with patch("src.chaser.reply_plan.counterfactual", return_value=metrics), patch.object(loop, "counterfactual", return_value=metrics):
            self.assertTrue(self.reply("A001", mid, "early", early, 20, simulated=True))
            loop.advance(self.db, self.truth, self.options, scope="demo", clock=WHEN, dispatch=False)
            self.assertEqual(loop.view(self.db, "demo")[0]["kind"], "approve_dock")
            self.assertTrue(self.reply("A001", mid, "late", late, 30, simulated=True))
            self.assertFalse(self.reply("A001", mid, "late", late, 30, simulated=True))
            self.assertTrue(self.reply("A001", mid, "older", early + "\nOriginal update.", 25, simulated=True))
            self.assertTrue(self.reply("A001", mid, "retransmit", early, 35, simulated=True))
            self.assertFalse(self.reply("A001", "<unrelated@example.invalid>", "wrong", early, 40, simulated=True))
            self.assertFalse(self.reply("A001", mid, "sender", early, 40, simulated=True, address="other@example.invalid"))
            self.assertFalse(self.reply("A001", mid, "mode", early, 40))
            loop.advance(self.db, self.truth, self.options, scope="demo", clock=WHEN, dispatch=False)
            action = loop.view(self.db, "demo")[0]
            self.assertEqual(action["kind"], "review_recovery")
            self.assertEqual(action["transport"]["messageId"], mid)
            self.assertEqual(self.db.execute("SELECT count(*) FROM messages WHERE side='out'").fetchone()[0], 1)

    def test_karton_pending_exception_and_firm_denial_route_separately_from_offer(self):
        quote = self.sent(loop.BOOK, "B001", "Can you hold finished stock?", "gmail")
        small = self.sent(loop.BOOK, "B002", "Would you accept a 50–100 unit order below the minimum?", "gmail")
        self.assertTrue(self.reply("B001", quote, "offer", "Możemy zarezerwować 5 900 z dostępnych 8 000. 2,10 EUR za sztukę.", 10))
        pending = ("Standardowe minimum zamówienia dla CMP-GAM-008 wynosi 5 000 sztuk. "
                   "Sprawdzę wewnętrznie, czy możemy jednorazowo zaoferować mniejszą ilość.")
        self.assertTrue(self.reply("B002", small, "pending", pending, 25))
        with patch("src.chaser.send") as send:
            loop.advance(self.db, self.truth, self.options, scope="verified", clock=WHEN + timedelta(minutes=30))
            result = {a["kind"]: a for a in loop.view(self.db, "verified")}
            self.assertEqual(result["review_cover"]["reportedUnits"], 5900)
            waiting = result["await_small_lot_exception"]
            self.assertIn("5,000 units", waiting["detail"])
            self.assertEqual(waiting["status"], "awaiting_reply")
            self.assertTrue(self.reply("B002", small, "denied", "We cannot accept the 50–100 unit order.", 40))
            loop.advance(self.db, self.truth, self.options, scope="verified", clock=WHEN + timedelta(minutes=45))
            result = {a["kind"]: a for a in loop.view(self.db, "verified")}
            self.assertIn("review_cover", result)
            self.assertEqual(result["review_minimum"]["status"], "escalated")
            self.assertNotIn("await_small_lot_exception", result)
            send.assert_not_called()
        self.assertEqual(self.db.execute("SELECT count(*) FROM messages WHERE side='out'").fetchone()[0], 2)

    @patch.dict("os.environ", {"CHASER_SENDER": "test@example.invalid"})
    def test_complete_reply_cancels_queued_followup_before_transport_claim(self):
        mid = self.sent(loop.CARD, "A002", f"Please confirm {loop.SHIPMENT}.", "dry_run")
        early = loop.sample_card_reply(self.truth, "on-time")
        complete = loop.sample_card_reply(self.truth, "complete")
        metrics = {"editions": {"STD": {"p50": 600, "p90": 675, "probability": 0.1}}}
        with patch("src.chaser.reply_plan.counterfactual", return_value=metrics), patch.object(loop, "counterfactual", return_value=metrics):
            self.assertTrue(self.reply("A002", mid, "partial", early, 20, simulated=True))
            loop.advance(self.db, self.truth, self.options[:1], scope="demo", clock=WHEN, dispatch=False)
            draft = next(a for a in loop.view(self.db, "demo") if a["kind"] == "customs_followup")
            self.assertEqual(draft["status"], "queued")
            self.assertTrue(self.reply("A002", mid, "complete", complete, 25, simulated=True,
                                       docs=("Commercial invoice", "Packing list", "Air waybill")))
            with self.assertRaises(ValueError):
                chaser.send(self.db, draft["dispatchThread"], demo=True, managed=True)
            loop.advance(self.db, self.truth, self.options[:1], scope="demo", clock=WHEN)
            self.assertEqual([a["kind"] for a in loop.view(self.db, "demo")], ["approve_dock"])
            self.assertEqual(self.db.execute("SELECT count(*) FROM messages WHERE side='out'").fetchone()[0], 1)

    def test_worker_counts_attachment_only_revisions_before_followup(self):
        from src.orchestrator import __main__ as runner

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return WHEN + timedelta(minutes=45)

        body = loop.sample_card_reply(self.truth, "complete")
        documents = ("Commercial invoice", "Packing list", "Air waybill")
        metrics = {"editions": {"STD": {"p50": 600, "p90": 675, "probability": 0.1}}}
        for batches in ((documents,), (documents[:1], documents[1:])):
            with self.subTest(batches=batches):
                with self.db:
                    self.db.execute("DELETE FROM supplier_loop_actions")
                    self.db.execute("DELETE FROM messages")
                    self.db.execute("DELETE FROM chases")
                    save_state(self.db, "sourceChecks", {"filesSeen": 1, "rejections": [], "warnings": {}})
                    save_state(self.db, "options", self.options[:1])
                mid = self.sent(loop.CARD, "A003", f"Please confirm {loop.SHIPMENT}.", "dry_run")
                with (
                    patch("src.chaser.reply_plan.counterfactual", return_value=metrics),
                    patch.object(loop, "counterfactual", return_value=metrics),
                    patch.object(loop, "datetime", Clock),
                    patch.object(runner, "ingest", return_value=[]),
                    patch.object(runner, "extract", return_value=0),
                    patch.object(runner, "reconcile_handwriting", return_value=0),
                    # This worker fixture contains only supplier mail and its stock requirements.
                    patch.object(runner, "dashboard", return_value={"actions": []}),
                    patch.dict("os.environ", {"CHASER_REAL_SMTP": "0", "SOONY_AGENTS": "0"}),
                ):
                    self.assertTrue(self.reply("A003", mid, "no-docs", body, 10, simulated=True))
                    loop.advance(self.db, self.truth, self.options[:1], scope="demo", dispatch=False)
                    self.assertIn("customs_followup", {a["kind"] for a in loop.view(self.db, "demo")})
                    for index, batch in enumerate(batches, 1):
                        self.assertTrue(self.reply("A003", mid, f"docs-{index}", body, 10 + index,
                                                   simulated=True, docs=batch))
                    self.assertTrue(self.reply("A003", mid, "retransmitted-docs", body, 30,
                                               simulated=True, docs=batches[-1]))
                    worker = runner.Loop(SimpleNamespace(data=self.path.parent / "inputs", demo=True,
                                                         replay_dir=self.path.parent, online=False, once=False))
                    worker.initialized = True
                    worker.cycle()
                    worker.cycle()
                    actions = loop.view(self.db, "demo")
                    self.assertEqual([a["kind"] for a in actions], ["approve_dock"])
                    reply_id = self.db.execute("SELECT id FROM messages WHERE external_id=?",
                                               (f"<docs-{len(batches)}@example.invalid>",)).fetchone()[0]
                    self.assertEqual(actions[0]["replyId"], reply_id)
                    self.assertEqual(self.db.execute("SELECT count(*) FROM messages WHERE side='out'").fetchone()[0], 1)

    def test_carrier_confirmation_pending_keeps_the_dock_decision_waiting(self):
        mid = self.sent(loop.CARD, "A004", f"Please confirm {loop.SHIPMENT}.", "dry_run")
        body = f"{loop.SHIPMENT} confirmed. We are checking with the carrier and will send the arrival time."
        self.assertTrue(self.reply("A004", mid, "pending-carrier", body, 18, simulated=True))
        loop.advance(self.db, self.truth, self.options[:1], scope="demo", clock=WHEN + timedelta(minutes=30))
        action, = loop.view(self.db, "demo")
        self.assertEqual(action["kind"], "await_carrier_eta")
        self.assertEqual(action["status"], "awaiting_reply")
        self.assertEqual(self.db.execute("SELECT count(*) FROM messages WHERE side='out'").fetchone()[0], 1)

    @patch.dict("os.environ", {"CHASER_REAL_SMTP": "1", "CHASER_AUTO_SEND": "1",
                              "CHASER_SMTP_HOST": "test.invalid", "CHASER_SMTP_PORT": "587",
                              "CHASER_SENDER": "test@example.invalid", "SOONY_AGENTS": "0"})
    def test_live_worker_reuses_verified_karton_thread_for_one_due_status_request(self):
        from src.orchestrator import __main__ as runner

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return WHEN + timedelta(hours=3)

        mid = self.sent(loop.BOOK, "B003", "Would you accept a 50–100 unit order below the minimum?", "gmail")
        self.assertTrue(self.reply("B003", mid, "pending", "Minimum order is 5,000 units. We are checking internally.", 10))
        history = self.path.parent / "mail-history.db"
        with closing(connect(history)) as checkpoint:
            self.db.backup(checkpoint)
        with self.db:
            self.db.execute("DELETE FROM messages")
            self.db.execute("DELETE FROM chases")
            save_state(self.db, "options", self.options[1:])
            save_state(self.db, "sourceChecks", {"filesSeen": 1, "rejections": [], "warnings": {}})
        def cycle():
            worker = runner.Loop(SimpleNamespace(data=self.path.parent, db=self.path, demo=False, online=False, once=False))
            worker.initialized = True
            return worker.cycle()
        with (
            patch.dict("os.environ", {"SOONY_MAIL_HISTORY_DB": str(history)}),
            patch.object(loop, "datetime", Clock),
            patch.object(runner, "ingest", return_value=[]),
            patch.object(runner, "extract", return_value=0),
            patch.object(runner, "reconcile_handwriting", return_value=0),
            # The mail fixture has a published forecast but no raw planning tables.
            patch.object(runner, "readiness", return_value=self.truth) as readiness,
            patch.object(runner, "choose", return_value=self.options[1:]),
            patch.object(runner, "source_proposals", return_value=[]),
            patch("src.chaser.draft", return_value=0),
            patch.object(runner, "datetime", Clock),
            patch.object(runner, "dashboard", return_value={"actions": []}),
            patch("src.chaser.poll", return_value=0),
            patch("src.chaser.mailenv.load_team_mail_env"),
            patch("src.chaser.authenticate"),
            patch("src.chaser.smtplib.SMTP") as smtp,
        ):
            receiver = smtp.return_value.__enter__.return_value
            receiver.send_message.return_value = {}
            cycle()
            cycle()
            readiness.assert_called_once()
            watch = runner.get_state(self.db, runner.deal_watch.KEY)
            self.assertEqual(watch["reviewedThrough"], runner.recovery.watermark(self.db))
            self.assertEqual(watch["status"], "active")
            receiver.send_message.assert_called_once()
            message = receiver.send_message.call_args.args[0]
            self.assertEqual(message["In-Reply-To"], "<pending@example.invalid>")
            self.assertIn(mid, message["References"])
            self.assertIn("karton_status_followup", {a["kind"] for a in loop.view(self.db, "live")})
        self.assertEqual(self.db.execute("SELECT count(*) FROM messages WHERE side='out'").fetchone()[0], 2)

    @patch.dict("os.environ", {"CHASER_REAL_SMTP": "1", "CHASER_SMTP_HOST": "test.invalid",
                              "CHASER_SMTP_PORT": "587", "CHASER_SENDER": "test@example.invalid"})
    def test_uncertain_transport_is_claimed_once_across_workers_and_restart(self):
        loop.advance(self.db, self.truth, self.options, scope="live", clock=WHEN, dispatch=False)
        action = next(a for a in loop.view(self.db, "live") if a["case"] == "game_card")
        self.assertEqual(action["status"], "queued")

        def attempt():
            with closing(connect(self.path)) as con:
                with self.assertRaises(ValueError):
                    chaser.send(con, action["threadId"], managed=True)

        with patch("src.chaser.mailenv.load_team_mail_env"), patch("src.chaser.authenticate"), patch("src.chaser.smtplib.SMTP") as smtp:
            smtp.return_value.__enter__.return_value.send_message.side_effect = chaser.smtplib.SMTPServerDisconnected()
            with ThreadPoolExecutor(max_workers=2) as workers:
                list(workers.map(lambda _: attempt(), range(2)))
            attempt()
            self.assertEqual(smtp.return_value.__enter__.return_value.send_message.call_count, 1)

        loop.advance(self.db, self.truth, self.options, scope="live", clock=WHEN)
        action = next(a for a in loop.view(self.db, "live") if a["case"] == "game_card")
        self.assertEqual(action["kind"], "reconcile_dispatch")
        self.assertEqual(action["transport"]["status"], "delivery_uncertain")
        self.assertEqual(self.db.execute("SELECT count(*) FROM messages WHERE side='out'").fetchone()[0], 1)
