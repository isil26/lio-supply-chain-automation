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

    def test_artwork_revision_conflict_via_alias(self):
        def doc(supplier, po, code, qty, quote, rev):
            cite = {"file": f"{supplier}.pdf", "page": 1, "quote": quote}
            return {"kind": "confirmation", "supplier_id": supplier, "fields": {
                "po": [{"value": po}], "revision": [{"value": rev, "quote": quote, "citation": cite}],
                "items": [{"value": {"material": code, "quantity": qty}}]}}
        docs = [doc("SUP-A", "1", "PR-SL-0604", 64000, "Artwork PR-SL-0604: rev. B (x_revB.pdf)", "B"),
                doc("SUP-B", "2", "STATUE", 50000, "STATUE: druk wg pliku rev. C", "C")]
        pos = [{"po_number": "1", "material_id": "STATUE", "supplier_id": "SUP-A", "quantity": 64000, "status": "open"},
               {"po_number": "2", "material_id": "STATUE", "supplier_id": "SUP-B", "quantity": 50000, "status": "open"}]
        grs = [{"material_id": "STATUE", "supplier_id": "SUP-B", "qty_received": 7000}]
        result = evaluate(truth(), docs, po_rows=pos, gr_rows=grs)["parts"]["STATUE"]
        self.assertEqual(result["status"], "HUMAN")
        self.assertIn("rev B at SUP-A (0 pcs delivered, 64,000 open)", result["reasons"][0])
        self.assertIn("rev C at SUP-B (7,000 pcs delivered, 50,000 open)", result["reasons"][0])
        self.assertEqual(len(result["evidence"]), 2)
        docs[1]["fields"]["revision"][0]["value"] = "B"
        self.assertEqual(evaluate(truth(), docs, po_rows=pos, gr_rows=grs)["parts"]["STATUE"]["status"], "GO")


if __name__ == "__main__":
    unittest.main()
