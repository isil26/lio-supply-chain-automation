import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path

from . import schema
from .negotiate import (compare, draft_counter, negotiation_asks, parse_offer, score_material, split_order,
                        weights_for, Quote)
from .supplier_facts import facts

DEADLINE = "2026-11-22T20:00:00+01:00"
FAR = datetime(2026, 11, 15, tzinfo=timezone.utc)     # a week out: little time pressure
NEAR = datetime(2026, 11, 22, 6, tzinfo=timezone.utc)  # cut-off today
CASE = Path(__file__).resolve().parents[2] / "case-data"


def quote(name, qty, eta, price, cur="EUR", commitment=2, lang="en", reply=None, supplier_facts=None):
    q = Quote(name, name, name, f"{name}@suppliers.juliansibbing.de", lang, "CMP-GAM-001", 6800, qty,
              datetime.fromisoformat(eta).replace(tzinfo=timezone.utc) if eta else None, price, cur, commitment, reply)
    q.facts = supplier_facts or {"none": True}
    return q


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

    def test_attachment_gives_price_and_proof(self):
        offer = parse_offer("See attached.", [{"kind": "packing_list", "text": "Qty: 3,400\nUnit price EUR 2.10"}])
        self.assertEqual((offer["quantity"], offer["unit_price"], offer["commitment"]), (3400, 2.1, 3))


class CaseFactsTest(unittest.TestCase):
    def test_reads_case_files(self):
        f = facts("SUP-0010", "CMP-GAM-001", CASE)
        self.assertEqual((f["moq"], f["list_price"], f["list_currency"]), (20000, 9.8, "USD"))
        self.assertEqual((f["payment_days"], f["incoterm"], f["customs"]), (45, "FOB", True))
        self.assertEqual(facts("SUP-0028", "CMP-GAM-004", CASE)["incoterm"], "DAP")
        self.assertEqual(facts("SUP-0018", "CMP-GAM-010", CASE)["qualification"], "conditional")


class AdaptiveModelTest(unittest.TestCase):
    def test_weights_follow_the_situation(self):
        calm = weights_for({"time_pressure": 0, "price_pressure": 0})
        rush = weights_for({"time_pressure": 1, "price_pressure": 0})
        swing = weights_for({"time_pressure": 0, "price_pressure": 1})
        self.assertGreater(rush["on_time"], calm["on_time"])
        self.assertGreater(rush["logistics"], calm["logistics"])
        self.assertGreater(swing["price"], calm["price"])
        self.assertAlmostEqual(sum(rush.values()), 1, places=2)

    def test_cost_critical_far_from_deadline_picks_cheap(self):
        ranked, context, _ = score_material([quote("Fast", 6800, "2026-11-20T08:00", 6.0),
                                             quote("Cheap", 6800, "2026-11-22T15:00", 3.0)], DEADLINE, now=FAR)
        self.assertEqual(context["mode"], "cost-critical")
        self.assertEqual(ranked[0].supplier, "Cheap")

    def test_time_critical_on_deadline_day_picks_safe(self):
        ranked, context, _ = score_material(
            [quote("Fast", 6800, "2026-11-22T08:00", 4.4), quote("Cheap", 6800, "2026-11-22T17:00", 4.0)],
            DEADLINE, now=NEAR)
        self.assertEqual(context["mode"], "time-critical")
        self.assertEqual(ranked[0].supplier, "Fast")

    def test_door_delivery_beats_exw_when_otherwise_equal(self):
        dap = {"incoterm": "DAP", "incoterm_full": "DAP Hamburg", "customs": False}
        exw = {"incoterm": "EXW", "incoterm_full": "EXW Boise", "customs": True}
        ranked, _, _ = score_material([quote("Exw", 6800, "2026-11-21", 4.0, supplier_facts=exw),
                                       quote("Dap", 6800, "2026-11-21", 4.0, supplier_facts=dap)], DEADLINE, now=FAR)
        self.assertEqual(ranked[0].supplier, "Dap")

    def test_late_offer_is_backup_only(self):
        ranked, _, _ = score_material([quote("Late", 6800, "2026-11-25", 1.0), quote("OK", 6800, "2026-11-21", 5.0)],
                                      DEADLINE, now=FAR)
        self.assertEqual(ranked[0].supplier, "OK")
        self.assertFalse(ranked[1].eligible)

    def test_split_when_nobody_covers_all(self):
        ranked, _, _ = score_material([quote("A", 4000, "2026-11-21", 4.0), quote("B", 3000, "2026-11-21", 4.2)],
                                      DEADLINE, now=FAR)
        plan = split_order(ranked, 6800)
        self.assertTrue(plan["split"])
        self.assertEqual(sum(a["units"] for a in plan["allocation"]), 6800)
        self.assertEqual(plan["uncovered"], 0)


