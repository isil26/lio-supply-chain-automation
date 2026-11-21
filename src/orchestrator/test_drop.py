import unittest

from .__main__ import drop_summary


class DropSummaryTest(unittest.TestCase):
    def test_new_risks_and_recovery_appear_even_when_shortfall_improves(self):
        known_hold = {"kind": "quality_hold", "title": "Existing lot hold"}
        short_shipment = {"kind": "short_ship", "title": "Only part of the shipment flew"}
        new_hold = {"kind": "dock_hold", "title": "Alternate supplier shipment on hold"}
        previous = {"issues": [known_hold], "parts": {"CARD": {"shortfall": 100}}}
        current = {
            "issues": [known_hold, short_shipment, short_shipment, new_hold],
            "parts": {"CARD": {"shortfall": 20}},
        }
        known_option = {"id": "old", "title": "Request quality review", "material": "STATUE"}
        repriced_option = dict(known_option, id="revised", price=15)
        new_option = {"id": "new", "title": "Reserve finished stock", "material": "BOOK"}

        summary = drop_summary(previous, current, [known_option], [repriced_option, new_option])

        self.assertEqual(
            summary,
            "Only part of the shipment flew · Alternate supplier shipment on hold"
            " · New option: Reserve finished stock · CARD: 100 to 20 short",
        )

    def test_unchanged_snapshot_has_no_updates(self):
        snapshot = {
            "issues": [{"kind": "short_ship", "title": "Only part of the shipment flew"}],
            "parts": {"CARD": {"shortfall": 20}},
        }
        self.assertEqual(drop_summary(snapshot, snapshot, [], []), "")
