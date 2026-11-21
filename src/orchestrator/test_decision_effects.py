import sqlite3
import unittest

from src import chaser
from src.chaser.supplier_loop import BOOK
from src.orchestrator import decision_effects


def db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE state(key TEXT PRIMARY KEY, value TEXT)")
    con.execute("CREATE TABLE suppliers(supplier_id TEXT, name TEXT)")
    chaser.schema(con)
    return con


OPTION = {"id": "abc", "title": "Secure art book stock", "kind": "partial", "request_only": True,
          "owner": "Paul Winter", "threshold": "Buyer by total PO value", "supplier_id": BOOK[0], "material": BOOK[1]}


class DecisionEffectTest(unittest.TestCase):
    def test_request_only_approval_says_nothing_was_ordered(self):
        con = db()
        effect = decision_effects.record(con, OPTION, "approved", "Gülşah", [])
        self.assertFalse(effect["sent"])
        self.assertTrue(effect["lines"][0].startswith("Approved by Gülşah at "))
        self.assertNotIn("Still needed", " ".join(effect["lines"]))
        options = decision_effects.attach(con, [dict(OPTION, status="approved"), {"id": "x", "status": "pending"}])
        self.assertIn("effect", options[0])
        self.assertNotIn("effect", options[1])

    def test_links_the_supplier_conversation_and_delivery(self):
        con = db()
        con.execute("INSERT INTO suppliers VALUES(?, 'Karton Nowak')", (BOOK[0],))
        con.execute("INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)"
                    " VALUES('T1',?,'Karton','k@suppliers.juliansibbing.de','pl','s','awaiting reply',?,1,'b','d')", BOOK)
        con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES('T1','m','out','us','b','2026-11-21T22:00:00+00:00')")
        queue = [{"optionId": "abc", "title": "Review the Karton art-book PO", "status": "sent",
                  "delivery": {"status": "sent", "recipient": "k@suppliers.juliansibbing.de"}}]
        effect = decision_effects.describe(con, OPTION, "approved", "Isil", queue)
        self.assertTrue(effect["sent"])
        self.assertEqual(effect["threadId"], "T1")
        text = " ".join(effect["lines"])
        self.assertIn("Email sent to k@suppliers.juliansibbing.de", text)
        self.assertIn("Karton Nowak", text)
        self.assertIn("Sat 23:00", text)

    def test_past_keeps_details_and_reply_even_after_the_option_is_gone(self):
        from src.decide import authorize
        con = db()
        con.execute("INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)"
                    " VALUES('T9','SUP-1','Boise','b@suppliers.juliansibbing.de','en','s','awaiting reply','M',1,'b','d')")
        con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES('T9','r','in','b@x','We can hold 500.','2026-11-21T23:30:00+00:00')")
        con.commit()
        option = dict(OPTION, id="opt9", title="Check Boise stock")
        authorize(con, option, "approve")
        decision_effects.record(con, option, "approved", "Gülşah", [], delivery={"status": "sent", "recipient": "b@x",
                                "subject": "Hold", "body": "Hello", "chase_id": "T9"})
        rows = decision_effects.past(con)
        self.assertEqual([r["id"] for r in rows], ["opt9"])
        self.assertEqual(rows[0]["effect"]["email"]["subject"], "Hold")
        self.assertEqual(rows[0]["effect"]["reply"]["body"], "We can hold 500.")
        self.assertEqual(decision_effects.past(con, days=0), [])


if __name__ == "__main__":
    unittest.main()
