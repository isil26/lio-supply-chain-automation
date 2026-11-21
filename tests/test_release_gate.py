import unittest

from src.decide.release_gate import evaluate


SOURCE = {"file": "inspection.txt", "page": 1, "quote": "Lot does not meet AQL."}


def truth(issue=None):
    return {
        "deadline": "2026-11-22T20:00:00+01:00",
        "parts": {"STATUE": {"material": "STATUE", "label": "Statue", "required": 10,
                             "on_hand": 10, "suppliers": [], "unit_usage": {"FG-CE": 1},
                             "evidence": []}},
        "editions": {"FG-CE": {"edition": "CE", "remaining": 10}},
        "issues": [issue] if issue else [],
    }


class ReleaseGateTests(unittest.TestCase):
    def test_quality_hold_flips_go_to_hold(self):
        clean = evaluate(truth())
        held = evaluate(truth({"material": "STATUE", "kind": "quality_hold", "quantity": 4,
                               "title": "4 units failed AQL", "evidence": [SOURCE]}))
        self.assertEqual(clean["parts"]["STATUE"]["status"], "GO")
        self.assertEqual(held["parts"]["STATUE"]["status"], "HOLD")
        self.assertEqual(held["parts"]["STATUE"]["held_quantity"], 4)
        self.assertEqual(held["parts"]["STATUE"]["evidence"][0]["quote"], SOURCE["quote"])

    def test_incoterm_conflict_is_non_blocking(self):
        result = evaluate(truth({"material": "STATUE", "kind": "confirmation",
                                 "changed_fields": ["incoterm"], "evidence": [SOURCE]}))
        self.assertEqual(result["parts"]["STATUE"]["status"], "GO")
        self.assertIn("Incoterms", result["parts"]["STATUE"]["reasons"][0])


if __name__ == "__main__":
    unittest.main()
