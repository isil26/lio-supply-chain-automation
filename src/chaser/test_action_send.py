import os
import sqlite3
import unittest
from datetime import datetime, timezone
from email.message import EmailMessage
from unittest import mock

from . import action_send as A
from . import receive, schema

DEADLINE = "2026-11-22T20:00:00+01:00"
NOW = datetime(2026, 11, 21, 18, tzinfo=timezone.utc)


def db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    schema(con)
    A.schema(con)
    con.execute("CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT)")
    return con


def supplier_action(**kw):
    a = {"id": "act-1", "kind": "info_request", "title": "Chase the 20,000-card balance", "owner_role": "Planner",
         "person": "Mia", "deadline": DEADLINE, "eur_at_stake": 2400, "evidence": ["ERP PO line 3"],
         "approver": "Mia Planner", "draft": "Hello, can you confirm the open quantity and ETA? Information request only.",
         "target": "supplier", "supplier_id": "S1", "material": "CMP-GAM-001", "qty": 20000,
         "supplier": {"name": "Sup One", "email": "one@suppliers.juliansibbing.de", "language": "en"}}
    a.update(kw)
    return a


def fake_send(sent):
    def send(con, chase_id):
        sent.append(chase_id)
        con.execute("UPDATE chases SET status='awaiting reply' WHERE id=?", (chase_id,))
        con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time,transport) VALUES(?,?,?,?,?,?,?)",
                    (chase_id, f"out-{chase_id}", "out", "us", "x", "2026-11-21T17:00:00+00:00",
                     '{"mode":"smtp","status":"smtp_accepted"}'))
    return send


