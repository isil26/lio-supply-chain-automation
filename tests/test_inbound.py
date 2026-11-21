"""T67: inbound expedite options and the handling_hours what-if."""
from copy import deepcopy
import unittest
from unittest import mock

from src.decide import inbound
from src.truth.sensitivity import counterfactual

START = "2026-01-10T08:00:00+01:00"
END = "2026-01-10T12:00:00+01:00"
LANDS = "2026-01-10T07:00:00+01:00"  # +6 h default handling misses the shift, +4 h makes it
AFTER = "2026-01-10T13:00:00+01:00"

POLICY_QUOTE = ("3. Receiving site\nPOs delivered to a Soony site require a booked dock slot released by the site\nlead.\n"
                "Site            Site lead          Deputy\nDC-HAM Hamburg  Katrin Jansen      Raj Patel")
DOCS = [{"source": inbound.POLICY, "fields": {"policy_clause": [
    {"value": POLICY_QUOTE, "citation": {"file": inbound.POLICY, "page": 1, "quote": POLICY_QUOTE}}]}}]
CARRIERS = [{"carrier_id": "LSP-02", "name": "Alpen Air Cargo GmbH", "source": {"file": "carriers.csv", "row": 3}}]


def fixture():
    """One 4 h shift; cards run out at once and an 8-unit air lot lands at 07:00 with 6 h handling."""
    return {
        "site": "DC-HAM", "deadline": END,
        "editions": {"FG-STD": {"edition": "Standard", "target": 8, "packed": 0, "rate": 4}},
        "parts": {"card": {"material": "card", "label": "Game Card – X", "on_hand": 0, "shortfall": 8,
                           "unit_usage": {"FG-STD": 1}, "embedded_in": None}},
        "shifts": [[START, END]],
        "inbound": [
            {"id": "AIR", "reference": "020-1", "mode": "air", "material": "card", "quantity": 8,
             "supplier": "SUP-1", "held": False, "earliest": LANDS, "evidence": [{"file": "ship.csv", "row": 2}]},
            {"id": "HELD", "reference": "020-2", "mode": "air", "material": "card", "quantity": 8,
             "supplier": "SUP-1", "held": True, "earliest": LANDS, "evidence": []},
            {"id": "LATE", "reference": "020-3", "mode": "air", "material": "card", "quantity": 8,
             "supplier": "SUP-1", "held": False, "earliest": AFTER, "evidence": []},
        ],
        "model": {"runs": 20, "lag_hours": {"air": (6, 6, 6)}},
    }


def run(truth, status="booked"):
    shipments = {sid: {"shipment_id": sid, "carrier_id": "LSP-02", "status": status, "note": None,
                       "source": {"file": "erp/open_shipments.csv"}} for sid in ("AIR", "HELD", "LATE")}
    with mock.patch.object(inbound, "_shipment_rows", return_value=shipments), \
            mock.patch.object(inbound, "rows", return_value=CARRIERS):
        return inbound.inbound_options(None, truth, DOCS, trials=20)


class HandlingHoursTests(unittest.TestCase):
    def test_cap_moves_late_handled_lot_into_the_shift(self):
        truth = fixture()
        base = counterfactual(truth, {}, trials=20)["editions"]["FG-STD"]
        capped = counterfactual(truth, {"handling_hours": {"AIR": 1}}, trials=20)["editions"]["FG-STD"]
        self.assertEqual(base["p50"], 0)
        self.assertGreater(capped["p50"], 0)

    def test_cap_never_adds_delay(self):
        truth = fixture()
        truth["model"]["lag_hours"]["air"] = (0, 0, 0)
        base = counterfactual(truth, {}, trials=20)
        self.assertEqual(counterfactual(truth, {"handling_hours": {"AIR": 3}}, trials=20), base)

    def test_rejects_negative_and_unknown(self):
        with self.assertRaises(ValueError):
            counterfactual(fixture(), {"handling_hours": {"AIR": -1}}, trials=5)
        with self.assertRaises(ValueError):
            counterfactual(fixture(), {"handling_hours": {"NOPE": 1}}, trials=5)


