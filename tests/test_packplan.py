import unittest
from datetime import datetime, timedelta

from src.decide.packplan import (CE_MAX, _inputs, _slots, allocation_rules, arrival_lag_hours,
                                 plan, run_policy, summarize)
from src.ingest.store import DB

CE, STD = "FG-GH6-CE", "FG-GH6-STD"
T0 = "2026-01-01T00:00:00+00:00"


def truth(parts, hours=1.0, target=10, rate=10, inbound=(), packed=0):
    """Readiness-shaped input: parts is {id: (on_hand, ce_qty, std_qty)}."""
    end = (datetime.fromisoformat(T0) + timedelta(hours=hours)).isoformat()
    return {
        "editions": {pid: {"target": target, "packed": packed, "rate": rate} for pid in (CE, STD)},
        "parts": {p: {"on_hand": s, "raw_stock": s, "embedded_in": None,
                      "unit_usage": {k: q for k, q in ((CE, c), (STD, d)) if q}}
                  for p, (s, c, d) in parts.items()},
        "inbound": list(inbound),
        "shifts": [[T0, end]],
    }


def run_at(report, w):
    return next(r for r in report["runs"] if r["weight"] == w)


class HandCheckable(unittest.TestCase):
    def test_shared_part_frontier_and_gain_over_both_baselines(self):
        # 15 units of P; CE needs 2, STD needs 1; 5/slot caps, 2 slots, 10 each.
        # Both greedy baselines pack 10; the optimum is X=3 CE, Y=9 STD = 12.
        report = plan(truth({"P": (15, 2, 1)}))
        self.assertEqual(report["baseline"]["ce_first"]["units"], 10)
        self.assertEqual(report["baseline"]["std_first"]["units"], 10)
        best = run_at(report, 1)
        self.assertEqual((best["packed"][CE], best["packed"][STD], best["units"]), (3, 9, 12))
        self.assertEqual(best["gain_vs_best_baseline"], 2)
        # w=2: X=3,5,7 all score 15, tie broken by total units -> (3, 9); w=5: X=7, Y=1
        self.assertEqual(run_at(report, 2)["packed"][CE], 3)
        self.assertEqual((run_at(report, 5)["packed"][CE], run_at(report, 5)["packed"][STD]), (7, 1))
        self.assertEqual(run_at(report, 0)["packed"][STD], 10)
        self.assertEqual(run_at(report, 0)["packed"][CE], 2)  # free CE units: Y stays 10
        self.assertEqual(run_at(report, CE_MAX)["packed"][CE], 7)

    def test_never_worse_than_either_baseline(self):
        for stock, ce_q, std_q in [(15, 2, 1), (7, 1, 1), (100, 3, 2), (9, 4, 1)]:
            report = plan(truth({"P": (stock, ce_q, std_q)}))
            floor = max(b["units"] for b in report["baseline"].values())
            for run in report["runs"]:
                self.assertEqual(run["gain_vs_best_baseline"], run["units"] - floor)
            self.assertGreaterEqual(run_at(report, 1)["units"], floor)

    def test_schedule_respects_caps_parts_and_totals(self):
        t = truth({"P": (15, 2, 1), "Q": (6, 1, 0)}, hours=2.0)
        report = plan(t)
        for run in report["runs"]:
            self.assertEqual(sum(b["CE"] for b in run["buckets"]), run["packed"][CE])
            self.assertEqual(sum(b["STD"] for b in run["buckets"]), run["packed"][STD])
            for b in run["buckets"]:
                self.assertLessEqual(b["CE"], 5)
                self.assertLessEqual(b["STD"], 5)
            self.assertLessEqual(2 * run["packed"][CE] + run["packed"][STD], 15)
            self.assertLessEqual(run["packed"][CE], 6)

    def test_late_arrival_limited_by_rate(self):
        # nothing in stock; 10 arrive at 00:30 (earliest lag rule): only the last
        # slot (cap 5 per line) can use them, so exactly 10 pack (5 CE + 5 STD).
        inbound = [{"material": "P", "quantity": 10, "earliest": "2026-01-01T00:30:00+00:00",
                    "held": False, "mode": "road"}]
        report = plan(truth({"P": (0, 1, 1)}, inbound=inbound), lag="earliest")
        self.assertEqual(run_at(report, 1)["units"], 10)
        # with the median road lag (~3.4 h) the lot misses the 1 h shift
        report = plan(truth({"P": (0, 1, 1)}, inbound=inbound))
        self.assertEqual(run_at(report, 1)["units"], 0)

    def test_held_inbound_needs_release(self):
        inbound = [{"material": "P", "quantity": 10, "earliest": T0, "held": True, "mode": "road"}]
        base = truth({"P": (0, 1, 1)}, inbound=inbound)
        self.assertEqual(run_at(plan(base, lag="earliest"), 1)["units"], 0)
        released = plan(base, {"release_held": ["P"]}, lag="earliest")
        self.assertEqual(released["delta_vs_unchanged"][2]["units"], 10)

    def test_what_if_restore_stock_and_preorders_saved(self):
        t = truth({"P": (100, 1, 1), "ART": (4, 1, 0)})
        out = plan(t, {"restore_stock": {"ART": 3}})
        self.assertEqual(run_at(out, CE_MAX)["packed"][CE], 7)
        self.assertEqual(out["preorders_saved"]["numbered_ce_copies"], 3)
        with self.assertRaises(ValueError):
            plan(t, {"restore_stock": {"NOPE": 1}})

    def test_embedded_part_is_supplier_fitted_flag(self):
        t = truth({"P": (100, 1, 1)})
        t["parts"]["MAG"] = {"on_hand": 100, "raw_stock": 0, "embedded_in": "P", "unit_usage": {CE: 4}}
        self.assertEqual(run_at(plan(t), CE_MAX)["packed"][CE], 10)
        self.assertEqual(run_at(plan(t, magnet_fitted=False), CE_MAX)["packed"][CE], 0)
        self.assertIn("CE cannot be packed", plan(t)["assumptions"][1])

    def test_pause_and_resume_events(self):
        inbound = [{"material": "P", "quantity": 100, "earliest": "2026-01-01T01:00:00+00:00",
                    "held": False, "mode": "road"}]
        t = truth({"P": (5, 1, 0)}, hours=2.0, inbound=inbound)
        out = run_at(plan(t, lag="earliest"), 1)
        kinds = [(e["edition"], e["event"]) for e in out["events"]]
        self.assertIn(("CE", "pause"), kinds)
        self.assertIn(("CE", "resume"), kinds)

    def test_lag_rules_and_allocation(self):
        self.assertEqual(arrival_lag_hours("air", "earliest"), 0)
        self.assertEqual(arrival_lag_hours("air", "mode"), 8)
        self.assertGreater(arrival_lag_hours("air"), 8)
        result = allocation_rules(123)
        self.assertTrue(result["human_decision"])
        self.assertEqual(result["rules"][0]["gets"], 123)
        self.assertIn("Head of Procurement", result["owner"])
        self.assertIn("71,877", result["consequence"])

    def test_summary_is_json_safe(self):
        import json
        json.dumps(summarize(plan(truth({"P": (15, 2, 1)}))))


