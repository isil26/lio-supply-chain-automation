from unittest import TestCase
from unittest.mock import patch

from . import deals, offer_limits
from .test_deals import NOW, DEADLINE, db


class ProductLimitTests(TestCase):
    def setUp(self):
        self.con = db()
        self.addCleanup(self.con.close)
        self.clock = patch.object(deals, "_now", return_value=NOW.isoformat())
        self.clock.start()
        self.addCleanup(self.clock.stop)
        sync = deals.sync
        fixed = patch.object(deals, "sync", side_effect=lambda con, cutoff: sync(con, cutoff, now=NOW, model=False))
        fixed.start()
        self.addCleanup(fixed.stop)
        deals.sync(self.con, DEADLINE)
        self.material = "CMP-GAM-001"
        self.truth = {"deadline":DEADLINE, "parts":{self.material:{"shortfall":6800}}}

    def rows(self):
        return deals.list_deals(self.con)["deals"]

    def run_cycle(self):
        offer_limits.apply(self.con, self.truth, 0, demo=True)

    def test_default_price_ceiling_and_manual_dispatch(self):
        self.run_cycle()
        self.assertEqual([r["status"] for r in self.rows()], ["pending", "pending"])
        quote = next(r for r in self.rows() if r["best"])
        price = quote["price_eur"]
        offer_limits.set_limit(self.con, self.material, price - 0.01, 0, "Reviewer A")
        self.run_cycle()
        self.assertTrue(all(r["status"] == "pending" for r in self.rows()))
        with self.assertRaisesRegex(ValueError, "changed"):
            offer_limits.set_limit(self.con, self.material, price, 0, "Reviewer B")
        offer_limits.set_limit(self.con, self.material, price, round(price - 0.01, 4), "Reviewer A")
        self.run_cycle()
        self.run_cycle()
        approved, = [r for r in self.rows() if r["status"] == "approved"]
        self.assertEqual(approved["decided_by"], "Reviewer A")
        self.assertTrue(approved["awaiting_send"])
        self.assertIsNone(approved["email_id"])
        self.assertEqual(len(approved["history"]), 1)
        self.assertEqual(len(approved["history"][0]["terms"]["alternatives"]), 2)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM chases WHERE status='draft'").fetchone()[0], 0)
        for _ in range(2):
            released = deals.decide(self.con, approved["id"], "approve", "Reviewer B",
                                    revision=approved["revision"], confirm_held=True)
        self.assertFalse(released["awaiting_send"])
        self.assertEqual(released["decided_by"], "Reviewer A")
        self.assertTrue(deals.check_draft(self.con, released["email_id"]))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM chases WHERE status='draft'").fetchone()[0], 1)

    def test_covered_product_and_disabled_rule(self):
        price = next(r["price_eur"] for r in self.rows() if r["best"])
        offer_limits.set_limit(self.con, self.material, price, 0, "Reviewer")
        self.truth["parts"][self.material]["shortfall"] = 0
        self.run_cycle()
        offer_limits.set_limit(self.con, self.material, 0, price, "Reviewer")
        self.truth["parts"][self.material]["shortfall"] = 6800
        self.run_cycle()
        self.assertTrue(all(r["status"] == "pending" for r in self.rows()))

    def test_catalogue_currency_and_product_scales(self):
        self.con.execute("CREATE TABLE supplier_components(component_id,supplier_id,unit_price,currency)")
        self.con.executemany("INSERT INTO supplier_components VALUES(?,?,?,?)", [
            ("sleeve","A",0.1,"EUR"), ("card","B",100,"USD")])
        rows = [dict(material=m,supplier_id=s,offer_kind="goods",offer_state="incomplete",price_eur=None)
                for m,s in (("sleeve","A"),("card","B"),("unknown","C"))]
        policies = offer_limits.market(self.con, rows)
        self.assertAlmostEqual(policies["sleeve"]["reference"], 0.1)
        self.assertAlmostEqual(policies["card"]["reference"], 92)
        self.assertLess(policies["sleeve"]["maximum"], 1)
        self.assertGreater(policies["card"]["maximum"], 100)
        self.assertEqual(policies["unknown"]["maximum"], 0)
