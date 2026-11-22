import unittest

from .portal_update import portal_baseline, portal_update


class PortalUpdateTest(unittest.TestCase):
    def setUp(self):
        self.source = {"file": "soony/erp/goods_receipts_update.csv", "row": 4}
        self.issue = {"kind": "shipment_received", "quantity": 28000, "material": "CMP-GAM-001",
                      "shipment": "flight", "evidence": [self.source]}
        self.truth = {"issues": [self.issue], "parts": {"CMP-GAM-001": {"label": "Game card", "shortfall": 6800}},
                      "editions": {"STD": {"edition": "Standard", "p50": 639100}}}
        self.drop = {"source": "portal", "changes": [{"file": self.source["file"], "action": "added"}],
                     "detail": "Standard median forecast: 614,650 → 630,500 · CMP-GAM-001: 6,800 to 0 short"}
        self.option = {"material": "CMP-GAM-001", "status": "pending", "id": "boise", "title": "Check Boise stock",
                       "approvalMode": {"mode": "ONE_CLICK"}}

    def display(self, actions=()):
        return portal_update(self.drop, self.truth, actions, "Hamburg")

    def test_saved_drop_projects_receipt_current_gap_and_current_forecast(self):
        result = self.display([dict(self.option, status="approved"), self.option])
        self.assertEqual(result["receipts"], [{
            "headline": "Hamburg received 28,000 game cards.", "balance": "The launch still needs 6,800 more.",
            "action": {"id": "boise", "title": "Check Boise stock"}, "evidence": self.source}])
        self.assertEqual(result["forecasts"], ["The Standard forecast is 639,100 copies (614,650 before this update)."])
        self.assertNotIn("630,500", result["detail"])
        self.assertNotIn("to 0 short", result["detail"])
        self.truth["parts"]["CMP-GAM-001"]["shortfall"] = 0
        self.assertIsNone(self.display([self.option])["receipts"][0]["action"])
        self.assertIn("covers the full launch requirement", self.display()["detail"])

    def test_changed_export_confirms_only_newly_matched_receipts(self):
        self.drop["changes"][0]["action"] = "changed"
        self.assertFalse(self.display()["receipts"])
        before = dict(self.truth, issues=[], editions={"STD": {"p50": 600000}})
        self.drop.update(portal_baseline(before, self.truth))
        self.assertIn("600,000 before this update", self.display()["detail"])
        self.assertEqual(len(self.display()["receipts"]), 1)
        self.drop.update(portal_baseline(self.truth, self.truth))
        self.assertFalse(self.display()["receipts"])

    def test_unrelated_drop_and_replay(self):
        self.drop["changes"] = [{"file": "supplier-notice.pdf", "action": "added"}]
        self.assertFalse(self.display()["receipts"])
        self.drop["source"] = "replay"
        self.assertIs(self.display(), self.drop)
