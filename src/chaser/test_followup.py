import sqlite3
import unittest
from email.message import EmailMessage

from . import schema
from .followup import answer_body, answer_replies, attachment_evidence, due_reminders, wait_hours

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


class AnswerRepliesTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        schema(self.con)

    def thread(self, cid, supplier_id, material, lang, reply, transport=None):
        self.con.execute("INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)"
                         " VALUES(?,?,?,?,?,?,?,?,?,?,?)", (cid, supplier_id, "Sup " + cid, f"{cid}@suppliers.juliansibbing.de",
                         lang, f"[SOONY-{cid}] Launch stock", "reply to verify", material, 3400, "q", DEADLINE))
        self.con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES(?,?,?,?,?,?)",
                         (cid, cid + "o", "out", "us", "q", "2026-11-21T08:00:00+00:00"))
        self.con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time,transport) VALUES(?,?,?,?,?,?,?)",
                         (cid, cid + "i", "in", "s", reply, "2026-11-21T09:00:00+00:00", transport))

    def test_every_unanswered_reply_gets_one_answer(self):
        self.thread("D", "SUP-0019", "CMP-GAM-010", "zh", "We cannot deliver 3,400 units before the launch.")
        self.thread("B", "SUP-0011", "CMP-GAM-001", "en", "Stock is available EXW Boise, your forwarder must pick up.")
        self.thread("S", "SUP-0018", "CMP-GAM-010", "en", "Simulated", '{"mode": "simulated"}')
        first = answer_replies(self.con, save=True)
        self.assertEqual({a["thread_id"]: a["asks"][0] for a in first}, {"D": "partial", "B": "pickup"})
        self.assertIn("分批", next(a["body"] for a in first if a["thread_id"] == "D"))
        status = self.con.execute("SELECT status, subject FROM chases WHERE id=?", (first[0]["draft_id"],)).fetchone()
        self.assertEqual(status[0], "draft")
        self.assertTrue(status[1].startswith("Re: [SOONY-"))
        self.assertEqual(answer_replies(self.con, save=True), [])  # not answered twice

    def test_cut_off_shown_in_hamburg_time(self):
        body, _ = answer_body("en", "We cannot deliver before the launch.", DEADLINE)
        self.assertIn("22 Nov 20:00 CET", body)

    def test_managed_cases_are_left_to_the_supplier_loop(self):
        self.thread("H", "SUP-0010", "CMP-GAM-001", "ko", "확인 중입니다.")
        self.assertEqual(answer_replies(self.con), [])

    def test_complete_reply_asks_for_document(self):
        body, kinds = answer_body("en", "Quantity: 3,400 pcs, ETA 2026-11-22 08:00, EUR 2.10 per unit", DEADLINE)
        self.assertEqual(kinds, ["document"])
        body, kinds = answer_body("en", "Quantity: 3,400 pcs, ETA 2026-11-22 08:00, EUR 2.10 per unit, AWB 020-12345678", DEADLINE)
        self.assertEqual(kinds, ["noted"])

    def test_local_quality_sort_suppresses_freight_replies_only_on_that_chain(self):
        self.thread("AAA", "SUP-0018", "CMP-GAM-010", "en", "Packing details are pending.")
        draft, = answer_replies(self.con, save=True)
        self.con.execute("UPDATE messages SET transport=? WHERE external_id='AAAo'",
                         ('{"mode":"smtp","status":"smtp_accepted"}',))
        self.con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time,transport) VALUES(?,?,?,?,?,?,?)",
                         ("AAA", "quality", "in", "AAA@suppliers.juliansibbing.de",
                          "We can arrange a 100% visual sort at DC-HAM. Please send the acceptance standard or reference photographs.",
                          "2026-11-21T10:00:00+00:00",
                          '{"mode":"inbox","inReplyTo":"another-sent-mailbox","subject":"Re: [SOONY-AAA] Launch stock"}'))
        self.thread("BBB", "SUP-0018", "CMP-GAM-010", "en",
                    "Shipment NHMU8536079 is planned to arrive in Hamburg on 28 November 2026.")
        self.con.execute("UPDATE chases SET subject='Re: [SOONY-AAA] Launch stock' WHERE id='BBB'")
        self.thread("CCC", "SUP-0018", "CMP-GAM-010", "en", "We have separate released stock. Could you confirm the request?")
        self.assertEqual([item["thread_id"] for item in answer_replies(self.con, save=True)], ["CCC"])
        status = self.con.execute("SELECT status FROM chases WHERE id=?", (draft["draft_id"],)).fetchone()[0]
        self.assertEqual(status, "superseded draft")
        self.assertEqual(answer_replies(self.con, save=True), [])
        self.assertEqual(self.con.execute("SELECT count(*) FROM activity WHERE action LIKE '%Supplier Quality owns%'").fetchone()[0], 1)

    def test_replies_with_unchanged_shipping_evidence_do_not_repeat_the_same_question(self):
        self.thread("AAA", "SUP-0018", "CMP-GAM-010", "en",
                    "We are checking the package details for NHMU8536079.")
        self.assertEqual(len(answer_replies(self.con, save=True)), 1)
        self.con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES(?,?,?,?,?,?)",
                         ("AAA", "duplicate-facts", "in", "supplier", "For NHMU8536079, package details are still being checked.",
                          "2026-11-21T10:00:00+00:00"))
        self.assertEqual(answer_replies(self.con, save=True), [])
