"""Regression checks for cited extraction traces, approval gates and deck numbers."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from email.message import Message
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from src import chaser
from src.decide import ORG, POLICY, authorize, ppap_block, waiting_exposure
from src.docs.parsers import context
from src.docs.schema import Facts
from src.docs.store import load_table
from src.ingest.store import connect, ingest, save_state
from src.orchestrator.__main__ import dashboard_activity, handler
from src.orchestrator.numbers import numbers_report
from src.truth import receipt_comparisons


class ReceiptTests(unittest.TestCase):
    def test_many_to_one_delivery_note_reconciles_both_po_lines(self):
        booked = [{"po_line": 1, "qty_received": 5000}, {"po_line": 2, "qty_received": 6000}]
        scanned = [{"value": {"quantity": 6000}}, {"value": {"quantity": 5000}}]
        matches = list(receipt_comparisons(booked, scanned))
        self.assertEqual(matches, [(booked[1], scanned[0]), (booked[0], scanned[1])])

    def test_explicit_po_line_uses_corrected_quantity(self):
        booked = [{"po_line": 1, "qty_received": 8000}, {"po_line": 2, "qty_received": 80000}]
        scanned = [{"value": {"line": 2, "printed_quantity": 80000,
                              "handwritten_quantity": 8000, "quantity": 8000}}]
        self.assertEqual(list(receipt_comparisons(booked, scanned)), [(booked[1], scanned[0])])


class ApprovalTests(unittest.TestCase):
    def test_vacant_role_routes_to_documented_exception_and_blocks_release(self):
        def document(source, fields, kind="context", supplier_id=None):
            return {"source": source, "kind": kind, "supplier_id": supplier_id,
                    "fields": {name: [dict(field, citation={"file": source, "page": field["page"],
                                                           "quote": field["quote"]}) for field in entries]
                               for name, entries in fields.items()}}

        release = "5. New suppliers\nSerial release requires successful PPAP and both signers."
        exception = "6. Exceptions\nThe Head of Procurement approves documented exceptions."
        policy, org, contract = Facts(POLICY), Facts(ORG), Facts("supplier.pdf")
        context(policy, f"{release}\n{exception}", 1, 1)
        context(org, "Alex Smith\nHead of Procurement\nTBD           Sam Jones\n"
                "Category Lead Collector's Items           Supplier Quality Lead", 1, 1)
        contract.add("annex", {"material": "PART-1"}, 2, "PART-1")
        contract.add("qualification", "PPAP and written release", 1, "PPAP and written release")
        supplier = {"qualification_status": "conditional", "category": "Collector's Items", "supplier_id": "SUP-1"}
        docs = [document(POLICY, policy), document(ORG, org), document("supplier.pdf", contract, "contract", "SUP-1")]
        block = ppap_block(docs, supplier, "PART-1", "- The Category Lead for Collector's Items position is open.")
        self.assertEqual(block["policy_clause"]["quote"], release)
        self.assertEqual(block["exception"]["name"], "Alex Smith")
        self.assertEqual(block["exception"]["policy_clause"]["quote"], exception)
        self.assertEqual([signer["name"] for signer in block["required_signers"]], ["Sam Jones", None])
        self.assertTrue(any(source.get("row") == 1 for source in block["evidence"]))
        self.assertIsNone(ppap_block(docs, dict(supplier, qualification_status="released"), "PART-1", ""))

        approval = {"id": "aaa", "approval_block": block}
        with closing(sqlite3.connect(":memory:")) as con:
            with self.assertRaises(PermissionError):
                authorize(con, approval, "approve")
            self.assertEqual(authorize(con, approval, "review"), "blocked")
            stored, = con.execute("SELECT status FROM decisions").fetchone()
            self.assertEqual(stored, "review")
            with self.assertRaises(PermissionError):
                authorize(con, approval, "approve")

    def test_cost_of_waiting_uses_current_shortfall_and_product_cost(self):
        ref = {"file": "products.csv", "row": 4}
        editions = {"SKU-CE": {"remaining": 500, "evidence": [ref]}}
        products = {"SKU-CE": {"std_cost_eur": 42.5, "source": ref}}
        part = {"shortfall": 300, "unit_usage": {"SKU-CE": 2}}
        waiting = waiting_exposure(part, editions, products)
        self.assertEqual((waiting["units"], waiting["amount_eur"]), (150, 6375.0))
        self.assertEqual(waiting["evidence"], [ref, ref])

    def test_http_approval_returns_conflict_until_the_block_is_resolved(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "api.db"
            with closing(connect(database)) as con, con:
                save_state(con, "options", [{"id": "abc", "title": "Release blocked",
                                             "approval_block": {"reason": "A required signer is vacant."}}])
            handler_class = handler(SimpleNamespace(database=database))
            request = object.__new__(handler_class)
            request.headers = Message()
            request.headers["Host"] = "127.0.0.1"
            request.headers["Content-Length"] = "2"
            request.headers["Content-Type"] = "application/json"
            request.path = "/api/decisions/abc/approve"
            request.rfile = BytesIO(b"{}")
            responses = []
            request.out = lambda payload, status=200: responses.append((payload, status))
            request.do_POST()
            self.assertEqual(responses, [({"error": "A required signer is vacant.", "status": "blocked"}, 409)])


class ExportTests(unittest.TestCase):
    def test_activity_from_sqlite_includes_the_tool_chain_and_original_citation(self):
        source = "suppliers/SUP-1/notices/notice.pdf"
        cite = {"file": source, "page": 1, "quote": "暂停发货"}
        trace = [{"agent": "Document Agent", "citation": cite, "input_ref": f"{source}#page=1",
                  "output_ref": f"{source}#page=1&field=impact", "time": "2026-11-21T13:00:00+00:00",
                  "tool": tool, "status": status, "action": tool}
                 for tool, status in [("ocr", "succeeded"), ("llm_text", "succeeded"), ("quote_validation", "accepted")]]
        with tempfile.TemporaryDirectory() as folder, closing(sqlite3.connect(":memory:")) as con:
            con.row_factory = sqlite3.Row
            chaser.schema(con)
            path = Path(folder) / "docs.jsonl"
            path.write_text(json.dumps({"source": source, "sha": "a", "kind": "notice", "supplier_id": "SUP-1",
                                        "error": None, "fields": {}, "activity": trace}), encoding="utf-8")
            load_table(con, path)
            activity = dashboard_activity(con, [], lambda stamp: stamp)
        self.assertEqual([event["tool"] for event in activity], ["ocr", "llm_text", "quote_validation"])
        self.assertEqual(activity[-1]["citation"], cite)
        self.assertEqual(activity[-1]["status"], "accepted")

    def test_numbers_report_uses_current_evaluated_snapshot(self):
        source = {"file": "launch.xlsx", "sheet": "Editions", "row": 2}
        truth = {"deadline": "2026-11-22T20:00:00+01:00", "site": "DC-1", "source": source,
                 "editions": {"SKU-CE": {"packed": 7000, "target": 10000, "remaining": 3000, "probability": .25,
                                        "p10": 7500, "p50": 8500, "p90": 10000, "first_stop": "PART-1", "evidence": [source]}},
                 "parts": {"PART-1": {"material": "PART-1", "label": "Part 1", "raw_stock": 2000, "on_hand": 500,
                                      "inbound": 750, "shortfall": 1750, "required": 3000, "embedded_in": None}},
                 "issues": [], "model": {"runs": 100, "allocation": "CE first", "assumptions": "Test scenario."},
                 "data_quality": {"documents": 23, "errors": 1}}
        with tempfile.TemporaryDirectory() as folder, closing(connect(Path(folder) / "numbers.db")) as con:
            data = Path(folder) / "data"
            data.mkdir()
            ingest(con, data)
            with self.assertRaisesRegex(ValueError, "No evaluated launch snapshot"):
                numbers_report(con)
            save_state(con, "truth", truth)
            report = numbers_report(con)
            self.assertIn("7,500 / 8,500 / 10,000 | 25.0% | Part 1 | 1,500", report)
            self.assertIn("| 3,000 | 2,000 | 500 | 750 | 1,750 |", report)
            self.assertIn("23 documents processed, 1 extraction errors", report)
            truth["parts"]["PART-1"]["shortfall"] = 1000
            save_state(con, "truth", truth)
            self.assertIn("| 3,000 | 2,000 | 500 | 750 | 1,000 |", numbers_report(con))
