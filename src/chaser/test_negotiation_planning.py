import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from . import schema
from .autosend import run
from .negotiate import compare, is_late_offer

NOW = datetime(2031, 6, 5, 11, tzinfo=timezone.utc)
CUTOFF = "2031-06-05T14:00:00+02:00"


def thread(con, key="A1", supplier="Willow", deadline=CUTOFF, need=75, lang="en"):
    con.execute("""INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (key, supplier, supplier, f"{supplier}@example.invalid", lang,
                   f"[SOONY-{key}] Hinge enquiry", "awaiting reply", "HINGE-37", need, "Price and arrival?", deadline))
    con.execute("""INSERT INTO messages(chase_id,external_id,side,sender,body,time,transport)
                   VALUES(?,?,'out','buyer','Please quote','2031-06-04T10:00:00Z',?)""",
                (key, key + "-out", json.dumps({"mode": "smtp", "status": "smtp_accepted"})))


def reply(con, key, text, authored="2031-06-05T10:00:00Z", mode="inbox"):
    m = con.execute("""INSERT INTO messages(chase_id,side,sender,body,time,transport)
                     VALUES(?,'in','supplier',?,'2031-06-05T10:55:00Z',?)""",
                  (key, text, json.dumps({"mode": mode, "authoredAt": authored, "inReplyTo": key + "-out"})))
    return m.lastrowid


class NegotiationPlanningTest(unittest.TestCase):
    def test_partial_gap_recovery_from_late_offer_persists_once_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mail.db"
            with closing(sqlite3.connect(path)) as con:
                schema(con)
                thread(con, "A1", "Alder")
                reply(con, "A1", "35 units; ETA 2031-06-05 12:30+02:00. EUR 4 per unit.")
                thread(con, "B2", "Birch")
                source = reply(con, "B2", "55 units; delivery 2031-06-06 13:00+02:00. EUR 3 per unit.")
                report = compare(con, CUTOFF, save=True, model=False, now=NOW)["materials"][0]
                self.assertEqual((report["pick"], report["plan"]["uncovered"]), ("Alder", 40))
                late = next(n for n in report["negotiations"] if n["supplier"] == "Birch")
                self.assertEqual(late["asks"], [{"lever": "expedite", "units": 40, "target": "05 Jun 14:00 CEST"}])
                self.assertNotIn("no extra cost", late["body"])
                for word in ("partial", "handoff", "incremental all-in", "currency", "quote validity", "release time"):
                    self.assertIn(word, late["body"])
                row = con.execute("select qty,parent_thread_id,based_on_reply_id from chases where id=?", (late["draft_id"], )).fetchone()
                self.assertEqual(tuple(row), (40, "B2", source))
            with closing(sqlite3.connect(path)) as con:
                schema(con)
                reply(con, "B2", "50 units; ETA 2031-06-08 11:00Z.", authored="2031-06-05T10:10:00Z")
                again = compare(con, CUTOFF, save=True, model=False, now=NOW)["materials"][0]
                self.assertFalse(any(n["saved"] for n in again["negotiations"]))
                self.assertEqual(con.execute("select count(*) from negotiations where supplier_id='Birch'").fetchone()[0], 1)

    def test_no_request_after_cutoff_or_when_an_on_time_offer_covers_need(self):
        with closing(sqlite3.connect(":memory:")) as con:
            schema(con)
            thread(con)
            reply(con, "A1", "100 units, ETA 2031-06-08 14:00Z.")
            after = datetime(2031, 6, 5, 12, 1, tzinfo=timezone.utc)
            self.assertFalse(compare(con, CUTOFF, now=after, model=False)["materials"][0]["negotiations"])
            thread(con, "B2", "Birch")
            reply(con, "B2", "75 units, ETA 2031-06-05 13:00+02:00.")
            item = compare(con, CUTOFF, now=NOW, model=False)["materials"][0]
            self.assertFalse(item["plan"]["uncovered"])
            self.assertNotIn("Willow", [n["supplier"] for n in item["negotiations"]])
            for negotiation in item["negotiations"]:
                for ask in negotiation["asks"]:
                    if ask["lever"] in ("earlier", "partial"):
                        self.assertEqual(ask["target"], "05 Jun 13:00 CEST")

    def test_no_ask_on_wait_approval_cancellation_or_definitive_refusal(self):
        for text in ("We will check the carrier and reply.", "Requires a signed purchase order.",
                     "The shipment was cancelled.", "We cannot supply any units before the deadline."):
            with self.subTest(text=text), closing(sqlite3.connect(":memory:")) as con:
                schema(con)
                thread(con)
                reply(con, "A1", "Qty: 75. ETA 2031-06-10 10:00Z. " + text)
                item = compare(con, CUTOFF, now=NOW, model=False)["materials"][0]
                self.assertEqual(item["plan"]["uncovered"], 75)
                self.assertFalse(item["negotiations"])

    def test_authored_order_live_scope_and_independent_future_windows(self):
        with closing(sqlite3.connect(":memory:")) as con:
            schema(con)
            thread(con)
            source = reply(con, "A1", "75 units; ETA 2031-06-06 09:00Z.")
            reply(con, "A1", "75 units; ETA 2031-06-05 11:00Z.", authored="2031-06-04T18:00Z")
            reply(con, "A1", "75 units; ETA 2031-06-05 11:00Z.", authored="2031-06-05T10:30Z", mode="simulated")
            thread(con, "A2", deadline="2031-07-01T14:00:00+02:00", lang="pl")
            reply(con, "A2", "75 szt; dostawa 2031-07-05 18:00Z.")
            groups = compare(con, CUTOFF, now=NOW, save=True, model=False, use_thread_deadlines=True)["materials"]
            self.assertEqual(len(groups), 2)
            june, july = [g["negotiations"][0] for g in groups]
            self.assertTrue(june["saved"] and july["saved"])
            self.assertIn("01 Jul 14:00 CEST", july["body"])
            self.assertNotEqual(june["draft_id"], july["draft_id"])
            self.assertEqual(con.execute("select based_on_reply_id from chases where id=?", (june["draft_id"], )).fetchone()[0], source)
            self.assertTrue(all(g["plan"]["uncovered"] == 75 for g in groups))

    def test_legacy_demo_mail_cannot_influence_live_comparison(self):
        with closing(sqlite3.connect(":memory:")) as con:
            schema(con)
            thread(con)
            con.execute("update messages set sender='buyer (demo)', transport=NULL")
            reply(con, "A1", "80 units, ETA 2031-06-09 12:00Z.")
            con.execute("update messages set transport=NULL where side='in'")
            self.assertEqual(compare(con, CUTOFF, model=False, now=NOW)["materials"], [])
            replay = compare(con, CUTOFF, model=False, now=NOW, simulated=True, save=True)
            self.assertEqual(replay["materials"][0]["plan"]["uncovered"], 75)
            self.assertFalse(replay["materials"][0]["negotiations"][0]["saved"])

    def test_an_optimistic_model_never_promotes_an_explicitly_late_offer(self):
        from unittest.mock import Mock

        historical = Mock()
        historical.p_on_time.return_value = 0.99
        historical.discounted_eta.return_value.eta_p90 = NOW
        with closing(sqlite3.connect(":memory:")) as con:
            schema(con)
            thread(con)
            reply(con, "A1", "75 units. ETA 2031-06-06 15:00+02:00.")
            entry = compare(con, CUTOFF, model=historical, now=NOW)["materials"][0]
            self.assertIsNone(entry["pick"])
            self.assertEqual(entry["plan"]["allocation"], [])
            self.assertEqual(entry["ranking"][0]["factors"]["on_time"], 0)

    def test_quoted_text_multiple_lots_or_expiry_is_not_a_specific_late_offer(self):
        self.assertFalse(is_late_offer("Thanks.\n> ETA 2031-06-12 with 75 units.", CUTOFF))
        self.assertFalse(is_late_offer("75 units; quote valid until 2031-06-06.", CUTOFF))
        self.assertFalse(is_late_offer("20 units, ETA 2031-06-06; 55 units, ETA 2031-06-07.", CUTOFF))
        self.assertTrue(is_late_offer("20 units, ETA 2031-06-05 15:00+02:00.", CUTOFF))
        self.assertFalse(is_late_offer("20 units, ETA 2031-06-05 13:00+02:00.", CUTOFF))
        self.assertTrue(is_late_offer("20 units, arrival Friday, 6 June 2031 at 12:00 CEST.", CUTOFF))

    def test_legacy_negotiation_record_keeps_old_window_but_allows_new_round(self):
        with closing(sqlite3.connect(":memory:")) as con:
            schema(con)
            thread(con)
            reply(con, "A1", "50 units; ETA 2031-06-09.")
            thread(con, "B1", deadline="2031-07-05T14:00:00+02:00")
            reply(con, "B1", "65 units; ETA 2031-07-07.")
            con.execute("create table negotiations(supplier_id text,material text,chase_id text,time text,primary key(supplier_id,material))")
            con.execute("insert into negotiations values('Willow','HINGE-37','A1','2031-05-01')")
            con.commit()
            groups = compare(con, CUTOFF, now=NOW, save=True, model=False, use_thread_deadlines=True)["materials"]
            self.assertEqual([g["negotiations"][0]["saved"] for g in groups], [False, True])

    def test_autosend_routes_only_the_specific_recovery_enquiry(self):
        with closing(sqlite3.connect(":memory:")) as con:
            schema(con)
            thread(con)
            reply(con, "A1", "80 units, ETA 2031-06-09T12:00Z.")
            con.commit()
            sent = []

            def capture(con, key):
                sent.append(con.execute("select body from chases where id=?", (key, )).fetchone()[0])
                con.execute("update chases set status='awaiting reply' where id=?", (key, ))
            with patch("src.chaser.negotiate._reliability", return_value=None):
                run(con, now=NOW, send=capture)
                run(con, now=NOW, send=capture)
            self.assertEqual(len(sent), 1)
            self.assertIn("incremental all-in freight", sent[0])
