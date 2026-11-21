import unittest

from src.decide.release_gate import evaluate, load_drop


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


def sleeve_truth(on_hand=186000):
    return {"deadline": "2026-11-22T20:00:00+01:00",
            "parts": {"SLV": {"material": "SLV", "label": "Sleeve", "required": 128000, "on_hand": on_hand,
                              "suppliers": [], "unit_usage": {"STD": 1}, "evidence": []}},
            "editions": {"STD": {"edition": "Standard", "remaining": 128000}}, "issues": []}


def conf(supplier, po, rev, qty):
    quote = f"SLV: rev. {rev}"
    return {"kind": "confirmation", "supplier_id": supplier, "fields": {
        "po": [{"value": po}], "revision": [{"value": rev, "quote": quote,
                                             "citation": {"file": f"{supplier}.pdf", "page": 1, "quote": quote}}],
        "items": [{"value": {"material": "SLV", "quantity": qty}}]}}


ECN = [{"change_id": "ECN-1", "child_id": "SLV", "action": "revision", "rev_old": "B", "rev_new": "C",
        "use_up_old_rev": "N", "effective_from": "2026-11-21", "reason": "parts to rev B must not be packed",
        "_src": {"file": "bom_delta.csv", "row": 2}},
       {"change_id": "ECN-2", "child_id": "POSTER", "action": "revision", "rev_old": "A", "rev_new": "B",
        "use_up_old_rev": "Y", "effective_from": "2026-11-21", "reason": "use up rev A",
        "_src": {"file": "bom_delta.csv", "row": 3}}]


class ReleaseGateV2Tests(unittest.TestCase):
    def test_ecn_rev_b_lot_hold_and_usable_rev_c(self):
        docs = [conf("PR", "1", "B", 64000), conf("KN", "2", "C", 50000)]
        pos = [{"po_number": "1", "material_id": "SLV", "supplier_id": "PR", "quantity": 675000, "status": "open"},
               {"po_number": "2", "material_id": "SLV", "supplier_id": "KN", "quantity": 50000, "status": "open"}]
        grs = [{"material_id": "SLV", "supplier_id": "PR", "qty_received": 64000}]
        gate = evaluate(sleeve_truth(), docs, po_rows=pos, gr_rows=grs, drop={"bom_delta": ECN})
        part = gate["parts"]["SLV"]
        self.assertEqual(part["status"], "HOLD")
        self.assertEqual((part["held_quantity"], part["go_quantity"], part["do_not_accept_quantity"]),
                         (64000, 122000, 675000))
        self.assertEqual(part["required_human_action"]["decisions"][0]["name"], "Sofia Marchetti")
        self.assertNotIn("Marketing must confirm", part["reasons"][0])
        self.assertEqual(part["evidence"][0]["file"], "bom_delta.csv")
        self.assertEqual(gate["editions"]["STD"]["units_with_go_parts"], 122000)

    def test_use_up_old_revision_is_go_with_note(self):
        truth_ = {"deadline": "2026-11-22", "parts": {"POSTER": {"required": 5, "on_hand": 9, "unit_usage": {"CE": 1}}},
                  "editions": {"CE": {"remaining": 5}}, "issues": []}
        part = evaluate(truth_, drop={"bom_delta": ECN})["parts"]["POSTER"]
        self.assertEqual(part["status"], "GO")
        self.assertIn("may still be packed", part["reasons"][0])

    def test_critical_statue_needs_quality_and_pune_expired(self):
        drop = {"component_updates": [{"component_id": "STATUE", "field": "critical", "old": "N", "new": "Y",
                                       "changed_by": "Mei Lin", "_src": {"file": "cu.csv", "row": 4}}],
                "profiles": {"SUP-P": {"name": "Pune", "qualification": {
                    "status": "conditional", "releasedOn": "2026-08-01", "validUntil": "2026-10-30", "extendedBy": None},
                    "source": {"file": "profile.json", "row": 28, "quote": "validUntil"}}},
                "org_category_lead_from": "2026-11-23"}
        base = truth({"material": "STATUE", "kind": "quality_hold", "quantity": 4, "title": "failed", "evidence": [SOURCE]})
        base["parts"]["STATUE"]["suppliers"] = [{"supplier_id": "SUP-P", "source": {"file": "c.csv", "row": 2}}]
        part = evaluate(base, drop=drop)["parts"]["STATUE"]
        text = " ".join(part["reasons"])
        self.assertEqual(part["status"], "HOLD")
        self.assertEqual(part["go_quantity"], 0)
        self.assertIn("CRITICAL", text)
        self.assertIn("EXPIRED on 2026-10-30", text)
        self.assertIn("Dr. Maren Vogt", text)
        self.assertIn("Daniel Okafor", text)
        self.assertEqual(part["required_authority"]["name"], "Clara Weiss")
        self.assertTrue(any("Quality & Compliance" in c.get("quote", "") for c in part["evidence"]))
        drop["profiles"]["SUP-P"]["qualification"]["extendedBy"] = "Sofia"
        self.assertNotIn("EXPIRED", " ".join(evaluate(base, drop=drop)["parts"]["STATUE"]["reasons"]))

    def test_load_drop_reads_real_files(self):
        from src.ingest.store import ROOT
        drop = load_drop(ROOT / "data")
        if drop["bom_delta"]:
            self.assertEqual(drop["bom_delta"][0]["change_id"], "ECN-2026-118")
            self.assertEqual(drop["bom_delta"][0]["_src"]["row"], 2)
        self.assertEqual(load_drop("/nonexistent")["bom_delta"], [])


if __name__ == "__main__":
    unittest.main()