class InboundOptionTests(unittest.TestCase):
    def test_site_lead_from_policy(self):
        lead, deputy, citation = inbound.site_lead(DOCS, "DC-HAM")
        self.assertEqual((lead, deputy, citation["page"]), ("Katrin Jansen", "Raj Patel", 1))

    def test_proposes_only_the_landing_unheld_lot(self):
        options = run(fixture())
        self.assertEqual([o["shipment_id"] for o in options], ["AIR"])
        option = options[0]
        self.assertEqual(option["owner"], "Katrin Jansen")
        self.assertTrue(option["request_only"])
        self.assertIsNone(option["price"])
        self.assertGreater(option["modeled_impact"]["FG-STD"]["medianDelta"], 0)
        self.assertIn("Alpen Air Cargo GmbH", option["draft"]["to"])
        self.assertIn("pre-clear customs", option["recommendation"])
        self.assertIn("carriers.csv", [e["file"] for e in option["evidence"]])

    def test_landed_lot_gets_pickup_wording(self):
        options = run(fixture(), status="arrived_port")
        self.assertTrue(options[0]["title"].startswith("Book pickup"))

    def test_no_option_when_handling_does_not_matter(self):
        truth = deepcopy(fixture())
        truth["model"]["lag_hours"]["air"] = (0, 0, 0)
        self.assertEqual(run(truth), [])

    def test_no_shifts_no_options(self):
        truth = fixture()
        truth["shifts"] = []
        self.assertEqual(run(truth), [])


class CustomsDocumentsDraftTests(unittest.TestCase):
    def setUp(self):
        import sqlite3
        from src import chaser
        self.chaser = chaser
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.execute("CREATE TABLE suppliers (supplier_id, name, contact_name, contact_email, preferred_language)")
        self.con.execute("INSERT INTO suppliers VALUES ('SUP-1', 'Hwaseong Memory', 'Seo-yeon Kim', "
                         "'sy.kim@suppliers.juliansibbing.de', 'ko')")
        chaser.schema(self.con)
        self.truth = fixture()
        self.options = run(self.truth)

    def tearDown(self):
        self.con.close()

    def chases(self):
        return [dict(row) for row in self.con.execute("SELECT * FROM chases")]

    def test_drafts_one_korean_request_for_the_air_lot(self):
        self.assertEqual(self.chaser.draft_documents(self.con, self.truth, self.options), 1)
        [chase] = self.chases()
        self.assertEqual((chase["status"], chase["language"], chase["qty"]), ("draft", "ko", 8))
        self.assertEqual(chase["address"], "sy.kim@suppliers.juliansibbing.de")
        self.assertIn("020-1", chase["subject"])
        self.assertIn("상업송장", chase["body"])
        self.assertIn("8개", chase["body"])

    def test_redrafting_is_idempotent(self):
        self.chaser.draft_documents(self.con, self.truth, self.options)
        self.assertEqual(self.chaser.draft_documents(self.con, self.truth, self.options), 0)
        self.assertEqual(len(self.chases()), 1)

    def test_skips_other_options_and_non_air_lots(self):
        self.assertEqual(self.chaser.draft_documents(self.con, self.truth, [{"kind": "air", "shipment_id": "AIR"}]), 0)
        self.truth["inbound"][0]["mode"] = "sea"
        self.assertEqual(self.chaser.draft_documents(self.con, self.truth, self.options), 0)

    def test_real_send_stays_on_the_supplier_allowlist(self):
        self.chaser.draft_documents(self.con, self.truth, self.options)
        from src.chaser.allowlist import check_recipient
        self.assertEqual(check_recipient(self.chases()[0]["address"]), "sy.kim@suppliers.juliansibbing.de")


if __name__ == "__main__":
    unittest.main()
