import unittest

from . import confirmed_shipment_receipts


class ShipmentReceiptTests(unittest.TestCase):
    lot = ("air-lot", ("supplier", "card", "po", 28_000), "2026-11-20")
    receipt = {"gr_number": "receipt", "supplier_id": "supplier", "material_id": "card",
               "po_number": "po", "qty_received": 28_000, "gr_date": "2026-11-21"}

    def match(self, lots, receipts):
        return confirmed_shipment_receipts(lots, receipts, "2026-11-22")

    def test_full_receipt_matches_one_advised_lot(self):
        self.assertEqual(self.match([self.lot], [self.receipt]), {"air-lot": self.receipt})

    def test_unrelated_partial_and_out_of_window_receipts_do_not_match(self):
        for mismatch in ({"po_number": "other"}, {"supplier_id": "other"}, {"material_id": "other"},
                         {"qty_received": 14_000}, {"gr_date": "2026-11-19"}, {"gr_date": "2026-11-23"}):
            with self.subTest(mismatch=mismatch):
                self.assertEqual(self.match([self.lot], [self.receipt | mismatch]), {})

    def test_ambiguous_lots_or_receipts_stay_unmatched(self):
        duplicate_lot = ("another-lot", *self.lot[1:])
        duplicate_receipt = self.receipt | {"gr_number": "another-receipt"}
        self.assertEqual(self.match([self.lot, duplicate_lot], [self.receipt]), {})
        self.assertEqual(self.match([self.lot], [self.receipt, duplicate_receipt]), {})
