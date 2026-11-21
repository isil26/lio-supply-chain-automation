import os
import sqlite3
import unittest
from datetime import datetime, timezone
from unittest import mock

from . import schema
from . import autosend

DEADLINE = "2026-11-22T20:00:00+01:00"
NOW = datetime(2026, 11, 21, 18, tzinfo=timezone.utc)


def db(rows):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    schema(con)
    for cid, address, body in rows:
        con.execute("INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?)", (cid, "S", "Sup " + cid, address, "en", f"[SOONY-{cid}] s",
                                                       "draft", "CMP-GAM-001", 100, body, DEADLINE))
    con.commit()
    return con


class AutoSendTest(unittest.TestCase):
    def test_no_cap_but_no_duplicate_text(self):
        con = db([(c, f"{c.lower()}@suppliers.juliansibbing.de", "Please confirm quantity.") for c in "ABCDEFGH"])
        con.execute("INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)"
                    " VALUES('Z','S','Sup Z','z@suppliers.juliansibbing.de','en','s','awaiting reply','M',1,'Same text',?)", (DEADLINE,))
        con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES('Z','z','out','us','Same text','2026-11-20T00:00:00+00:00')")
        con.execute("INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)"
                    " VALUES('Y','S','Sup Y','z@suppliers.juliansibbing.de','en','s','draft','M',1,'Same text',?)", (DEADLINE,))
        sent = []
        results = autosend.run(con, send=lambda con, cid: sent.append(cid), now=NOW, prepare=False)
        self.assertEqual(len(sent), 8)
        self.assertIn({"id": "Y", "supplier": "Sup Y", "result": "duplicate"}, results)

    def test_only_live_mode(self):
        with mock.patch.dict(os.environ, {"CHASER_REAL_SMTP": "1"}, clear=True):
            self.assertTrue(autosend.enabled())
            self.assertFalse(autosend.enabled(demo=True))
        with mock.patch.dict(os.environ, {"CHASER_REAL_SMTP": "1", "CHASER_AUTO_SEND": "0"}, clear=True):
            self.assertFalse(autosend.enabled())
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(autosend.enabled())

    def test_sends_drafts_skips_guardrail_and_cooldown(self):
        con = db([("A", "a@suppliers.juliansibbing.de", "Please confirm quantity."),
                  ("B", "b@suppliers.juliansibbing.de", "We guarantee payment."),
                  ("C", "a@suppliers.juliansibbing.de", "Second mail to the same address.")])
        sent = []

        def fake_send(con, chase_id):
            sent.append(chase_id)
            con.execute("UPDATE chases SET status='awaiting reply' WHERE id=?", (chase_id,))
            con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES(?,?,?,?,?,?)",
                        (chase_id, chase_id, "out", "us", "x", NOW.isoformat()))

        results = autosend.run(con, send=fake_send, now=NOW, prepare=False)
        self.assertEqual(sent, ["A"])
        self.assertEqual({r["id"]: r["result"] for r in results}, {"A": "sent", "B": "blocked"})

    def test_reply_lifts_the_wait(self):
        con = db([("A", "a@suppliers.juliansibbing.de", "Follow-up answer.")])
        con.execute("INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)"
                    " VALUES('P','S','Sup P','a@suppliers.juliansibbing.de','en','s','awaiting reply','CMP-GAM-001',1,'first',?)", (DEADLINE,))
        con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES('P','p1','out','us','first','2026-11-21T17:50:00+00:00')")
        sent = []
        autosend.run(con, send=lambda con, cid: sent.append(cid), now=NOW, prepare=False)
        self.assertEqual(sent, [])  # no answer yet, 10 minutes ago: wait
        con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES('P','p2','in','a','reply','2026-11-21T17:55:00+00:00')")
        autosend.run(con, send=lambda con, cid: sent.append(cid), now=NOW, prepare=False)
        self.assertEqual(sent, ["A"])  # they replied: answer right away

    def test_real_dispatch_path_can_send_distinct_components_to_the_same_supplier(self):
        for cooldown, expected in (("30", ["A", "B"]), ("0", ["A", "B", "C"])):
            with self.subTest(cooldown=cooldown):
                address = "supplier@suppliers.juliansibbing.de"
                con = db([("A", address, "Please confirm game card quantities."),
                          ("B", address, "Please confirm art-book pickup."),
                          ("C", address, "Please confirm the game card ETA."),
                          ("D", address, "Please confirm game card quantities.")])
                self.addCleanup(con.close)
                con.execute("UPDATE chases SET material='CMP-GAM-008' WHERE id='B'")
                con.execute("UPDATE chases SET material='CMP-GAM-003' WHERE id='D'")
                con.commit()
                with (
                    mock.patch.dict(os.environ, {"CHASER_REAL_SMTP": "1", "CHASER_AUTO_COOLDOWN_MIN": cooldown,
                                                 "CHASER_AUTO_MAX_PER_CYCLE": "0", "CHASER_SENDER": "qa@example.invalid",
                                                 "CHASER_SMTP_HOST": "example.invalid", "CHASER_SMTP_PORT": "587"}),
                    mock.patch("src.chaser.mailenv.load_team_mail_env"),
                    mock.patch("src.chaser.authenticate"),
                    mock.patch("src.chaser.smtplib.SMTP") as smtp,
                ):
                    receiver = smtp.return_value.__enter__.return_value
                    receiver.send_message.return_value = {}
                    result = autosend.run(con, prepare=False)
                    self.assertEqual([r["id"] for r in result if r["result"] == "sent"], expected)
                    self.assertEqual(receiver.send_message.call_count, len(expected))
                    self.assertIn({"id": "D", "supplier": "Sup D", "result": "duplicate"}, result)
                    autosend.run(con, prepare=False)
                    self.assertEqual(receiver.send_message.call_count, len(expected))

    def test_failed_send_is_logged_not_raised(self):
        con = db([("A", "boss@gmail.com", "Please confirm quantity.")])

        def refuse(con, chase_id):
            raise PermissionError("not on the supplier allowlist")

        self.assertEqual(autosend.run(con, send=refuse, now=NOW, prepare=False)[0]["result"], "failed")


if __name__ == "__main__":
    unittest.main()
