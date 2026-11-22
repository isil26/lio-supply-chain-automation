import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.agents.tools import _ToolContext, all_tools


class ToolRegistryTests(unittest.TestCase):
    def test_registry_is_closed_and_handlers_are_callable(self):
        with tempfile.TemporaryDirectory() as directory:
            tools = all_tools(Path(directory) / "soony.db")
        expected = {
            "get_readiness", "list_shortfalls", "release_gate_status", "packplan", "whatif", "supplier_history",
            "search_documents", "get_document", "list_shipments", "get_po",
            "compare_sources", "list_options", "breakeven", "draft_email", "send_email",
            "parse_reply", "propose_option", "escalate_to_human", "request_review",
        }
        self.assertEqual({tool["name"] for tool in tools}, expected)
        self.assertTrue(all(callable(tool["handler"]) for tool in tools))
        self.assertTrue(next(tool for tool in tools if tool["name"] == "send_email")["needs_approval"])

    def test_draft_store_preserves_operational_mail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "soony.db"
            with sqlite3.connect(path) as con:
                con.execute("CREATE TABLE messages(id INTEGER PRIMARY KEY, chase_id TEXT, parsed TEXT)")
                con.execute("INSERT INTO messages VALUES(1, 'thread', 'original')")
            store = _ToolContext(path).draft_store()
            self.assertNotEqual(store.path, path)
            self.assertEqual(store.list_threads(), [])
            with sqlite3.connect(path) as con:
                self.assertEqual(con.execute("SELECT parsed FROM messages").fetchone(), ("original",))
                self.assertIsNone(con.execute("SELECT name FROM sqlite_master WHERE name='messages_legacy'").fetchone())

    def test_request_review_is_persisted_with_citation(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "soony.db"
            tool = next(tool for tool in all_tools(db) if tool["name"] == "request_review")
            result = tool["handler"]({"file": "drop.eml", "reason": "unknown format"})
            self.assertEqual(result["citations"], [{"file": "drop.eml"}])
            with sqlite3.connect(db) as con:
                value = con.execute("SELECT value FROM state WHERE key='documentReviews'").fetchone()[0]
            self.assertIn("unknown format", value)

    def test_cli_schema_shape_is_json_serializable(self):
        tool = all_tools(":memory:")[0]
        json.dumps({key: tool[key] for key in ("name", "input_schema", "needs_approval")})


if __name__ == "__main__":
    unittest.main()
