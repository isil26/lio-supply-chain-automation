import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from . import __main__ as orchestrator
from .__main__ import drop_summary, handler


class DropSummaryTest(unittest.TestCase):
    def test_health_endpoint_reports_cycle_and_lock_metrics(self):
        with TemporaryDirectory() as folder:
            database = Path(folder) / "health.db"
            with closing(orchestrator.connect(database)):
                pass
            loop = SimpleNamespace(
                database=database,
                health={
                    "lastCycleTime": "2026-11-21T15:43:36+00:00",
                    "durationMs": 125,
                    "lockWaitMs": 7,
                    "errors": [],
                },
            )
            handler_class = handler(loop)
            request = object.__new__(handler_class)
            request.headers = SimpleNamespace(
                get=lambda name, default=None: "127.0.0.1" if name == "Host" else default
            )
            request.path = "/api/health"
            responses = []
            request.out = lambda payload, status=200: responses.append((payload, status))
            request.do_GET()
            payload = responses[0][0]
            self.assertEqual(payload["duration_ms"], 125)
            self.assertEqual(payload["lock_wait_ms"], 7)
            self.assertIn("dataHealth", payload)

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

    def test_dashboard_state_cannot_mix_two_replay_snapshots(self):
        with TemporaryDirectory() as folder:
            database = Path(folder) / "demo.db"
            truth = {
                "name": "Launch", "deadline": "2026-11-22T20:00:00+01:00", "site": "DC",
                "parts": {}, "editions": {}, "issues": [], "model": {}, "data_quality": {},
            }

            def publish(name, pending):
                with closing(orchestrator.connect(database)) as writer, writer:
                    orchestrator.save_state(writer, "truth", dict(truth, name=name))
                    orchestrator.save_state(writer, "options", [{"id": name}])
                    orchestrator.save_state(writer, "drop", {"title": name})
                    orchestrator.save_state(writer, "sync", {"pendingDrop": pending})

            def publish_during_render(*_, **_kwargs):
                publish("Updated", 0)
                return []

            publish("Baseline", 2)
            with closing(orchestrator.connect(database)) as reader:
                with patch.object(orchestrator, "dashboard_activity", side_effect=publish_during_render):
                    snapshot = orchestrator.dashboard(reader)
                self.assertEqual(snapshot["approval"]["id"], "Baseline")
                self.assertEqual(snapshot["drop"]["title"], "Baseline")
                self.assertEqual(snapshot["sync"]["pendingDrop"], 2)
                self.assertEqual(orchestrator.dashboard(reader)["approval"]["id"], "Updated")
