import sqlite3
import tempfile
import unittest
from unittest.mock import patch

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

    def test_unseen_email_uses_local_translator_and_populates_thread(self):
        con = sqlite3.connect(":memory:")
        body = "Dostawa będzie możliwa rano."
        thread = {"language":"pl", "messages":[{"text":body}]}
        result = {"english":"Delivery will be possible in the morning.","summary":None,"language":"Polish","source":"translated"}
        with patch.object(translate.local_translation,"to_english",return_value=result) as worker:
            self.assertEqual(translate.translate(con,body,hint="pl"),result)
            self.assertEqual(translate.translate(con,body,hint="pl"),result)
            translate.annotate(con,[thread])
            worker.assert_called_once()
        self.assertEqual(thread["messages"][0],{"text":body,"english":result["english"]})

    def test_machine_translation_preserves_source_references_even_after_model_errors(self):
        from .local_translation import _preserve, references_preserved
        source = "订单 4500318738 行 00020，数量 350,000。"
        repaired = _preserve(source, "PO 450318738 line 00020, quantity 350,000.", None)
        self.assertEqual(repaired,"PO 4500318738 line 00020, quantity 350,000.")
        fallback = _preserve(source, "We have the items.", lambda texts:["Order" for _ in texts])
        self.assertTrue(references_preserved(source,fallback))
        con = sqlite3.connect(":memory:")
        translate.schema(con)
        key = translate.hashlib.sha256(source.encode()).hexdigest()
        con.execute("INSERT INTO translations VALUES(?,?,?,?)",(key,"Chinese","PO 450318738.",None))
        self.assertIsNone(translate._cached(con, source, "zh"))

    def test_no_model_says_so(self):
        out = translate.translate(sqlite3.connect(":memory:"), "Dzień dobry, możemy zarezerwować książki.",
                                  LLMClient(model=None, provider="none"))
        self.assertEqual(out["source"], "unavailable")


if __name__ == "__main__":
    unittest.main()