class Consistency(unittest.TestCase):
    def sim_inputs(self, t):
        inp = _inputs(t, lag="earliest")
        eds = {pid: {"target": t["editions"][pid]["target"], "packed": t["editions"][pid]["packed"],
                     "rate": t["editions"][pid]["rate"]} for pid in (CE, STD)}
        shifts = [(datetime.fromisoformat(a), datetime.fromisoformat(b)) for a, b in t["shifts"]]
        return inp, eds, shifts

    def test_baselines_equal_truth_simulate_without_inbound(self):
        from src.truth import simulate
        for parts in ({"P": (15, 2, 1)}, {"P": (7, 1, 1), "Q": (4, 1, 0)}, {"P": (1000, 1, 1)}):
            t = truth(parts, hours=2.0)
            inp, eds, shifts = self.sim_inputs(t)
            slots = _slots(inp)
            for mode, order in (("ce_first", (CE, STD)), ("std_first", (STD, CE))):
                sim = simulate(eds, inp["needs"], inp["stock"], [], shifts, mode=mode, trials=3)
                run = run_policy(inp, order, slots)
                for pid in (CE, STD):
                    self.assertEqual(run["packed"][pid], sim[pid]["p50"], (parts, mode, pid))

    @unittest.skipUnless(DB.exists(), "store not built")
    def test_real_baseline_reproduces_numbers_md(self):
        from src.decide.packplan import _load_truth
        truth_ = _load_truth()
        report = plan(truth_)
        ed = truth_["editions"]
        ce_first = report["baseline"]["ce_first"]["packed"]
        std_first = report["baseline"]["std_first"]["packed"]
        # docs/NUMBERS.md: STD 614,650 / CE 62,550 (ce_first p50); readiness std_first p50 615,100 / 62,100
        self.assertEqual(ed[STD]["packed"] + ce_first[STD], ed[STD]["p50"])
        self.assertEqual(ed[CE]["packed"] + ce_first[CE], ed[CE]["p50"])
        self.assertEqual(ed[STD]["packed"] + std_first[STD], ed[STD]["std_first_p50"])
        self.assertEqual((ed[STD]["p50"], ed[CE]["p50"]), (614650, 62550))
        floor = max(b["units"] for b in report["baseline"].values())
        self.assertGreaterEqual(run_at(report, 1)["units"], floor)
        self.assertNotIn(0, [r["packed"][CE] for r in report["runs"] if r["weight"] >= 1])


if __name__ == "__main__":
    unittest.main()
