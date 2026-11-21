import unittest

from src.decide.packplan import CE, STD, allocation_rules, plan


def truth(stock, shifts, inbound=()):
    return {
        "editions": {
            CE: {"target": 10, "packed": 0, "rate": 10, "needs": {"P": 1}},
            STD: {"target": 10, "packed": 0, "rate": 10, "needs": {"P": 1}},
        },
        "parts": {"P": {"on_hand": stock}},
        "inbound": list(inbound),
        "shifts": shifts,
    }


class PackPlanTests(unittest.TestCase):
    def test_weight_changes_allocation_and_frontier_is_not_worse(self):
        report = plan(truth(10, [("2026-01-01T00:00:00+00:00", "2026-01-01T01:00:00+00:00")]))
        self.assertEqual(report["best"]["units"], 10)
        self.assertEqual(report["runs"][0]["packed"][STD], 10)
        self.assertEqual(report["runs"][-1]["packed"][CE], 10)
        self.assertGreaterEqual(report["best"]["units"], report["baseline"]["ce_first"]["units"])
        self.assertGreaterEqual(report["best"]["units"], report["baseline"]["std_first"]["units"])

    def test_arrival_what_if_adds_units(self):
        base = truth(0, [("2026-01-01T00:00:00+00:00", "2026-01-01T02:00:00+00:00")],
                     [{"material": "P", "quantity": 10, "earliest": "2026-01-01T01:00:00+00:00"}])
        changed = plan(base, {"part_arrives_earlier": {"P": 1}})
        self.assertGreaterEqual(changed["best"]["units"], 10)

    def test_numbered_rule_is_explicitly_human(self):
        result = allocation_rules(123)
        self.assertTrue(result["human_decision"])
        self.assertEqual(result["rules"][0]["gets"], 123)
        self.assertIn("Head of Procurement", result["owner"])

    def test_shared_part_boundary_is_hand_checkable(self):
        t = truth(15, [("2026-01-01T00:00:00+00:00", "2026-01-01T01:00:00+00:00")])
        t["editions"][CE]["needs"] = {"P": 2}
        t["editions"][STD]["needs"] = {"P": 1}
        result = plan(t)
        self.assertEqual(result["best"]["units"], 10)


if __name__ == "__main__":
    unittest.main()
