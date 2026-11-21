"""Verify the handoff from recorded PP-07 decisions to preparation."""

import sqlite3
import unittest
from unittest.mock import patch

from src.chaser import schema
from src.decide import approvals
from src.orchestrator import action_approvals as queue


class ApprovalHandoffTest(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.addCleanup(self.con.close)
        self.con.row_factory = sqlite3.Row
        schema(self.con)

    def proposal(self, kind, amount):
        action = {
            "id": kind, "approvalKind": kind, "kind": "internal", "material": "CMP-GAM-001",
            "title": "Review the freight package", "person": "Jonas Lindqvist",
            "binding": True, "costEur": amount, "status": "pending",
            "evidence": [{"file": "case-evidence", "quote": "Verified test estimate"}],
        }
        queue.project(self.con, [action], include_history=True)
        queue.register(self.con, [action], automatic=False)
        return action

    def test_escalated_air_freight_prepares_after_cpo_click(self):
        action = self.proposal("air_freight", 250_000)
        self.assertEqual((action["mode"], action["approverName"]), (approvals.ESCALATE, "Jonas Lindqvist"))
        with self.assertRaises(PermissionError):
            queue.approve(self.con, action, "Tobias Brandt", None, demo=True)
        prepared = queue.approve(self.con, action, "Jonas Lindqvist", None, demo=True)
        self.assertEqual((prepared["status"], prepared["approved_by"]), ("prepared", "Jonas Lindqvist"))
        self.assertEqual([row["mode"] for row in approvals.log_rows(self.con, action["id"])],
                         [approvals.ESCALATE, "APPROVED"])

    def test_live_queue_ignores_a_simulated_grant(self):
        action = {
            "id": "eta", "kind": "supplier", "material": "CMP-GAM-001",
            "title": "Request delivery ETA", "status": "pending", "costEur": 0,
            "draft": {"body": "Could you confirm the delivery ETA?"},
            "evidence": ["Test acknowledgement"],
        }
        grant = {
            "id": "DEL-TEST-eta", "delegator": "Felix Brunner", "simulated": True,
            "confirmed_in_writing": True, "action_kinds": ["supplier_info_request"],
            "max_value_eur": 100, "valid_from": "2020-01-01T00:00:00+01:00",
            "valid_until": "2099-01-01T00:00:00+01:00", "conditions": {"information_only": True},
        }
        with patch.object(approvals, "load_delegations", return_value=[grant]):
            queue.project(self.con, [action], include_history=False)
            self.assertEqual(action["mode"], approvals.ONE_CLICK)
            queue.project(self.con, [action], include_history=False, demo=True)
            self.assertEqual(action["mode"], approvals.AUTO)
            with patch.object(queue.delivery, "auto_dispatch") as dispatch:
                queue.register(self.con, [action], automatic=True)
            dispatch.assert_not_called()

    def test_joint_order_remains_pending_until_both_signers_click(self):
        action = self.proposal("purchase_order", 5_000_000)
        partial = queue.approve(self.con, action, "Jonas Lindqvist", None, demo=True)
        self.assertEqual(partial, {"status": "pending", "waitingFor": ["Henrik Dahl"]})
        final = queue.approve(self.con, action, "Henrik Dahl", None, demo=True)
        self.assertEqual(final["status"], "prepared")
        approved_by = [row["approver"] for row in approvals.log_rows(self.con, action["id"])
                       if row["mode"] == "APPROVED"]
        self.assertEqual(approved_by, ["Jonas Lindqvist", "Henrik Dahl"])
