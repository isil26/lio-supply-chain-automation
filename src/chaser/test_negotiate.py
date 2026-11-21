import sqlite3
import unittest
from datetime import datetime, timezone

from . import schema
from .negotiate import compare, draft_counter, negotiation_target, parse_offer, rank, Quote

DEADLINE = "2026-11-22T20:00:00+01:00"


def quote(name, qty, eta, price, cur, commitment=2, lang="en"):
    return Quote(name, name, name, f"{name}@suppliers.juliansibbing.de", lang, "CMP-GAM-001", 6800, qty,
                 datetime.fromisoformat(eta).replace(tzinfo=timezone.utc) if eta else None, price, cur, commitment)


class ParseOfferTest(unittest.TestCase):
    def test_reads_quantity_date_price(self):
        offer = parse_offer("We can ship 6,800 pcs, ETA 2026-11-22 09:00. Price USD 4.20 per unit. AWB 020-48113256")
        self.assertEqual(offer["quantity"], 6800)
        self.assertEqual(offer["eta"].isoformat(), "2026-11-22T09:00:00+00:00")
        self.assertEqual((offer["unit_price"], offer["currency"]), (4.2, "USD"))
        self.assertEqual(offer["commitment"], 3)

    def test_date_is_not_read_as_quantity(self):
        self.assertEqual(parse_offer("Delivery 2026-11-22 5000 pcs")["quantity"], 5000)

    def test_vague_reply(self):
        offer = parse_offer("We will do our best.")
        self.assertEqual((offer["quantity"], offer["eta"], offer["unit_price"], offer["commitment"]), (None, None, None, 0))


class RankTest(unittest.TestCase):
    def test_on_time_beats_cheaper_late(self):
        late_cheap = quote("Late", 6800, "2026-11-25", 3.0, "EUR")
        on_time = quote("OnTime", 6800, "2026-11-22T08:00", 4.0, "EUR")
        ranked = rank([late_cheap, on_time], DEADLINE)
        self.assertEqual(ranked[0].supplier, "OnTime")

    def test_target_anchors_on_cheaper_on_time_rival(self):
        a = quote("A", 6800, "2026-11-22T08:00", 4.0, "EUR", commitment=3)
        b = quote("B", 3000, "2026-11-22T08:00", 3.6, "EUR", commitment=1)
        ranked = rank([a, b], DEADLINE)
        self.assertEqual(ranked[0].supplier, "A")
        self.assertEqual(negotiation_target(ranked[0], ranked), 3.6)

    def test_default_ask_when_no_cheaper_rival(self):
        a = quote("A", 6800, "2026-11-22T08:00", 4.0, "EUR")
        self.assertEqual(negotiation_target(a, rank([a], DEADLINE)), 3.8)

    def test_drafts_pass_guardrails_in_all_languages(self):
        for lang in ("en", "pl", "ko", "zh"):
            draft = draft_counter(quote("A", 6800, "2026-11-22", 4.0, "EUR", lang=lang), 3.8)
            self.assertIn("3.8", draft["body"])
            self.assertTrue(draft["subject"].startswith("[SOONY-"))


class CompareDbTest(unittest.TestCase):
    def test_compare_saves_draft_for_approval_only(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        schema(con)
        for cid, sup, body in (("A1", "Alpha", "Quantity: 6800, ETA 2026-11-22 08:00, EUR 4.00 per unit"),
                               ("B1", "Beta", "Quantity: 6800, ETA 2026-11-22 10:00, EUR 3.70 per unit")):
            con.execute("INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?,?)", (cid, sup, sup, f"{sup}@suppliers.juliansibbing.de", "en",
                        "s", "awaiting reply", "CMP-GAM-001", 6800, "b", DEADLINE))
            con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES(?,?,?,?,?,?)",
                        (cid, cid + "m", "in", sup, body, "t"))
        con.commit()
        report = compare(con, DEADLINE, save=True, model=False)
        entry = report["materials"][0]
        self.assertIsNotNone(entry["pick"])
        self.assertIsNotNone(entry["negotiation"])
        status = con.execute("SELECT status FROM chases WHERE id=?", (entry["negotiation"]["draft_id"],)).fetchone()[0]
        self.assertEqual(status, "draft")


if __name__ == "__main__":
    unittest.main()
