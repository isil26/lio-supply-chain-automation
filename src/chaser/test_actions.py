import json
import os
import sqlite3
import unittest
from unittest import mock

from . import actions, schema
from .supplier_loop import CARD

SUPPLIER = {"id": "chase-boise", "kind": "supplier", "title": "Ask Boise for the missing cases", "supplierId": "SUP-9",
            "material": "CMP-X", "qty": 500, "deadline": "22 Nov 18:00", "copiesStd": 10,
            "draft": {"to": "boise@suppliers.juliansibbing.de", "subject": "Cases", "body": "Hello,\n\nCan you confirm 500 cases? Request for information only."}}
INTERNAL = {"id": "dock", "kind": "internal", "title": "Book the Hamburg dock slot", "person": "Katrin Jansen",
            "deadline": "Sun 10:00", "copiesStd": 21216, "copiesCe": 3133, "costEur": 5000, "approver": "Katrin Jansen",
            "evidence": [{"text": "Decision A", "source": "docs/VOGT_BREAKEVEN.md"}]}


def db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    schema(con)
    return con


@mock.patch.dict(os.environ, {"CHASER_SENDER": "team@example.invalid"})
class ActionSendTest(unittest.TestCase):
    def test_internal_action_is_prepared_with_euro_case(self):
        con = db()
        row = actions.on_approve(con, INTERNAL, "Isil", demo=True)
        self.assertEqual(row["status"], "prepared")
        self.assertIn("EUR 1,054,872", row["body"])      # 21,216 x 32 + 3,133 x 120
        self.assertIn("clears its cost", row["body"])
        self.assertIn("docs/VOGT_BREAKEVEN.md", row["body"])
        self.assertEqual(actions.mark(con, "dock", "done")["status"], "done")

    def test_supplier_action_sends_once_and_tracks_reply(self):
        con = db()
        row = actions.on_approve(con, SUPPLIER, "Isil", demo=True)
        self.assertEqual(row["status"], "sent")
        self.assertTrue(row["subject"].startswith("[SOONY-"))
        again = actions.on_approve(con, SUPPLIER, "Isil", demo=True)
        self.assertEqual(again["chase_id"], row["chase_id"])
        self.assertEqual(con.execute("SELECT count(*) FROM messages WHERE side='out'").fetchone()[0], 1)
        con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time,parsed) VALUES(?,?,?,?,?,?,?)",
                    (row["chase_id"], "r1", "in", "boise", "Quantity: 500, ship 2026-11-22", "2026-11-21T19:00:00+00:00",
                     json.dumps({"quantity": {"value": "500"}, "stated_time": {"value": "2026-11-22"}})))
        self.assertEqual(actions.refresh(con), ["chase-boise"])
        self.assertEqual(actions.get(con, "chase-boise")["status"], "done")

    def test_vague_reply_needs_a_look(self):
        con = db()
        row = actions.on_approve(con, SUPPLIER, "Isil", demo=True)
        con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time,parsed) VALUES(?,?,?,?,?,?,?)",
                    (row["chase_id"], "r1", "in", "boise", "We will check.", "2026-11-21T19:00:00+00:00", "{}"))
        self.assertEqual(actions.status(con)[0]["status"], "replied")

    def test_guardrails_block_supplier_email(self):
        bad = dict(SUPPLIER, id="bad", draft=dict(SUPPLIER["draft"], body="Our cost per missing copy is high."))
        row = actions.on_approve(db(), bad, "Isil", demo=True)
        self.assertEqual(row["status"], "blocked")

    def test_supplier_loop_case_is_not_mailed_twice(self):
        con = db()
        row = actions.on_approve(con, dict(SUPPLIER, id="card", supplierId=CARD[0], material=CARD[1]), "Isil", demo=True)
        self.assertEqual(row["status"], "handled by supplier loop")
        self.assertEqual(con.execute("SELECT count(*) FROM messages").fetchone()[0], 0)

    def test_live_send_problem_leaves_it_queued(self):
        con = db()
        with mock.patch.dict(os.environ, {"CHASER_NO_TEAM_MAIL": "1", "CHASER_SMTP_HOST": ""}):
            row = actions.on_approve(con, SUPPLIER, "Isil", demo=False)
        self.assertEqual(row["status"], "queued")
        self.assertEqual(con.execute("SELECT status FROM chases").fetchone()[0], "draft")

    def test_t81_recovery_review_shape(self):
        review = {"id": "opt-dock", "status": "awaiting_approval", "title": "Arrange a provisional Hamburg dock slot",
                  "owner": "Katrin Jansen", "approver": "Katrin Jansen, DC-HAM site lead", "detail": "Ask DC-HAM for a window.",
                  "dueAt": "2026-11-22T09:00:00+01:00", "price": 1200.0}
        row = actions.on_approve(db(), review, "Katrin Jansen", demo=True)
        self.assertEqual((row["kind"], row["status"], row["person"]), ("internal", "prepared", "Katrin Jansen"))
        for text in ("Ask DC-HAM for a window.", "2026-11-22T09:00", "EUR 1,200"):
            self.assertIn(text, row["body"])


if __name__ == "__main__":
    unittest.main()
