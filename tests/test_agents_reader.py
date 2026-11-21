import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

from src.agents.reader import DocumentReader, reader_tool
from src.llm.client import LLMClient


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "review.sqlite"

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_text_document_needs_no_model(self):
        path = self.root / "notices" / "notice.txt"
        path.parent.mkdir()
        path.write_text("Notice\nDelivery will remain available.", encoding="utf-8")
        result = DocumentReader(review_db=self.db).read_document(path)
        self.assertEqual(result["coverage"], "partial")
        self.assertTrue(result["needs_review"])
        self.assertEqual(result["facts"][0]["quote"], "Delivery will remain available.")

    def test_corrupt_file_enters_review_queue(self):
        path = self.root / "notice.pdf"
        path.write_bytes(b"not a pdf")
        result = DocumentReader(review_db=self.db).read_document(path)
        self.assertTrue(result["needs_review"])
        self.assertEqual(result["coverage"], "none")
        self.assertEqual(DocumentReader(review_db=self.db).approve(path.as_posix())["status"], "approved")

    def test_image_model_requires_verbatim_quote_and_is_provisional(self):
        path = self.root / "scan.png"
        path.write_bytes(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        ))

        def transport(model, url, payload, headers, timeout):
            return {"language": "de", "translation_en": "Maintenance notice",
                    "facts": [{"field": "what", "value": "Maintenance", "quote": "Wartung",
                               "page": 1, "confidence": .9, "translation_en": "Maintenance"}]}

        llm = LLMClient(model="gpt-4.1-mini", url="http://test", provider="openai_compat",
                        transport=transport, cache_dir=self.root / "cache", log_path=self.root / "llm.jsonl")
        result = DocumentReader(llm=llm, review_db=self.db, repo=self.root).read_document(path)
        self.assertEqual(result["language"], "de")
        self.assertTrue(result["facts"][0]["provisional"])
        self.assertEqual(result["facts"][0]["method"], "llm_vision")

    def test_struck_printed_quantity_keeps_both_values_and_requires_review(self):
        path = self.root / "WZ-261116-473.jpg"
        path.write_bytes(b"scan")
        calls = []

        def transport(model, url, payload, headers, timeout):
            calls.append(payload["messages"][-1]["content"])
            return {
                "language": "pl",
                "translation_en": "delivery note",
                "facts": [
                    {"field": "items", "value": {"material": "CMP-GAM-008"},
                     "quote": "80.000 struck through; handwritten 8 000",
                     "page": 1, "confidence": .94},
                    {"field": "printed_quantity", "value": 80000,
                     "quote": "80.000 struck through; handwritten 8 000",
                     "page": 1, "confidence": .94},
                    {"field": "handwritten_quantity", "value": 8000,
                     "quote": "80.000 struck through; handwritten 8 000",
                     "page": 1, "confidence": .9,
                     "translation_en": "read as 8 000, uncertain"},
                    {"field": "handwriting_present", "value": True,
                     "quote": "80.000 struck through; handwritten 8 000",
                     "page": 1, "confidence": .9},
                ],
            }

        llm = LLMClient(model="gpt-4.1-mini", url="http://test",
                        provider="openai_compat", transport=transport,
                        cache_dir=self.root / "cache", log_path=self.root / "llm.jsonl")
        result = DocumentReader(llm=llm, review_db=self.db, repo=self.root).read_document(path)
        self.assertEqual(len(calls), 1)
        self.assertTrue(result["needs_review"])
        self.assertEqual(result["coverage"], "full")
        corrected = next(item for item in result["facts"] if item["field"] == "handwritten_quantity")
        self.assertEqual(corrected["value"], 8000)
        self.assertIn("8 000", corrected["translation_en"])
        self.assertIn("uncertain", corrected["translation_en"])
        self.assertTrue(any(item["field"] == "printed_quantity" and item["value"] == 80000
                            for item in result["facts"]))

    def test_plain_printed_scan_is_sent_to_vision_without_false_correction(self):
        path = self.root / "DN-plain.jpg"
        path.write_bytes(b"scan")
        calls = []

        def transport(model, url, payload, headers, timeout):
            calls.append(True)
            return {
                "language": "en", "translation_en": "delivery note",
                "facts": [
                    {"field": "items", "value": {"material": "CMP-GAM-001"},
                     "quote": "Quantity 48,000", "page": 1, "confidence": .95},
                    {"field": "printed_quantity", "value": 48000,
                     "quote": "Quantity 48,000", "page": 1, "confidence": .95},
                    {"field": "handwriting_present", "value": False,
                     "quote": "Quantity 48,000", "page": 1, "confidence": .95},
                ],
            }

        llm = LLMClient(model="gpt-4.1-mini", url="http://test",
                        provider="openai_compat", transport=transport,
                        cache_dir=self.root / "cache", log_path=self.root / "llm.jsonl")
        result = DocumentReader(llm=llm, review_db=self.db, repo=self.root).read_document(path)
        self.assertEqual(calls, [True])
        self.assertFalse(any(item["field"] == "handwritten_quantity" for item in result["facts"]))
        self.assertTrue(any(item["field"] == "handwriting_present" and item["value"] is False
                            for item in result["facts"]))

    @unittest.skipUnless(
        os.getenv("SOONY_LLM_MODEL") or os.getenv("SOONY_LOCAL_MODEL"),
        "live reader model is not configured",
    )
    def test_live_reader_smoke_art_book_scan(self):
        path = Path("case-data/soony/receiving/DC-HAM/20261118_WZ-261116-473.jpg")
        if not path.is_file():
            self.skipTest("case snapshot is not present")
        result = DocumentReader(review_db=self.db).read_document(path)
        self.assertTrue(any(item["field"] == "handwritten_quantity" for item in result["facts"]))
        self.assertTrue(result["needs_review"])

    def test_tool_shape_is_closed(self):
        tool = reader_tool(DocumentReader(review_db=self.db))
        self.assertEqual(tool["name"], "read_document")
        self.assertTrue(tool["schema"]["additionalProperties"] is False)


if __name__ == "__main__":
    unittest.main()
