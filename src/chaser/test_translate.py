import sqlite3
import tempfile
import unittest

from . import translate
from src.llm.client import LLMClient


class TranslateTest(unittest.TestCase):
    def test_english_stays_as_is(self):
        out = translate.translate(sqlite3.connect(":memory:"), "Hello, we can ship 500 units and the price is EUR 4 with delivery Sunday.")
        self.assertEqual((out["source"], out["language"]), ("original", "English"))

    def test_polish_is_translated_once_and_cached(self):
        calls = []
        def transport(model, url, payload, headers, timeout):
            calls.append(payload)
            return {"language": "Polish", "english": "We can reserve 5,900 books.", "summary": "Can reserve 5,900 books."}
        with tempfile.TemporaryDirectory() as folder:
            client = LLMClient(model="m", provider="openai", transport=transport, cache_dir=folder, log_path=f"{folder}/log")
            con = sqlite3.connect(":memory:")
            text = "Dzień dobry, możemy zarezerwować 5 900 książek. Pozdrawiamy"
            first = translate.translate(con, text, client)
            second = translate.translate(con, text, LLMClient(model="m", provider="openai", transport=transport,
                                                              cache_dir=folder, log_path=f"{folder}/log"))
        self.assertEqual(first["english"], "We can reserve 5,900 books.")
        self.assertEqual(second["source"], "translated")
        self.assertEqual(len(calls), 1)

    def test_no_model_says_so(self):
        out = translate.translate(sqlite3.connect(":memory:"), "Dzień dobry, możemy zarezerwować książki.",
                                  LLMClient(model=None, provider="none"))
        self.assertEqual(out["source"], "unavailable")


if __name__ == "__main__":
    unittest.main()
