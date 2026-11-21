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

    def test_failed_send_is_logged_not_raised(self):
        con = db([("A", "boss@gmail.com", "Please confirm quantity.")])

        def refuse(con, chase_id):
            raise PermissionError("not on the supplier allowlist")

        self.assertEqual(autosend.run(con, send=refuse, now=NOW, prepare=False)[0]["result"], "failed")


if __name__ == "__main__":
    unittest.main()
