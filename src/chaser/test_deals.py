import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from . import schema
from .deals import check_draft, decide, is_decision_draft, list_deals, signer, sync

DEADLINE = "2026-11-22T20:00:00+01:00"
NOW = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)


def db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    schema(con)
    for cid, sid, sup, lang, body in (
            ("B1", "SUP-0011", "Boise Semi", "en", "Quantity: 6,800 pcs, ETA 2026-11-22 06:00, USD 10.40 per unit, AWB 020-12345678"),
            ("H1", "SUP-0029", "Guangzhou PackRight", "zh", "数量: 6800, 到货 2026-11-22 15:00, USD 9.90 per unit")):
        con.execute("INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?)", (cid, sid, sup, f"{cid}@suppliers.juliansibbing.de", lang,
                    f"[SOONY-{cid}] s", "reply to verify", "CMP-GAM-001", 6800, "q", DEADLINE))
        con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES(?,?,?,?,?,?)",
                    (cid, cid + "o", "out", "us", "q", "2026-11-21T08:00:00+00:00"))
        con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES(?,?,?,?,?,?)",
                    (cid, cid + "i", "in", sup, body, "2026-11-21T09:00:00+00:00"))
    con.commit()
    return con


class DealsTest(unittest.TestCase):
    def setUp(self):
        self.clock = patch("src.chaser.deals._now", return_value=NOW.isoformat())
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def boise(self, con):
        return next(d for d in list_deals(con)["deals"] if d["supplier"] == "Boise Semi")

    def revise(self, con, body, time="2026-11-21T11:00:00+00:00", mid="revision"):
        con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES(?,?,?,?,?,?)",
                    ("B1", mid, "in", "Boise", body, time))

    def test_buyer_reviews_separate_deadlines_for_the_same_supplier_and_part(self):
        con = db()
        sync(con, DEADLINE, now=NOW, model=False)
        original = self.boise(con)
        con.execute("""INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)
                    SELECT 'B2',supplier_id,supplier,address,language,'[SOONY-B2] Second release',status,material,qty,body,
                           '2026-12-15T20:00:00+01:00' FROM chases WHERE id='B1'""")
        con.execute("""INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES('B2','second-round','in',
                    'supplier','6,800 units; ETA 2026-12-14 13:00+01:00. EUR 8 per unit. AWB 020-12345678',
                    '2026-11-21T11:00:00Z')""")
        sync(con, DEADLINE, now=NOW, model=False)
        both = [d for d in list_deals(con)["deals"] if d["supplier"] == original["supplier"]]
        self.assertEqual(len(both), 2)
        self.assertEqual({d["offer_state"] for d in both}, {"quoted"})
        for item in both:
            self.assertIsNotNone(decide(con, item["id"], "approve", "Buyer", revision=item["revision"])["email_id"])
        self.assertEqual(next(d for d in both if d["thread_id"] == "B1")["revision"], original["revision"])

    def test_signer_follows_pp07(self):
        self.assertEqual(signer(49_999), "Buyer")
        self.assertEqual(signer(62_000), "Category Lead")
        self.assertEqual(signer(6_000_000), "CPO and CFO jointly")

    def test_table_best_and_decisions(self):
        con = db()
        self.assertEqual(sync(con, DEADLINE, now=NOW, model=False), 2)
        data = list_deals(con)
        self.assertEqual(len(data["deals"]), 2)
        self.assertEqual(len(data["best"]), 1)
        boise = next(d for d in data["deals"] if d["supplier"] == "Boise Semi")
        self.assertEqual((boise["quantity"], boise["unit_price"], boise["currency"]), (6800, 10.4, "USD"))
        self.assertEqual(boise["proof"], "shipping document")
        self.assertEqual(boise["signer"], "Category Lead")  # 6,800 x 10.40 USD ~ EUR 65k
        approved = decide(con, boise["id"], "approve", "Gülşah", revision=boise["revision"])
        email = con.execute("SELECT status, body FROM chases WHERE id=?", (approved["email_id"],)).fetchone()
        self.assertEqual(email[0], "draft")
        self.assertIn("Category Lead", email[1])
        other = next(d for d in data["deals"] if d["supplier"] != "Boise Semi")
        declined = decide(con, other["id"], "decline", "Gülşah", revision=other["revision"])
        self.assertEqual(declined["status"], "declined")
        # supplier changes the offer after approval -> back to "changed"
        con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES(?,?,?,?,?,?)",
                    ("B1", "B1i2", "in", "Boise", "Quantity: 6,800 pcs, ETA 2026-11-22 06:00, USD 11.20 per unit", "2026-11-21T10:00:00+00:00"))
        sync(con, DEADLINE, now=NOW, model=False)
        self.assertEqual(next(d for d in list_deals(con)["deals"] if d["supplier"] == "Boise Semi")["status"], "changed")

    def test_repeated_review_and_refresh_queue_one_response(self):
        con = db()
        sync(con, DEADLINE, now=NOW, model=False)
        item = self.boise(con)
        first = decide(con, item["id"], "approve", "Buyer", revision=item["revision"])
        self.assertTrue(is_decision_draft(con, first["email_id"]))
        self.assertTrue(check_draft(con, first["email_id"]))
        sync(con, DEADLINE, now=NOW, model=False)
        retry = decide(con, item["id"], "approve", "Another buyer", revision=item["revision"])
        self.assertEqual((first["email_id"], first["decided_by"]), (retry["email_id"], retry["decided_by"]))
        with self.assertRaisesRegex(ValueError, "already recorded"):
            decide(con, item["id"], "decline", revision=item["revision"])
        self.assertEqual(con.execute("SELECT count(*) FROM chases WHERE status='draft'").fetchone()[0],1)
        self.assertEqual(len(self.boise(con)["history"]), 1)

    def test_change_blocks_stale_request_before_sync_and_retires_draft(self):
        con = db()
        sync(con, DEADLINE, now=NOW, model=False)
        original = self.boise(con)
        approved = decide(con, original["id"], "approve", revision=original["revision"])
        self.revise(con, "Quantity: 6,800 pcs, ETA 2026-11-22 06:00, USD 10.40 per unit, EXW, NET 10.")
        with self.assertRaisesRegex(ValueError,"changed"):
            check_draft(con, approved["email_id"])
        sync(con, DEADLINE, now=NOW, model=False)
        revised = self.boise(con)
        with self.assertRaisesRegex(ValueError,"changed"):
            decide(con, revised["id"], "approve", revision=original["revision"])
        self.assertEqual((revised["status"],revised["incoterm"],revised["payment_terms"]),("changed","EXW","NET 10"))
        self.assertNotEqual(original["revision"],revised["revision"])
        self.assertEqual(con.execute("SELECT status FROM chases WHERE id=?", (approved["email_id"],)).fetchone()[0],"superseded")
        self.assertEqual(revised["history"][0]["terms"]["total_eur"],original["total_eur"])

    def test_non_quotes_cannot_be_approved_or_declined(self):
        cases = [
            ("Quantity: 6,800 pcs, ETA 2026-11-22 06:00. Freight EUR 1,200 total.", "incomplete"),
            ("Quantity: 6,800 pcs, EUR 10 per unit. Quote expires 2026-11-22 06:00.", "incomplete"),
            ("Quantity: 6,800 pcs, ETA 2026-11-24 06:00, USD 9.00 per unit.", "late"),
            ("This quote is withdrawn. Quantity: 6,800 pcs, ETA 2026-11-22 06:00, EUR 9.00 per unit.", "superseded"),
            ("We can supply zero units before launch. Quantity: 6,800 pcs, EUR 2 per unit.", "unavailable"),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                con = db()
                self.revise(con, body)
                sync(con, DEADLINE, now=NOW, model=False)
                d = self.boise(con)
                self.assertEqual(d["offer_state"], expected)
                self.assertFalse(d["eligible"])
                for action in ("approve","decline"):
                    with self.assertRaises(ValueError):
                        decide(con, d["id"], action, revision=d["revision"])

    def test_paid_freight_is_a_single_service_charge(self):
        con = db()
        self.revise(con, "Quantity: 6,800 pcs. Hamburg handoff: 2026-11-22T13:00+01:00. "
                        "Incremental all-in freight charge: EUR 1,200. Valid until 2026-11-21T21:15+01:00. "
                        "Air service. Carrier: Blue Air")
        sync(con, DEADLINE, now=NOW,model=False)
        d = self.boise(con)
        self.assertEqual((d["offer_kind"],d["offer_state"],d["total_eur"],d["unit_price"]), ("freight","quoted",1200,None))
        approved = decide(con, d["id"], "approve",revision=d["revision"])
        email = con.execute("SELECT body FROM chases WHERE id=?", (approved["email_id"],)).fetchone()[0]
        self.assertIn("without charge", email)
        self.assertIn("separate written authorization", email)

    def test_old_mail_import_and_equivalent_resend_preserve_revision(self):
        con = db()
        sync(con, DEADLINE, now=NOW,model=False)
        first = self.boise(con)
        self.revise(con, "Quantity: 300 pcs, EUR 5 per unit.", "2026-11-20T05:00:00+00:00")
        self.revise(con, first["excerpt"], mid="resend")
        sync(con, DEADLINE, now=NOW,model=False)
        self.assertEqual(self.boise(con)["revision"], first["revision"])

    def test_simultaneous_reviewers_record_one_decision(self):
        con = db()
        sync(con, DEADLINE, now=NOW, model=False)
        item = self.boise(con)
        barrier = Barrier(2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deals.db"
            with sqlite3.connect(path) as on_disk:
                con.backup(on_disk)

            def approve(actor):
                with sqlite3.connect(path, timeout=5) as session:
                    barrier.wait(timeout=5)
                    return decide(session, item["id"], "approve", actor, revision=item["revision"])

            with ThreadPoolExecutor(max_workers=2) as pool:
                first, second = list(pool.map(approve, ["buyer A", "buyer B"]))
            self.assertEqual(first["email_id"], second["email_id"])
            self.assertEqual(first["decided_by"], second["decided_by"])
            with sqlite3.connect(path) as saved:
                self.assertEqual(saved.execute("SELECT count(*) FROM deal_decision_history").fetchone()[0], 1)

    def test_legacy_approved_draft_requires_review_and_remains_in_audit(self):
        con = db()
        sync(con, DEADLINE, now=NOW, model=False)
        item = self.boise(con)
        result = decide(con, item["id"], "approve", "Buyer A", revision=item["revision"])
        con.execute("DELETE FROM deal_decision_history")
        con.execute("UPDATE deals SET revision=NULL WHERE id=?", (item["id"],))
        with self.assertRaises(ValueError):
            check_draft(con, result["email_id"])
        sync(con, DEADLINE, now=NOW, model=False)
        saved = self.boise(con)
        self.assertEqual((saved["status"], saved["history"][0]["by"]), ("changed", "Buyer A"))
        self.assertIsNone(saved["email_id"])
        self.assertEqual(con.execute("SELECT status FROM chases WHERE id=?", (result["email_id"],)).fetchone()[0], "superseded")


if __name__ == "__main__":
    unittest.main()
