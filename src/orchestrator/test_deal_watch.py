import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.chaser import schema
from src.ingest.store import connect, get_state, save_state
from src.orchestrator import deal_watch


class ServerDealWatchTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "worker.db"
        self.con = connect(self.path)
        self.addCleanup(lambda: self.con.close())
        schema(self.con)
        self.clock = datetime(2031, 2, 8, 12, tzinfo=timezone.utc)
        self.end = self.clock + timedelta(days=2)
        self.part = {"shortfall": 70, "suppliers": [{"supplier_id": "S4", "supplier": {"status": "active"}}]}
        self.truth = {"name": "Pump assembly", "site": "Dock B", "deadline": self.end.isoformat(),
                      "parts": {"SEAL": self.part}}
        with self.con:
            save_state(self.con, "truth", self.truth)

    def test_persistent_timer_new_mail_and_closed_scenario(self):
        self.assertTrue(deal_watch.due(None, self.truth, 3, self.clock))
        deal_watch.publish(self.con, self.truth, 3, self.clock)
        self.con.close()
        self.con = connect(self.path)
        review = get_state(self.con, deal_watch.KEY)
        self.assertEqual(review["shortages"], {"SEAL": 70})
        self.assertFalse(deal_watch.due(review, self.truth, 3, self.clock + timedelta(minutes=29)))
        self.assertTrue(deal_watch.due(review, self.truth, 3, self.clock + timedelta(minutes=30)))
        self.assertTrue(deal_watch.due(review, self.truth, 4, self.clock))
        self.assertTrue(deal_watch.due(review, self.truth, 3, self.end))
        deal_watch.publish(self.con, self.truth, 4, self.end)
        closed = get_state(self.con, deal_watch.KEY)
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["shortages"], {})
        self.assertIsNone(closed["nextReviewAt"])
        self.assertFalse(deal_watch.due(closed, self.truth, 5, self.end))
        self.assertTrue(deal_watch.due(closed, dict(self.truth, name="Replacement pump", deadline="2032-01-01T10:00:00Z"),
                                        5, self.end))

    def test_verified_quote_reported_once_and_removed_when_gap_closes(self):
        with self.con:
            self.con.execute("""INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)
                VALUES('AB12','S4','Seal Works','sales@example.test','en','[SOONY-AB12] Seals','reply to verify',
                       'SEAL',70,'Please quote.',?)""", (self.truth["deadline"],))
            self.con.execute("""INSERT INTO messages(chase_id,external_id,side,sender,body,time,transport) VALUES
                ('AB12','<ask>','out','team@example.test','Please quote.','2031-02-07T11:00:00Z',
                 '{"mode":"smtp","status":"smtp_accepted"}'),
                ('AB12','<quote>','in','sales@example.test',
                 'Quantity: 70 pcs. ETA 2031-02-09 06:00Z. EUR 4 per unit. AWB 020-12345678.',
                 '2031-02-08T08:00:00Z','{"mode":"inbox","status":"received","inReplyTo":"<ask>"}')""")
        for minutes in (0, 30):
            deal_watch.publish(self.con, self.truth, 2, self.clock + timedelta(minutes=minutes))
        review = get_state(self.con, deal_watch.KEY)
        quote, = review["offers"].values()
        self.assertEqual((quote["material"], quote["supplier"], quote["unit_price"], quote["source_message"]),
                         ("SEAL", "Seal Works", 4, "<quote>"))
        self.assertEqual(self.con.execute("SELECT count(*) FROM activity WHERE agent='Supplier Deal Watch'").fetchone()[0], 1)
        self.part["shortfall"] = 0
        deal_watch.publish(self.con, self.truth, 2, self.clock + timedelta(hours=1))
        self.assertEqual(get_state(self.con, deal_watch.KEY)["offers"], {})
