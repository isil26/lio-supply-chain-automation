"""Exercise the Plan B card against an uncertain existing shipment."""

import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.decide import choose
from src.ingest.run import create_schema
from src.ingest.store import connect
from src.truth import MODEL_RUNS, simulate


class OfferForecastTest(unittest.TestCase):
    def card_impact(self, load_hours):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(hours=8)
        edition_id = "DEMO-CE"
        editions = {edition_id: {
            "edition": "Collector’s Edition", "packed": 0, "target": 100,
            "remaining": 100, "rate": 20, "evidence": [],
        }}
        original = {
            "id": "original", "earliest": start + timedelta(minutes=22),
            "held": False, "quantity": 1000, "material": "PART", "mode": "road",
        }
        editions[edition_id].update(
            simulate(editions, {edition_id: {"PART": 1}}, {"PART": 0}, [original], [(start, end)])[edition_id]
        )
        truth = {
            "deadline": end.isoformat(),
            "shifts": [(start.isoformat(), end.isoformat())],
            "editions": editions,
            "parts": {"PART": {
                "material": "PART", "label": "Book", "shortfall": 100,
                "on_hand": 0, "unit_usage": {edition_id: 1}, "embedded_in": None, "evidence": [],
                "suppliers": [{
                    "supplier_id": "SUP-TEST", "supplier": {"name": "Test Supplier"},
                    "unit_price": 2.0, "currency": "EUR", "primary": True, "source": {},
                }],
            }},
            "inbound": [dict(original, earliest=original["earliest"].isoformat())],
            "issues": [],
            "model": {"runs": MODEL_RUNS},
        }
        source = "suppliers/SUP-TEST/notices/stock-offer.pdf"
        doc = {"source": source, "fields": {
            "available_offer": [{
                "value": {"material": "PART", "quantity": 100, "load_hours": load_hours},
                "citation": {"file": source, "page": 1},
            }],
            "road_hours": [{"value": 1, "citation": {"file": source, "page": 1}}],
        }}
        with TemporaryDirectory() as temp, closing(connect(Path(temp) / "store.db")) as con:
            create_schema(con)
            with patch("src.decide.documents", return_value=[doc]):
                card = next(option for option in choose(con, truth) if option["kind"] == "partial")
        self.assertEqual(card["supplier_timing"]["eta_p50"], (start + timedelta(hours=load_hours + 1)).isoformat())
        self.assertEqual(card["expedite"]["readiness_scope"], editions[edition_id]["edition"])
        self.assertIsNone(card["expedite"]["loss_per_copy_eur"])
        impact = card["modeled_impact"][edition_id]
        wait, express = card["expedite"]["options"]
        self.assertEqual(wait["p_on_time"], impact["baselineProbability"])
        self.assertEqual(express["p_on_time"], impact["scenarioProbability"])
        return impact

    def test_offer_arriving_a_day_after_the_last_shift_has_zero_benefit(self):
        # 31 hours loading + 1 hour driving leaves the offer 24 hours past the shift.
        impact = self.card_impact(load_hours=31)
        self.assertEqual(impact["medianDelta"], 0)
        self.assertEqual(impact["scenarioProbability"], impact["baselineProbability"])

    def test_offer_within_the_shift_can_improve_packing(self):
        impact = self.card_impact(load_hours=0)
        self.assertGreater(impact["medianDelta"], 0)
        self.assertGreater(impact["scenarioProbability"], impact["baselineProbability"])
