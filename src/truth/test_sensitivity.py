"""Regression tests for calibrated, paired launch what-ifs."""
from contextlib import closing
from copy import deepcopy
import json
import sqlite3
import unittest

from src.truth.sensitivity import calibrate_supplier_lags, counterfactual, plan_b_cases, sensitivity


START = "2026-01-10T08:00:00+01:00"
END = "2026-01-10T09:00:00+01:00"
LATE = "2026-01-11T08:00:00+01:00"


def fixture():
    return {
        "editions": {pid: {"target": 4, "packed": 0, "rate": 4} for pid in ("FG-STD", "FG-CE")},
        "parts": {
            "card": {"material": "card", "label": "Card", "on_hand": 4, "shortfall": 4,
                     "unit_usage": {"FG-STD": 1, "FG-CE": 1}},
            "book": {"material": "book", "label": "Book", "on_hand": 1, "shortfall": 3,
                     "unit_usage": {"FG-CE": 1}},
            "magnet": {"on_hand": 0, "embedded_in": "card", "unit_usage": {"FG-CE": 4}},
        },
        "shifts": [[START, END]],
        "inbound": [
            {"id": "A", "mode": "road", "material": "card", "quantity": 2,
             "supplier": "SUP-0001", "held": False, "earliest": LATE},
            {"id": "B", "mode": "air", "material": "card", "quantity": 2,
             "supplier": "SUP-0001", "held": False, "earliest": LATE},
            {"id": "C", "mode": "air", "material": "card", "quantity": 4,
             "supplier": "SUP-0002", "held": True, "earliest": START},
        ],
        "issues": [{"kind": "quality_hold", "material": "book", "quantity": 5}],
        "model": {"lag_hours": {"road": (0, 0, 0), "air": (0, 0, 0)}},
    }


class CalibrationTests(unittest.TestCase):
    def test_deduplicates_and_uses_delivered_positive_rows_before_cutoff(self):
        with closing(sqlite3.connect(":memory:")) as con:
            con.row_factory = sqlite3.Row
            con.execute("""CREATE TABLE purchase_orders (
                po_number TEXT, po_line INT, supplier_id TEXT, quantity REAL,
                order_date TEXT, promised_date TEXT, actual_delivery_date TEXT, status TEXT,
                source TEXT, source_sheet TEXT, source_row INT
            )""")

            def add(po, actual, source="modern.csv", supplier="S1", quantity=1, status="delivered"):
                con.execute("INSERT INTO purchase_orders VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, '', ?)",
                            (po, supplier, quantity, "2025-01-01", "2025-01-05", actual, status, source, po))

            add(1, "2025-01-09", "legacy.csv")
            add(1, "2025-01-06")
            add(2, "2025-01-04")
            add(3, "2026-01-10")
            add(4, "2025-01-08", quantity=-1)
            add(5, "2025-01-08", status="open")
            add(6, None)
            add(7, "2025-01-08", supplier="S2")
            profiles = calibrate_supplier_lags(con, before=START, min_samples=2)

        self.assertEqual(profiles["S1"]["hours"], [0, 24])
        self.assertEqual(profiles["S1"]["sample_count"], 2)
        self.assertEqual({source["file"] for source in profiles["S1"]["evidence"]}, {"modern.csv"})
        self.assertEqual(profiles["S2"]["method"], "mode_prior")
        self.assertEqual(profiles["S2"]["hours"], [])


class ReplayTests(unittest.TestCase):
    def test_shifts_holds_and_stock_additions(self):
        truth = fixture()
        original = deepcopy(truth)
        changes = {"add_units": {"book": 3}}
        baseline = counterfactual(truth, changes, trials=5)
        one = counterfactual(truth, dict(changes, shipment_days={"A": -1}), trials=5)
        both = counterfactual(truth, dict(changes, supplier_days={"SUP-0001": -1}), trials=5)
        release = counterfactual(truth, dict(changes, release_shipments=["C"]), trials=5)
        held_only = counterfactual(truth, dict(changes, shipment_days={"C": -1}), trials=5)
        self.assertEqual([f["combined"]["expected_packed"] for f in (baseline, one, both, release)],
                         [4, 6, 8, 8])
        self.assertEqual(held_only, baseline)
        self.assertEqual(both["combined"]["probability"], 1)
        self.assertEqual(one["combined"]["probability"], 0)
        self.assertEqual(truth, original)

    def test_criticality_deduplicates_component_across_editions_and_keeps_ties(self):
        truth = fixture()
        truth["parts"]["card"]["on_hand"] = 1
        result = counterfactual(truth, {}, trials=7)
        self.assertEqual(result["criticality"], {"book": 1, "card": 1})
        self.assertEqual(result["editions"]["FG-CE"]["first_stop_trials"], {"book": 7, "card": 7})
        self.assertEqual(result["editions"]["FG-STD"]["first_stop_trials"], {"card": 7})

    def test_empirical_lag_and_paired_scenarios_are_repeatable(self):
        truth = fixture()
        truth["inbound"][0]["earliest"] = START
        truth["parts"]["card"]["on_hand"] = 6
        changes = {"add_units": {"book": 3}}
        cases = [{"label": "Stock", "changes": changes}, {"label": "No change", "changes": {}}]
        profiles = {"SUP-0001": {"hours": [0, 24]}, "SUP-0002": {"hours": []}}
        kwargs = dict(lag_profiles=profiles, cases=cases, trials=91)
        report = sensitivity(truth, **kwargs)
        self.assertEqual(json.dumps(report), json.dumps(sensitivity(truth, **kwargs)))
        self.assertEqual(report["scenarios"][-1]["delta"]["combined"], {"expected_packed": 0, "probability": 0})
        self.assertEqual(report["baseline"]["combined"]["expected_packed"], 5)
        result = counterfactual(truth, changes, lag_profiles=profiles, trials=91)
        self.assertGreater(result["combined"]["expected_packed"], 6)
        self.assertLess(result["combined"]["expected_packed"], 8)
        self.assertGreater(result["combined"]["probability"], 0)
        self.assertLess(result["combined"]["probability"], 1)
        self.assertEqual(len(report["scenarios"]), 12)

    def test_release_with_new_eta_and_plan_b_cases(self):
        truth = fixture()
        truth["inbound"][2]["earliest"] = LATE
        docs = [{"fields": {"available_offer": [
            {"value": {"material": "book", "quantity": 6}, "citation": {"file": "offer.pdf", "page": 1}}
        ]}}]
        scheduled, early, offered, quarantine = plan_b_cases(truth, docs)
        self.assertEqual(offered["changes"], {"add_units": {"book": 3}})
        self.assertEqual(quarantine["changes"], {"add_units": {"book": 5}})
        base = counterfactual(truth, scheduled["changes"], trials=3)
        rescue = counterfactual(truth, early["changes"], trials=3)
        self.assertEqual(base["combined"]["expected_packed"], 4)
        self.assertEqual(rescue["combined"]["expected_packed"], 5)

    def test_empty_shift_window_and_invalid_change_id(self):
        truth = fixture()
        truth["shifts"] = []
        self.assertEqual(counterfactual(truth, {}, trials=1)["combined"]["expected_packed"], 0)
        with self.assertRaisesRegex(ValueError, "Unknown shipment ID"):
            counterfactual(truth, {"shipment_days": {"unknown": 1}}, trials=1)


if __name__ == "__main__":
    unittest.main()
