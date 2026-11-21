import base64
import json
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

    def test_tool_shape_is_closed(self):
        tool = reader_tool(DocumentReader(review_db=self.db))
        self.assertEqual(tool["name"], "read_document")
        self.assertTrue(tool["schema"]["additionalProperties"] is False)


if __name__ == "__main__":
    unittest.main()
