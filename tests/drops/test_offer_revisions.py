"""Exercise offer revisions through the ordinary ingest-to-dashboard refresh."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from audit_drops import SUP, pdf
from test_drops import Mirror, PART, PRODUCT, offline_environment


class SupplierOfferRevisionTests(unittest.TestCase):
    def notice(self, mirror, name, offer_id, revision, quantity, previous=None):
        path = mirror.path(f"{SUP}/notices/{name}")
        statement = f"Revision {revision} supersedes revision {previous} of offer {offer_id} in full." if previous else "Available stock."
        pdf(path, "Test Supplier, SUP-9001", f"Offer {offer_id}, revision {revision}", statement,
            f"{PART} finished stock {quantity} pcs, loaded within {35 if previous else 1} h.", "Road transfer is about 2 h driving.")
        return path

    def partials(self, dashboard):
        return [(item["full_lot_units"], Path(item["evidence"][0]["file"]).name, item["evidence"][0]["page"])
                for item in dashboard["options"] if item["kind"] == "partial"]

    def assert_baseline(self, truth):
        part = truth["parts"][PART]
        self.assertEqual((part["on_hand"], part["shortfall"], truth["editions"][PRODUCT]["p50"]), (10, 45, 55))

    def test_explicit_revision_and_old_resend_preserve_forecast_and_concurrent_quote(self):
        for order in ("AB", "BA"):
            for original_name, correction_name in (("10-a.pdf", "20-b.pdf"), ("90-a.pdf", "20-b.pdf")):
                with self.subTest(order=order, original=original_name), offline_environment(), TemporaryDirectory() as folder:
                    mirror = Mirror(folder)
                    mirror.stock("2026-11-20", [("LOT-A", 10)])
                    initial_gap = mirror.refresh()[1]
                    self.assert_baseline(initial_gap)
                    revisions = {"A": (original_name, "Q-17", "A", 30, None),
                                 "B": (correction_name, "Q-17", "B", 10, "A")}
                    files = {}
                    for index, revision in enumerate(order):
                        files[revision] = self.notice(mirror, *revisions[revision])
                        dashboard, truth, _, _ = mirror.refresh()
                        expected = [(30, original_name, 1)] if index == 0 and revision == "A" else [(10, correction_name, 1)]
                        self.assertEqual(self.partials(dashboard), expected)
                        self.assert_baseline(truth)
                    current = dashboard["approval"]
                    self.assertEqual(current["full_lot_units"], 10)
                    self.assertTrue(any("supersedes revision A" in item.get("quote", "") for item in current["evidence"]))
                    self.assertIsNotNone(current["supplier_timing"])
                    self.assertTrue(current["request_only"])
                    self.assertEqual(current["price"], 20)
                    self.assertIn("37 h loading + driving", current["impact"])
                    forecast = current["modeled_impact"][PRODUCT]
                    self.assertEqual(forecast["medianDelta"], 0)
                    self.assertEqual(forecast["scenarioProbability"], forecast["baselineProbability"])
                    self.assertEqual(current["expedite"]["thresholds"][0]["probability_gain"], 0)
                    mirror.put(f"{SUP}/notices/00-resent-a.pdf", files["A"].read_bytes())
                    self.notice(mirror, "30-concurrent.pdf", "Q-18", "A", 17)
                    dashboard, truth, documents, _ = mirror.refresh()
                    self.assertEqual(self.partials(dashboard), [(10, correction_name, 1), (17, "30-concurrent.pdf", 1)])
                    self.assertEqual(dashboard["approval"]["id"], current["id"])
                    independent = next(item for item in dashboard["options"] if item.get("full_lot_units") == 17)
                    self.assertGreater(independent["modeled_impact"][PRODUCT]["medianDelta"], 0)
                    self.assert_baseline(truth)
                    audit = {Path(doc["source"]).name: doc for doc in documents if doc["kind"] == "notice"}
                    self.assertEqual(set(audit), {original_name, correction_name, "00-resent-a.pdf", "30-concurrent.pdf"})
                    self.assertEqual(audit[original_name]["sha"], audit["00-resent-a.pdf"]["sha"])
                    self.assertEqual(audit[correction_name]["fields"]["offer_supersession"][0]["citation"]["page"], 1)
                    mirror.put(f"{SUP}/notices/01-resent-b.pdf", files["B"].read_bytes())
                    dashboard, truth, documents, _ = mirror.refresh()
                    self.assertEqual(self.partials(dashboard), [(10, correction_name, 1), (17, "30-concurrent.pdf", 1)])
                    self.assertEqual(dashboard["approval"]["id"], current["id"])
                    self.assert_baseline(truth)

    def test_full_correction_without_confirmed_stock_retires_the_old_quantity(self):
        with offline_environment(), TemporaryDirectory() as folder:
            mirror = Mirror(folder)
            mirror.stock("2026-11-20", [("LOT-A", 10)])
            original = self.notice(mirror, "10-a.pdf", "Q-17", "A", 30)
            dashboard, _, _, _ = mirror.refresh()
            self.assertEqual(self.partials(dashboard), [(30, original.name, 1)])
            correction = mirror.path(f"{SUP}/notices/20-b.pdf")
            pdf(correction, "Test Supplier, SUP-9001", "Offer Q-17, revision B",
                "Revision B supersedes revision A of offer Q-17 in full.",
                "Stock quantity pending confirmation.")
            dashboard, truth, documents, _ = mirror.refresh()
            self.assertEqual(self.partials(dashboard), [])
            self.assert_baseline(truth)
            audit = {Path(doc["source"]).name: doc["fields"] for doc in documents}
            self.assertIn("available_offer", audit[original.name])
            self.assertIn("offer_supersession", audit[correction.name])

    def test_unlinked_revisions_ask_for_review_and_keep_other_offer(self):
        with offline_environment(), TemporaryDirectory() as folder:
            mirror = Mirror(folder)
            mirror.stock("2026-11-20", [("LOT-A", 10)])
            self.notice(mirror, "10-a.pdf", "Q-17", "A", 30)
            self.notice(mirror, "20-b.pdf", "Q-17", "B", 10)
            other = self.notice(mirror, "30-concurrent.pdf", "Q-18", "A", 17)
            mirror.put(f"{SUP}/notices/35-copy.pdf", other.read_bytes())
            dashboard, truth, _, _ = mirror.refresh()
            self.assertEqual(self.partials(dashboard), [(17, "30-concurrent.pdf", 1)])
            review, = [item for item in dashboard["options"] if item["kind"] == "offer_revision_review"]
            self.assertTrue(review["request_only"])
            self.assertIsNone(review["price"])
            self.assertEqual({Path(citation["file"]).name for citation in review["evidence"][:-1]}, {"10-a.pdf", "20-b.pdf"})
            self.assert_baseline(truth)