class ActionSendTest(unittest.TestCase):
    def test_supplier_action_becomes_a_normal_chase_and_sends_once_approved(self):
        con = db()
        rec = A.prepare(con, supplier_action())
        self.assertEqual(rec["status"], "prepared")
        chase = con.execute("SELECT * FROM chases WHERE id=?", (rec["chase_id"],)).fetchone()
        self.assertEqual(chase["status"], "action prepared")  # not a draft: autosend cannot pick it up
        self.assertTrue(chase["subject"].startswith(f"[SOONY-{rec['chase_id']}]"))
        sent = []
        with self.assertRaises(PermissionError):
            A.send_supplier(con, "act-1", send=fake_send(sent), now=NOW)
        A.approve(con, "act-1", "Mia Planner")
        self.assertEqual(A.send_supplier(con, "act-1", send=fake_send(sent), now=NOW)["result"], "sent")
        self.assertEqual(sent, [rec["chase_id"]])
        self.assertEqual(A.get(con, "act-1")["status"], "sent")

    def test_template_in_supplier_language_when_no_draft(self):
        con = db()
        a = supplier_action(draft=None, supplier={"name": "Hwaseong", "email": "h@suppliers.juliansibbing.de", "language": "ko"})
        body = A.prepare(con, a)["message"]["body"]
        self.assertIn("20,000", body)
        self.assertIn("확인", body)

    def test_binding_needs_recorded_approver(self):
        con = db()
        A.prepare(con, supplier_action(id="po-1", kind="purchase_commitment", approver="Paul Winter"))
        with self.assertRaises(PermissionError) as ctx:
            A.send_supplier(con, "po-1", send=fake_send([]), now=NOW)
        self.assertIn("PP-07", str(ctx.exception))
        with self.assertRaises(PermissionError):
            A.approve(con, "po-1", "Somebody Else")
        with self.assertRaises(PermissionError):
            A.approve(con, "po-1", "  ")
        A.prepare(con, supplier_action(id="po-2", binding=True, approver="", supplier_id="S2",
                                       supplier={"name": "S2", "email": "two@suppliers.juliansibbing.de"}))
        A.approve(con, "po-2", "Anyone")
        with self.assertRaises(PermissionError):
            A.send_supplier(con, "po-2", send=fake_send([]), now=NOW)

    def test_allowlist_guardrails_and_cooldown(self):
        con = db()
        A.prepare(con, supplier_action(id="a-out", supplier={"name": "X", "email": "boss@gmail.com"}))
        A.approve(con, "a-out", "Mia Planner")
        with self.assertRaises(PermissionError):
            A.send_supplier(con, "a-out", send=fake_send([]), now=NOW)
        A.prepare(con, supplier_action(id="a-bad", supplier_id="S3", draft="We guarantee payment.",
                                       supplier={"name": "Y", "email": "y@suppliers.juliansibbing.de"}))
        A.approve(con, "a-bad", "Mia Planner")
        sent = []
        self.assertEqual(A.send_supplier(con, "a-bad", send=fake_send(sent), now=NOW)["result"], "blocked")
        self.assertEqual(sent, [])
        # a recent unanswered mail to the same address and material cools the action down
        A.prepare(con, supplier_action(id="a-1"))
        A.approve(con, "a-1", "Mia Planner")
        A.send_supplier(con, "a-1", send=fake_send(sent), now=NOW)
        A.prepare(con, supplier_action(id="a-2", draft="Another request, different text."))
        A.approve(con, "a-2", "Mia Planner")
        con.execute("UPDATE messages SET time='2026-11-21T17:50:00+00:00'")
        self.assertEqual(A.send_supplier(con, "a-2", send=fake_send(sent), now=NOW)["result"], "cooldown")
        self.assertEqual(len(sent), 1)

    def test_internal_action_is_prepared_never_sent(self):
        con = db()
        a = {"id": "dock-1", "kind": "dock_slot", "title": "Book a Hamburg dock slot for the air lot",
             "owner_role": "Site lead", "person": "Katrin Jansen", "deadline": DEADLINE, "eur_at_stake": 3360000,
             "evidence": ["AWB 020-48113256"], "approver": "Katrin Jansen", "draft": "Please book a slot.",
             "target": "internal"}
        rec = A.prepare(con, a)
        self.assertIn("EUR 3,360,000", rec["message"]["body"])
        self.assertIn("Katrin Jansen", rec["message"]["body"])
        self.assertFalse(rec["message"]["sent_by_system"])
        self.assertIsNone(rec["chase_id"])
        with self.assertRaises(PermissionError):
            A.send_supplier(con, "dock-1", send=fake_send([]), now=NOW)
        with mock.patch("src.chaser.smtplib.SMTP") as smtp:
            A.mark_handed_over(con, "dock-1", "Gülşah")
            smtp.assert_not_called()
        self.assertEqual(A.get(con, "dock-1")["status"], "sent")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM chases").fetchone()[0], 0)

    def test_reply_links_back_and_done(self):
        con = db()
        rec = A.prepare(con, supplier_action())
        A.approve(con, "act-1", "Mia Planner")
        A.send_supplier(con, "act-1", send=fake_send([]), now=NOW)
        self.assertEqual(A.link_replies(con), [])
        con.execute("UPDATE messages SET transport='{\"mode\":\"smtp\"}'")  # real out message id out-<chase>
        msg = EmailMessage()
        msg["From"], msg["To"] = "one@suppliers.juliansibbing.de", "us@example.invalid"
        msg["Subject"] = f"Re: [SOONY-{rec['chase_id']}] Launch stock"
        msg["In-Reply-To"], msg["Message-ID"] = f"out-{rec['chase_id']}", "<r1@x>"
        msg.set_content("We can ship 5000 pcs, ETA 2026-11-22.")
        self.assertTrue(receive(con, msg))
        self.assertEqual(A.link_replies(con), ["act-1"])
        self.assertEqual(A.get(con, "act-1")["status"], "replied")
        self.assertEqual(A.link_replies(con), [])
        done = A.mark_done(con, "act-1", by="Mia", note="covered")
        self.assertEqual((done["status"], done["done_by"]), ("done", "Mia"))

    def test_simulated_reply_does_not_count_and_real_default_send_uses_dry_run(self):
        con = db()
        rec = A.prepare(con, supplier_action())
        A.approve(con, "act-1", "Mia Planner")
        with mock.patch.dict(os.environ, {"CHASER_SENDER": "qa@example.invalid"}):
            self.assertEqual(A.send_supplier(con, "act-1", demo=True, now=NOW)["result"], "sent")
        self.assertEqual(con.execute("SELECT status FROM chases WHERE id=?", (rec["chase_id"],)).fetchone()[0], "awaiting reply")
        con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time,transport) VALUES(?,?,?,?,?,?,?)",
                    (rec["chase_id"], "sim", "in", "s", "ok", NOW.isoformat(), '{"mode":"simulated"}'))
        self.assertEqual(A.link_replies(con), [])

    def test_prepare_is_idempotent_and_validates(self):
        con = db()
        A.prepare(con, supplier_action())
        A.prepare(con, supplier_action(title="changed"))
        self.assertEqual(con.execute("SELECT COUNT(*) FROM action_sends").fetchone()[0], 1)
        with self.assertRaises(ValueError):
            A.prepare(con, {"id": "x", "target": "other"})


if __name__ == "__main__":
    unittest.main()
