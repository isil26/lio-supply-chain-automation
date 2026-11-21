import json
import tempfile
import unittest
from pathlib import Path

from .client import LLMCallError, LLMClient
from .check import find_polish_notice


SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "value": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["value", "quote"],
            },
        }
    },
    "required": ["facts"],
}


class LLMClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_fake_transport_schema_and_cache(self):
        calls = []

        def transport(model, url, payload, headers, timeout):
            calls.append(payload)
            return {"facts": [{"value": "deadline 2026-11-23", "quote": "deadline 2026-11-23"}]}

        client = LLMClient(
            model="fake",
            url="http://127.0.0.1:11434/v1/chat/completions",
            transport=transport,
            cache_dir=self.root / "cache",
            log_path=self.root / "log.jsonl",
        )
        first = client.complete_json(
            "test", SCHEMA, "Extract",
            source_text="The deadline 2026-11-23 is confirmed.",
        )
        second = client.complete_json(
            "test", SCHEMA, "Extract",
            source_text="The deadline 2026-11-23 is confirmed.",
        )
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)
        self.assertTrue((self.root / "cache").is_dir())
        self.assertTrue((self.root / "log.jsonl").exists())

    def test_quote_must_appear_in_source(self):
        def transport(model, url, payload, headers, timeout):
            return {"facts": [{"value": "invented", "quote": "not in source"}]}

        client = LLMClient(model="fake", transport=transport,
                           cache_dir=self.root / "cache", log_path=self.root / "log.jsonl")
        with self.assertRaisesRegex(LLMCallError, "not present"):
            client.complete_json("test", SCHEMA, "Extract", source_text="real source")

    def test_missing_quote_is_rejected(self):
        def transport(model, url, payload, headers, timeout):
            return {"facts": [{"value": "invented"}]}

        client = LLMClient(model="fake", transport=transport,
                           cache_dir=self.root / "cache", log_path=self.root / "log.jsonl")
        with self.assertRaisesRegex(LLMCallError, "quote is required"):
            client.complete_json("test", SCHEMA, "Extract", source_text="real source")

    def test_invalid_schema_is_rejected(self):
        def transport(model, url, payload, headers, timeout):
            return {"facts": "not an array"}

        client = LLMClient(model="fake", transport=transport,
                           cache_dir=self.root / "cache", log_path=self.root / "log.jsonl")
        with self.assertRaises(LLMCallError):
            client.complete_json("test", SCHEMA, "Extract", source_text="real source")

    def test_call_budget_is_enforced(self):
        def transport(model, url, payload, headers, timeout):
            return {"facts": []}

        client = LLMClient(model="fake", transport=transport, call_budget=1,
                           cache_dir=self.root / "cache", log_path=self.root / "log.jsonl")
        client.complete_json("one", SCHEMA, "Extract", source_text="")
        with self.assertRaisesRegex(LLMCallError, "budget exhausted"):
            client.complete_json("two", SCHEMA, "Extract", source_text="")

    def test_api_key_header_and_timeout_pass_to_transport(self):
        seen = {}

        def transport(model, url, payload, headers, timeout):
            seen.update({"model": model, "url": url, "headers": headers, "timeout": timeout})
            return {"facts": []}

        client = LLMClient(model="remote", url="https://example.invalid/v1/chat/completions",
                           api_key="secret", transport=transport, timeout=7,
                           cache_dir=self.root / "cache", log_path=self.root / "log.jsonl")
        client.complete_json("test", SCHEMA, "Extract", source_text="")
        self.assertEqual(seen["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(seen["timeout"], 7)

    def test_live_check_finds_no_data_gracefully(self):
        found = find_polish_notice()
        self.assertTrue(found is None or found.exists())
