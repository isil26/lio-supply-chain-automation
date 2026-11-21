"""Tests for empirical arrival priors and expedite economics."""

from contextlib import closing, redirect_stdout
from datetime import timedelta
from io import StringIO
import sqlite3
import unittest

from src.decide.expedite import choose, main
from src.decide.reliability import SupplierReliability, discounted_eta, p_on_time
from src.truth.test_sensitivity import LATE, START, fixture


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        with closing(sqlite3.connect(":memory:")) as con:
            con.row_factory = sqlite3.Row
            con.execute("""CREATE TABLE purchase_orders (
                po_number TEXT, po_line INT, supplier_id TEXT, quantity REAL,
                order_date TEXT, promised_date TEXT, actual_delivery_date TEXT, status TEXT,
                source TEXT, source_sheet TEXT, source_row INT
            )""")
            samples = [("slow", day) for day in (4, 5, 6, 7, 7, 9)]
            samples += [("fast", day) for day in (3, 4, 5, 5, 5, 6)]
            samples.append(("sparse", 5))
            for row, (supplier, actual) in enumerate(samples, 2):
                con.execute(
                    """INSERT INTO purchase_orders VALUES (?, 1, ?, 1, '2026-01-01',
                    '2026-01-05', ?, 'delivered', 'orders.csv', '', ?)""",
                    (row, supplier, f"2026-01-{actual:02d}", row),
                )
            self.model = SupplierReliability(con)
            self.cold = SupplierReliability(con, before="2026-01-02")

    def test_eta_quantiles_and_deadlines(self):
        slow = discounted_eta("slow", START, deadline=START, model=self.model)
        fast = self.model.discounted_eta("fast", START)
        self.assertGreater(slow.eta_p50, fast.eta_p50)
        self.assertEqual(slow.eta_p90 - fast.eta_p50, timedelta(days=4))
        self.assertAlmostEqual(slow.p_on_time, 2 / 6)
        self.assertEqual(p_on_time("slow", START, "2026-01-10T06:59:00Z", model=self.model), 0)
        self.assertAlmostEqual(self.model.p_on_time("slow", START, "2026-01-11T07:00:00Z"), 3 / 6)

    def test_sparse_suppliers_use_cited_global_prior(self):
        sparse = self.model.profile("sparse")
        self.assertTrue(sparse["low_data"])
        self.assertEqual((sparse["sample_count"], sparse["prior_sample_count"]), (1, 13))
        self.assertEqual(sparse["method"], "global")
        self.assertIn({"file": "orders.csv", "sheet": "", "row": 2}, sparse["evidence"])
        self.assertEqual(self.model.p_on_time("sparse", START, START),
                         self.model.p_on_time("unknown", START, START))
        self.assertEqual(len(self.model.profile("slow")["evidence"]), 6)

    def test_updates_and_cold_start(self):
        self.model.update("slow", True)
        self.assertAlmostEqual(self.model.p_on_time("slow", START, START), 3 / 7)
        self.model.update("slow", False)
        self.assertAlmostEqual(self.model.p_on_time("slow", START, START), 3 / 8)
        self.assertEqual(self.model.profile("slow")["observed_misses"], 1)
        self.assertEqual(self.cold.profile("slow")["method"], "cold_start")
        self.assertEqual(self.cold.p_on_time("slow", START, START), 0.5)


class ExpediteTests(unittest.TestCase):
    def setUp(self):
        self.options = [
            {"label": "Wait", "cost_eur": 0, "p_on_time": 0.25},
            {"label": "Express", "cost_eur": 12390, "p_on_time": 0.75},
        ]

    def test_no_loss_assumption_and_sensitivity(self):
        report = choose(self.options, None, 5900)
        self.assertEqual(report["status"], "needs Dr. Vogt")
        self.assertIsNone(report["recommendation"])
        self.assertEqual(report["thresholds"][0]["break_even_loss_eur"], 4.2)
        self.assertEqual(report["sensitivity"][0]["break_even_loss_eur"], [10.5, 4.2, 2.625])
        self.assertEqual(report["sensitivity"][0]["grid"][1]["net_benefit_eur"], [-6490, 2360, 11210])

    def test_expected_cost_and_pairwise_thresholds(self):
        options = self.options + [{"label": "Alternate", "cost_eur": 15000, "p_on_time": 0.5}]
        self.assertEqual(choose(options, 2, 5900)["recommendation"]["label"], "Wait")
        self.assertEqual(choose(options, 4.2, 5900)["recommendation"]["label"], "Wait")
        report = choose(options, 5, 5900)
        self.assertEqual(report["recommendation"]["label"], "Express")
        self.assertEqual(report["recommendation"]["source"], "assumption")
        self.assertEqual(report["recommendation"]["expected_cost_eur"], 19765)
        self.assertEqual(len(report["thresholds"]), 3)
        self.assertIsNone(report["thresholds"][-1]["break_even_loss_eur"])

    def test_joint_counterfactual_keeps_late_shipment_out_of_packout(self):
        options = [
            {"label": "Wait", "cost_eur": 0},
            {"label": "Books and late cards", "cost_eur": 1, "changes": {
                "add_units": {"book": 3}, "release_shipments": ["C"],
                "shipment_earliest": {"C": LATE},
            }},
            {"label": "Books and timely cards", "cost_eur": 2, "p_on_time": 0.1,
             "changes": {"add_units": {"book": 3}, "release_shipments": ["C"]}},
        ]
        report = choose(options, 5, 4, truth=fixture(), trials=4)
        self.assertEqual([item["p_on_time"] for item in report["options"]], [0, 0, 1])
        self.assertEqual(report["recommendation"]["source"], "counterfactual")
        self.assertEqual(report["recommendation"]["label"], "Books and timely cards")

    def test_cli_prints_cited_markdown_with_unknown_loss(self):
        output = StringIO()
        with redirect_stdout(output):
            main()
        for fragment in ("needs Dr. Vogt", "5,900", "12,390", "docs/NUMBERS.md", "10.50 | 4.20 | 2.63"):
            self.assertIn(fragment, output.getvalue())


if __name__ == "__main__":
    unittest.main()
