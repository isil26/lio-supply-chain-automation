import json
import os
import sqlite3
import unittest
from unittest import mock

from . import actions, schema
from .supplier_loop import CARD

SUPPLIER = {"id": "chase-boise", "kind": "supplier", "title": "Ask Boise for the missing cases", "supplierId": "SUP-9",
            "material": "CMP-X", "qty": 500, "deadline": "22 Nov 18:00", "copiesStd": 10,
            "evidence": ["Boise reply 21 Nov"],
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
                  "dueAt": "2026-11-22T09:00:00+01:00", "price": 1200.0,
                  "evidence": [{"text": "AWB 020-48113256", "source": "case-data"}]}
        row = actions.on_approve(db(), review, "Katrin Jansen", demo=True)
        self.assertEqual((row["kind"], row["status"], row["person"]), ("internal", "prepared", "Katrin Jansen"))
        for text in ("Ask DC-HAM for a window.", "2026-11-22T09:00", "EUR 1,200"):
            self.assertIn(text, row["body"])

    # ---- T94 approval modes ----
    def test_auto_needs_written_delegation(self):
        con = db()
        unconfirmed = {"mode": "AUTO", "approver": "Dr. Vogt", "delegation": {"id": "D1", "from": "Dr. Vogt", "confirmed": False}}
        row = actions.auto_dispatch(con, SUPPLIER, demo=True, decision=unconfirmed)
        self.assertEqual((row["mode"], row["status"]), ("ONE-CLICK", "awaiting approval"))
        self.assertEqual(con.execute("SELECT count(*) FROM messages").fetchone()[0], 0)
        row = actions.on_approve(con, SUPPLIER, "Felix", demo=True, decision=unconfirmed)   # a person clicks
        self.assertEqual((row["status"], row["approved_by"]), ("sent", "Felix"))

    def test_auto_with_confirmed_delegation_sends_and_logs_it(self):
        confirmed = {"mode": "auto", "approver": "Felix", "delegation": {"id": "D7", "from": "Felix", "confirmed": True}}
        row = actions.auto_dispatch(db(), SUPPLIER, demo=True, decision=confirmed)
        self.assertEqual((row["mode"], row["status"]), ("AUTO", "sent"))
        self.assertEqual(row["approved_by"], "delegation of Felix, record D7")

    def test_binding_email_is_never_auto(self):
        binding = dict(SUPPLIER, id="po", draft=dict(SUPPLIER["draft"], body="We accept your offer, purchase order follows."))
        confirmed = {"mode": "AUTO", "delegation": {"id": "D7", "from": "Felix", "confirmed": True}}
        row = actions.auto_dispatch(db(), binding, demo=True, decision=confirmed)
        self.assertEqual((row["mode"], row["status"]), ("ONE-CLICK", "awaiting approval"))

    def test_never_and_escalate(self):
        con = db()
        row = actions.on_approve(con, INTERNAL, "Isil", demo=True, decision={"mode": "NEVER", "reason": "quality release"})
        self.assertEqual(row["status"], "blocked")
        row = actions.on_approve(con, dict(SUPPLIER, id="esc"), "Isil", demo=True,
                                 decision={"mode": "ESCALATE", "escalateTo": "Jonas Lindqvist (CPO)", "sla": "same hour"})
        self.assertEqual((row["status"], row["recipient"], row["sla"]), ("escalated", "Jonas Lindqvist (CPO)", "same hour"))
        self.assertEqual(con.execute("SELECT count(*) FROM messages").fetchone()[0], 0)

    def test_t93_engine_is_consulted(self):
        con = db()
        row = actions.on_approve(con, INTERNAL, None, demo=True)          # automatic run, no click
        self.assertEqual((row["mode"], row["status"], row["approver"]), ("ONE-CLICK", "awaiting approval", "Katrin Jansen"))
        row = actions.on_approve(con, dict(INTERNAL, evidence=[]), "Isil", demo=True)  # still awaiting -> re-evaluated
        self.assertEqual((row["mode"], row["status"]), ("NEVER", "blocked"))   # engine: no evidence, never


if __name__ == "__main__":
    unittest.main()
