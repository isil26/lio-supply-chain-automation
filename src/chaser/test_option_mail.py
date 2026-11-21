import os
import sqlite3
import unittest
from unittest import mock

from . import option_mail, schema
from .guardrails import Guardrails
from .supplier_loop import BOOK


def db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    schema(con)
    con.execute("CREATE TABLE suppliers(supplier_id TEXT, name TEXT, contact_name TEXT, contact_email TEXT, preferred_language TEXT)")
    con.execute("INSERT INTO suppliers VALUES('SUP-1','Boise Semi','Ann','sales@suppliers.juliansibbing.de','en')")
    con.execute("INSERT INTO suppliers VALUES(?, 'Karton Nowak','Jan','k@suppliers.juliansibbing.de','pl')", (BOOK[0],))
    return con


OPTION = {"id": "abc123", "kind": "alternate", "title": "Check Boise Semi stock", "supplier_id": "SUP-1", "material": "CMP-X",
          "recommendation": "Request a hold and a written delivered quote for 6,800 finished units from Boise.",
          "latest_action": "2026-11-22T09:00:00+01:00", "evidence": ["offer.pdf"]}


@mock.patch.dict(os.environ, {"CHASER_SENDER": "team@example.invalid"})
class OptionMailTest(unittest.TestCase):
    def test_preview_then_approve_sends_exactly_that_email(self):
        con = db()
        mail = option_mail.preview(con, OPTION)
        self.assertEqual((mail["mode"], mail["to"], mail["qty"]), ("send", "sales@suppliers.juliansibbing.de", 6800))
        self.assertIn("6,800 units of CMP-X", mail["body"])
        self.assertTrue(Guardrails().validate_draft(mail["body"]).ok)
        row = option_mail.send(con, OPTION, "Gülşah", demo=True, mail=mail)
        self.assertEqual((row["status"], row["approved_by"], row["recipient"]), ("sent", "Gülşah", mail["to"]))
        self.assertEqual(con.execute("SELECT body FROM messages WHERE side='out'").fetchone()[0], mail["body"])

    def test_all_languages_pass_guardrails(self):
        for language, (subject, body) in option_mail.HOLD_QUOTE.items():
            text = body.format(name="X", part="P", qty=10, deadline="22 Nov")
            self.assertTrue(Guardrails().validate_draft(text).ok, language)

    def test_supplier_loop_case_shows_the_ongoing_email_and_sends_nothing(self):
        con = db()
        con.execute("INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)"
                    " VALUES('T1',?,'Karton','k@suppliers.juliansibbing.de','pl','Zapytanie','awaiting reply',?,1,'b','d')", BOOK)
        con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES('T1','m','out','us','Dzień dobry','2026-11-21T22:00:00+00:00')")
        option = dict(OPTION, supplier_id=BOOK[0], material=BOOK[1])
        mail = option_mail.preview(con, option)
        self.assertEqual((mail["mode"], mail["body"], mail["threadId"]), ("conversation", "Dzień dobry", "T1"))
        self.assertIsNone(option_mail.send(con, option, "Gülşah", demo=True, mail=mail))

    def test_no_supplier_email(self):
        self.assertEqual(option_mail.preview(db(), dict(OPTION, supplier_id=None))["mode"], "none")
        self.assertEqual(option_mail.preview(db(), dict(OPTION, kind="quality"))["mode"], "none")


if __name__ == "__main__":
    unittest.main()
