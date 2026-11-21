import sqlite3
import unittest
from datetime import datetime, timezone

from . import schema
from .deals import decide, list_deals, signer, sync

DEADLINE = "2026-11-22T20:00:00+01:00"
NOW = datetime(2026, 11, 21, 12, tzinfo=timezone.utc)


def db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    schema(con)
    for cid, sid, sup, lang, body in (
            ("B1", "SUP-0011", "Boise Semi", "en", "Quantity: 6,800 pcs, ETA 2026-11-22 06:00, USD 10.40 per unit, AWB 020-12345678"),
            ("H1", "SUP-0029", "Guangzhou PackRight", "zh", "数量: 6800, 2026-11-22 15:00, USD 9.90 per unit")):
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
        approved = decide(con, boise["id"], "approve", "Gülşah")
        email = con.execute("SELECT status, body FROM chases WHERE id=?", (approved["email_id"],)).fetchone()
        self.assertEqual(email[0], "draft")
        self.assertIn("Category Lead", email[1])
        other = next(d for d in data["deals"] if d["supplier"] != "Boise Semi")
        declined = decide(con, other["id"], "decline", "Gülşah")
        self.assertEqual(declined["status"], "declined")
        # supplier changes the offer after approval -> back to "changed"
        con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES(?,?,?,?,?,?)",
                    ("B1", "B1i2", "in", "Boise", "Quantity: 6,800 pcs, ETA 2026-11-22 06:00, USD 11.20 per unit", "2026-11-21T10:00:00+00:00"))
        sync(con, DEADLINE, now=NOW, model=False)
        self.assertEqual(next(d for d in list_deals(con)["deals"] if d["supplier"] == "Boise Semi")["status"], "changed")


if __name__ == "__main__":
    unittest.main()
