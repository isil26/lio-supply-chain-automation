import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from recording import DEFAULT_RECORDING, load_recording


class HostedRecordingTests(unittest.TestCase):
    def project(self, manifest):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "recording.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            return load_recording(path)

    def test_reported_summary_does_not_invent_events_or_approvals(self):
        result = load_recording(DEFAULT_RECORDING)
        self.assertEqual(result["coverage"], "summary_only")
        self.assertEqual(result["reported_summary"]["aggregate_usage"]["cost_usd"], .057892)
        self.assertTrue(result["reported_summary"]["pending_approvals_reported"])
        self.assertFalse(result["reported_summary"]["supplier_email_sent_reported"])
        self.assertEqual(result["events"], [])
        self.assertIsNone(result["approvals_pending"])
        self.assertIsNone(result["timing"]["duration_ms"])
        self.assertNotIn("web/public/snapshot/agent_run.json", [source["path"] for source in result["sources"]])

    def test_events_keep_observed_values_and_omit_raw_content(self):
        manifest = json.loads(DEFAULT_RECORDING.read_text(encoding="utf-8"))
        manifest.update(coverage="verified_events", run_id="synthetic-check", verified_event_count=2,
                        approvals_verified=True, approvals_pending=[{"id": "approval-1", "title": "Review quote"}])
        manifest["sources"].append({"kind": "redacted_trace_export", "path": "docs/agent_runs/example.json",
                                    "revision": "1" * 40, "sha256": "2" * 64})
        manifest["steps"] = [{"sequence": 2, "agent": "analyst", "tool": "get_document", "status": "completed",
                              "latency_ms": 234, "cost_usd": 0.0, "reason": "private raw data"}]
        manifest["verified_handoffs"] = [{"sequence": 1, "agent": "triage", "target": "analyst", "status": "completed"}]
        result = self.project(manifest)
        handoff, tool = result["events"]
        self.assertEqual(handoff["target"], "analyst")
        self.assertIsNone(handoff["latency_ms"])
        self.assertEqual((tool["tool"], tool["latency_ms"], tool["cost_usd"]), ("get_document", 234, 0.0))
        self.assertNotIn("private raw data", json.dumps(result))
        self.assertIsNone(result["verified_usage"])
        self.assertEqual(result["approvals_pending"][0]["title"], "Review quote")
        manifest["steps"][0]["tool"] = "recorded_run"
        with self.assertRaisesRegex(ValueError, "operational events"):
            self.project(manifest)
