import sqlite3
import unittest
from email.message import EmailMessage

from . import schema
from .followup import attachment_evidence, due_reminders, wait_hours

DEADLINE = "2026-11-22T20:00:00+01:00"


def db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    schema(con)
    con.execute("INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)"
                " VALUES('AAA','SUP-1','Alpha','a@suppliers.juliansibbing.de','pl','[SOONY-AAA] Pytanie','awaiting reply',"
                "'CMP-GAM-008',5900,'b',?)", (DEADLINE,))
    con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES('AAA','o1','out','us','q',"
                "'2026-11-21T08:00:00+00:00')")
    con.commit()
    return con


class ReminderTest(unittest.TestCase):
    def test_wait_shrinks_near_deadline(self):
        self.assertEqual(wait_hours("2026-11-18T00:00:00+00:00", DEADLINE), 12)
        self.assertEqual(wait_hours("2026-11-22T17:00:00+00:00", DEADLINE), 2)

    def test_reminder_drafted_once_then_call(self):
        con = db()
        self.assertEqual(due_reminders(con, "2026-11-21T09:00:00+00:00"), [])  # too early
        first = due_reminders(con, "2026-11-21T20:00:00+00:00", save=True)
        self.assertEqual(first[0]["action"], "remind")
        status = con.execute("SELECT status, language FROM chases WHERE id=?", (first[0]["draft_id"],)).fetchone()
        self.assertEqual(tuple(status), ("draft", "pl"))
        con.execute("UPDATE chases SET status='sent' WHERE id=?", (first[0]["draft_id"],))
        second = due_reminders(con, "2026-11-21T20:00:00+00:00", save=True)
        self.assertEqual(second[0]["reminders_so_far"], 1)
        third = due_reminders(con, "2026-11-21T20:00:00+00:00", save=True)
        self.assertEqual(third[0]["action"], "call")

    def test_reply_stops_reminders(self):
        con = db()
        con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES('AAA','i1','in','a','ok','t')")
        self.assertEqual(due_reminders(con, "2026-11-22T10:00:00+00:00"), [])


class AttachmentTest(unittest.TestCase):
    def test_reads_text_attachment_kind(self):
        msg = EmailMessage()
        msg.set_content("See attached packing list.")
        msg.add_attachment("Packing list\nQty: 5,900 pcs\nAWB 020-48113256", filename="PL-123.txt")
        msg.add_attachment(b"\x00\x01", maintype="application", subtype="octet-stream", filename="scan.bin")
        found = attachment_evidence(msg)
        self.assertEqual(found[0]["kind"], "air_waybill")
        self.assertIn("5,900", found[0]["text"])
        self.assertTrue(found[1]["needs_review"])


if __name__ == "__main__":
    unittest.main()
