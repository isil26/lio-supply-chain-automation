"""Offline end-to-end rehearsal using the team's downloaded portal files."""

from contextlib import contextmanager
import http.client
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic, sleep
import unittest


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = "/api/dashboard"
SCHEMA = {"launch", "readiness", "risks", "activity", "threads", "approval", "options", "drop"}
# Frozen expectations from docs/NUMBERS.md (post-drop for the component gaps).
TARGETS = {"STD": 640_000, "CE": 72_000}
GAPS = {"CMP-GAM-001": 6_800, "CMP-GAM-008": 5_900, "CMP-GAM-010": 3_400}


@contextmanager
def timed(step):
    started = monotonic()
    try:
        yield
    finally:
        print(f"{step} ({monotonic() - started:.2f}s)", flush=True)


def stop(process):
    if process.poll() is not None:
        return
    # Stop any OCR subprocesses along with the API before deleting its workspace.
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    except ProcessLookupError:
        process.wait()


class DemoReplayTest(unittest.TestCase):
    def request(self, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            if body is None:
                connection.request("GET", path)
            else:
                connection.request("POST", path, json.dumps(body), {"Content-Type": "application/json"})
            response = connection.getresponse()
            return response.status, json.load(response)
        finally:
            connection.close()

    def dashboard(self, ready, starting=False):
        deadline = monotonic() + self.timeout
        last_status = "server not accepting connections"
        while monotonic() < deadline:
            if self.process.poll() is not None:
                self.fail(f"Replay server exited with code {self.process.returncode}")
            try:
                status, snapshot = self.request(DASHBOARD)
            except (OSError, http.client.HTTPException):
                sleep(0.25)
                continue
            last_status = f"HTTP {status}"
            self.assertIn(status, {200, 503}, "Unexpected dashboard response")
            sync = snapshot.get("sync") or {}
            if sync.get("error"):
                if not (starting and status == 503 and sync["error"] == "database is locked"):
                    self.fail("Replay pipeline reported a sync error. Check the local server console.")
                last_status = "HTTP 503, startup database lock"
            elif status == 200 and ready(snapshot, sync):
                return snapshot
            sleep(0.25)
        self.fail(f"Dashboard did not reach the expected state in {self.timeout:g}s ({last_status})")

    def assert_targets(self, snapshot):
        self.assertEqual({row["edition"]: row["target"] for row in snapshot["readiness"]}, TARGETS)

    def test_offline_demo(self):
        with timed("Prepare workspace and start replay"):
            # Keep the app's repo-relative replay database, copied inputs and caches disposable.
            workspace = TemporaryDirectory(prefix="soony-e2e-")
            self.addCleanup(workspace.cleanup)
            self._start_replay(Path(workspace.name))
        self._exercise_replay()

    def _start_replay(self, workspace):
        default_data = ROOT / "data" if (ROOT / "data").is_dir() else ROOT / "case-data"
        data = Path(os.environ.get("DEMO_DATA_DIR", default_data)).resolve()
        self.assertTrue(data.is_dir(), "Local portal mirror missing. Restore it or set DEMO_DATA_DIR.")
        self.timeout = float(os.environ.get("DEMO_TIMEOUT_SECONDS", "240"))
        self.assertTrue(0 < self.timeout < float("inf"), "DEMO_TIMEOUT_SECONDS must be positive and finite")
        for directory in ("src", "bridge", "config"):
            shutil.copytree(ROOT / directory, workspace / directory,
                            ignore=shutil.ignore_patterns("__pycache__", ".soony_token", "state.json", "changes.log"))
        (workspace / "docs").mkdir()
        shutil.copyfile(ROOT / "docs" / "delegations.json", workspace / "docs" / "delegations.json")
        for relative in ("store/docs_cache.sqlite3", "runtime/tessdata"):
            source = ROOT / relative
            if source.exists():
                link = workspace / relative
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(source, target_is_directory=source.is_dir())

        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("CHASER_", "SOONY_IMAP_", "SOONY_LLM_"))
               and key not in {"SOONY_TOKEN", "SOONY_LOCAL_MODEL", "SOONY_VISION_MODEL", "PYTHONPATH"}}
        env.update(CHASER_REAL_SMTP="0", CHASER_NO_TEAM_MAIL="1", SOONY_LLM_PROVIDER="none", SOONY_AGENTS="0")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.process = subprocess.Popen(
            [sys.executable, "-m", "src.orchestrator", "--demo", "--port", str(self.port), "--data", str(data)],
            cwd=workspace, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
        self.addCleanup(stop, self.process)

    def _exercise_replay(self):
        with timed("Wait for baseline dashboard (HTTP 200)"):
            baseline = self.dashboard(lambda snapshot, sync: "pendingDrop" in sync, starting=True)

        with timed("Check dashboard schema, targets and staged drop"):
            self.assertEqual(SCHEMA - baseline.keys(), set(), "Dashboard keys missing")
            self.assert_targets(baseline)
            self.assertEqual(baseline["sync"]["mode"], "replay")
            self.assertEqual(baseline["sync"]["mailMode"], "dry-run")
            self.assertGreater(baseline["sync"]["pendingDrop"], 0, "No supplier files staged. Check the local mirror.")

        with timed("Release staged drop (POST /api/sync)"):
            status, result = self.request("/api/sync", {})
            self.assertEqual(status, 202)
            self.assertIs(result.get("ok"), True)

        with timed("Wait for replay banner and verify changed risks or options"):
            updated = self.dashboard(lambda snapshot, sync: sync.get("pendingDrop") == 0)
            drop = updated["drop"] or {}
            self.assertEqual(drop.get("title"), "Replayed portal drop processed")
            self.assertTrue(drop.get("detail"), "Replay banner detail missing")
            self.assertTrue(drop.get("changes"), "Replay banner has no source changes")
            self.assertTrue(
                self.risk_state(updated) != self.risk_state(baseline)
                or {option["id"] for option in updated["options"]} != {option["id"] for option in baseline["options"]},
                "The staged drop did not change any displayed risk or option",
            )

        with timed("Check post-drop NUMBERS.md invariants"):
            self.assert_targets(updated)
            gaps = {row["id"]: row["gap"] for row in updated["risks"]}
            for material, expected in GAPS.items():
                with self.subTest(material=material):
                    self.assertEqual(gaps.get(material), expected, "Post-drop component gap")

        with timed("Verify action queue review, persistence and dismissal"):
            code, result = self.request("/api/actions")
            self.assertEqual(code, 200)
            queue = result["actions"]
            self.assertEqual([row["id"] for row in queue], [row["id"] for row in updated["actions"]])
            self.assertTrue({"recovery", "release_gate", "claims"} <= {row["source"] for row in queue})
            sleeve = next(row for row in queue if row["source"] == "release_gate" and row["material"] == "CMP-GAM-004")
            self.assertEqual(sleeve["person"], "Sofia Marchetti")
            dock_action = next(row for row in queue if "provisional Hamburg dock slot" in row["title"])
            self.assertTrue(dock_action["evidence"] and dock_action["draft"]["body"])
            self.assertEqual((dock_action["mode"], dock_action["approverName"]), ("ONE_CLICK", "Katrin Jansen"))
            path = f'/api/actions/{dock_action["id"]}'
            self.assertEqual(self.request(path + "/approve", {"by": "Offline test"})[0], 403)
            actor = {"by": "Katrin Jansen"}
            status, approved = self.request(path + "/approve", actor)
            self.assertEqual((status, approved["action"]["status"]), (200, "prepared"))
            retry_status, retry = self.request(path + "/approve", actor)
            self.assertEqual((retry_status, retry["action"]["delivery"]), (status, approved["action"]["delivery"]))
            self.assertEqual(self.request(path + "/done", actor)[1]["action"]["status"], "done")
            self.assertEqual(self.request(path + "/approve", actor)[0], 409)
            review = next(row for row in queue if "Karton art-book PO" in row["title"])
            status, dismissed = self.request(f'/api/actions/{review["id"]}/dismiss', actor)
            self.assertEqual((status, dismissed["action"]["status"]), (200, "dismissed"))
            persisted = self.dashboard(lambda snapshot, sync: True)["actions"]
            self.assertEqual(next(row for row in persisted if row["id"] == review["id"])["status"], "dismissed")

        with timed("Approve a pending option and verify persisted state"):
            option = next((row for row in updated["options"] if row["status"] == "pending"), None)
            self.assertIsNotNone(option, "No actionable approval option")
            option_id = option["id"]
            status, result = self.request(f"/api/decisions/{option_id}/approve", {})
            self.assertEqual(status, 200)
            self.assertEqual(result.get("approvalId"), option_id)
            self.assertEqual(result.get("status"), "approved")
            approved = self.dashboard(lambda snapshot, sync: True)
            self.assertEqual({row["id"]: row["status"] for row in approved["options"]}.get(option_id), "approved")

        with timed("Verify automatic dry-run request on the shipment thread"):
            sent = self.dashboard(lambda snapshot, sync: any(
                a["case"] == "game_card" and a.get("transport", {}).get("status") == "dry_run"
                for a in snapshot.get("supplierActions", ())
            ))
            self.assertEqual(sent["sync"]["mailMode"], "dry-run")
            action = next(a for a in sent["supplierActions"] if a["case"] == "game_card")
            thread_id = action["threadId"]
            self.assertEqual(action["status"], "awaiting_reply")
            thread = next(row for row in sent["threads"] if row["id"] == thread_id)
            self.assertEqual(thread["status"], "awaiting reply")
            self.assertTrue(any(message["side"] == "out" and message["sender"] == "Supplier Chaser (demo)"
                                for message in thread["messages"]), "Dry-run message missing from thread")

        with timed("Recalculate a shipment scenario from a supplier reply"):
            status, received = self.request(f"/api/threads/{thread_id}/demo-reply", {})
            self.assertEqual((status, received.get("ok")), (200, True))
            reply = self.dashboard(lambda snapshot, sync: True)
            thread = next(row for row in reply["threads"] if row["id"] == thread_id)
            self.assertEqual(thread["status"], "reply to verify")
            outbound, incoming = thread["messages"][-2:]
            self.assertEqual(outbound["transport"]["status"], "dry_run")
            self.assertEqual(incoming["transport"]["mode"], "simulated")
            self.assertEqual(incoming["transport"]["inReplyTo"], outbound["transport"]["messageId"])
            plan = incoming["parsed"]["reply_plan"]
            self.assertTrue(plan["simulated"])
            self.assertTrue(plan["evidence"])
            self.assertIn("Escalate", plan["nextAction"])
            recovery = next(row for row in reply["supplierActions"] if row["case"] == "game_card")
            self.assertEqual(recovery["kind"], "review_recovery")
            self.assertNotIn(dock_action["id"], {row["id"] for row in reply["actions"]})
            self.assertTrue(all(row["withDock"] == row["after"] for row in recovery["impact"]))
            self.assertEqual(self.request(f'/api/decisions/{recovery["optionId"]}/approve', {})[0], 409)
            self.assertEqual(reply["readiness"], sent["readiness"])
            self.assertEqual(plan["status"], "proposed")
            status, result = self.request(f'/api/reply-decisions/{incoming["id"]}/approve', {})
            self.assertEqual((status, result["status"]), (200, "approved"))
            reviewed = self.dashboard(lambda snapshot, sync: True)
            reviewed_thread = next(row for row in reviewed["threads"] if row["id"] == thread_id)
            approved = reviewed_thread["messages"][-1]["parsed"]["reply_plan"]
            self.assertEqual((approved["id"], approved["status"]), (plan["id"], "approved"))
            self.assertEqual(reviewed["readiness"], sent["readiness"])

        with timed("Link an art-book hold reply to the current offer without pricing a PO"):
            offer = next(row for row in updated["options"] if row["kind"] == "partial" and row["material"] == "CMP-GAM-008")
            art_thread = next(row for row in sent["threads"] if row["status"] == "awaiting reply"
                              and row["supplier_id"] == offer["supplier_id"] and row["material"] == offer["material"])
            art_id = art_thread["id"]
            self.assertEqual(self.request(f"/api/threads/{art_id}/demo-reply", {})[0], 200)
            art_state = self.dashboard(lambda snapshot, sync: True)
            received = next(row for row in art_state["threads"] if row["id"] == art_id)["messages"][-1]
            plan = received["parsed"]["reply_plan"]
            self.assertEqual((plan["offerId"], plan["holdUnits"]), (offer["id"], 5900))
            self.assertEqual(plan["evidence"], ["can hold 5,900", "freight price to follow"])
            self.assertIn("Delivered price pending", plan["afterState"])
            self.assertIn("PO decision remains outstanding", plan["nextAction"])
            self.assertEqual(plan["status"], "proposed")
            self.assertEqual(art_state["readiness"], updated["readiness"])

    @staticmethod
    def risk_state(snapshot):
        return {row["id"]: (row["gap"], row["inbound"], row["detail"]) for row in snapshot["risks"]}