class NegotiationTest(unittest.TestCase):
    def test_price_anchor_on_cheaper_rival(self):
        ranked, context, _ = score_material([quote("A", 6800, "2026-11-20", 4.0, commitment=3, reply=1),
                                             quote("B", 3000, "2026-11-20", 3.6, commitment=1)], DEADLINE, now=FAR)
        a = next(q for q in ranked if q.supplier == "A")
        asks = negotiation_asks(a, ranked, context, DEADLINE)
        self.assertIn({"lever": "price", "target": 3.6, "from": 4.0, "currency": "EUR"}, asks)

    def test_contract_price_and_moq_levers(self):
        f = {"list_price": 9.8, "list_currency": "USD", "moq": 20000}
        ranked, context, _ = score_material([quote("A", 6800, "2026-11-20", 10.5, cur="USD", supplier_facts=f)],
                                            DEADLINE, now=FAR)
        asks = negotiation_asks(ranked[0], ranked, context, DEADLINE)
        self.assertIn({"lever": "price", "target": 9.8, "from": 10.5, "currency": "USD"}, asks)
        self.assertIn({"lever": "moq", "units": 6800}, asks)

    def test_tight_delivery_asks_for_date_partial_express(self):
        ranked, context, _ = score_material([quote("A", 6800, "2026-11-22T16:00", 4.0)], DEADLINE, now=NEAR)
        levers = [a["lever"] for a in negotiation_asks(ranked[0], ranked, context, DEADLINE)]
        self.assertTrue({"earlier", "partial", "express"} <= set(levers))

    def test_drafts_pass_guardrails_in_all_languages(self):
        asks = [{"lever": "price", "target": 3.8, "from": 4.0, "currency": "EUR"},
                {"lever": "earlier", "target": "2026-11-21 19:00 UTC"},
                {"lever": "partial", "units": 3400, "target": "2026-11-21 19:00 UTC"}, {"lever": "express"},
                {"lever": "moq", "units": 6800}]
        for lang in ("en", "pl", "ko", "zh"):
            draft = draft_counter(quote("A", 6800, "2026-11-22", 4.0, lang=lang), asks)
            self.assertIn("3.8", draft["body"])
            self.assertTrue(draft["subject"].startswith("[SOONY-"))


class CompareDbTest(unittest.TestCase):
    def test_compare_saves_drafts_for_approval_only(self):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        schema(con)
        for cid, sup, body in (("A1", "Alpha", "Quantity: 4000, ETA 2026-11-21 08:00, EUR 4.00 per unit"),
                               ("B1", "Beta", "Quantity: 3000, ETA 2026-11-21 10:00, EUR 3.70 per unit")):
            con.execute("INSERT INTO chases(id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?,?)", (cid, sup, sup, f"{sup}@suppliers.juliansibbing.de", "en",
                        "s", "awaiting reply", "CMP-GAM-001", 6800, "b", DEADLINE))
            con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES(?,?,?,?,?,?)",
                        (cid, cid + "o", "out", "us", "q", "2026-11-20T08:00:00+00:00"))
            con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES(?,?,?,?,?,?)",
                        (cid, cid + "m", "in", sup, body, "2026-11-20T11:00:00+00:00"))
        con.commit()
        report = compare(con, DEADLINE, save=True, model=False, now=FAR)
        entry = report["materials"][0]
        self.assertTrue(entry["plan"]["split"])
        self.assertTrue(entry["negotiations"])
        for n in entry["negotiations"]:
            status = con.execute("SELECT status FROM chases WHERE id=?", (n["draft_id"],)).fetchone()[0]
            self.assertEqual(status, "draft")
        self.assertEqual(entry["ranking"][0]["factors"]["speed"], 0.8)
        # a second round (new reply, new target) must not create a second negotiation email
        con.execute("INSERT INTO messages(chase_id,external_id,side,sender,body,time) VALUES(?,?,?,?,?,?)",
                    ("A1", "A1m2", "in", "Alpha", "Quantity: 4000, ETA 2026-11-21 06:00, EUR 3.95 per unit", "2026-11-20T12:00:00+00:00"))
        again = compare(con, DEADLINE, save=True, model=False, now=FAR)["materials"][0]
        self.assertFalse(any(n["saved"] for n in again["negotiations"]))


if __name__ == "__main__":
    unittest.main()
