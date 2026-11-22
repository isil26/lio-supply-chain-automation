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
        self.assertEqual(thread["messages"][0], {"text":body, "english":result["english"],
                                                "supplierLanguage":"Polish", "supplierText":None})

    def test_mixed_offer_and_mailbox_keep_raw_email_and_share_supplier_translation(self):
        con = sqlite3.connect(":memory:")
        body = "Dzień dobry,\n\nWe can ship the goods tomorrow.\n\nThe price is EUR 2.10.\n\nPozdrawiam,"
        polish = "Dzień dobry,\n\nMożemy wysłać towar jutro.\n\nCena wynosi EUR 2.10.\n\nPozdrawiam,"
        con.execute("CREATE TABLE deals (id TEXT, excerpt TEXT, language TEXT)")
        con.execute("INSERT INTO deals VALUES ('offer', ?, 'en')", (body,))
        translate.schema(con)
        en = body.replace("Dzień dobry,", "Hello,").replace("Pozdrawiam,", "Regards,")
        key = translate.hashlib.sha256(body.encode()).hexdigest()
        con.execute("INSERT INTO translations VALUES(?,?,?,?)", (key, "Polish", en, None))
        thread = {"language":"en", "messages":[{"text":body}]}
        with patch.object(translate.local_translation, "to_supplier", return_value=polish) as worker:
            for _ in range(2):
                offer = translate.english(con, "offer")
                self.assertEqual((offer["english"], offer["supplierText"], offer["original"]), (en, polish, body))
            translate.annotate(con, [thread])
            worker.assert_called_once_with(body, "pl")
        self.assertEqual(thread["messages"][0], {"text":body, "english":en, "supplierText":polish, "supplierLanguage":"Polish"})

    def test_reverse_model_translates_every_english_sentence_and_keeps_native_prose(self):
        from . import local_translation as local
        with tempfile.TemporaryDirectory() as root:
            model = local.Path(root) / "en-ko/model"
            model.mkdir(parents=True)
            (model / "model.bin").touch()
            with patch.object(local, "model_root", return_value=local.Path(root)), \
                 patch.object(local, "_is_english_prose", side_effect=lambda s: s.startswith("We ")), \
                 patch.object(local, "_decoder", return_value=lambda phrases: ["선적 가능합니다." for _ in phrases]):
                body = "안녕하세요.\n\nWe can ship. We will confirm.\n\n확인 중입니다.\n\nWe are ready.\n\n감사합니다.\nAlex Nguyen"
                self.assertEqual(local.to_supplier(body, "ko"), "안녕하세요.\n\n선적 가능합니다. 선적 가능합니다.\n\n확인 중입니다.\n\n선적 가능합니다.\n\n감사합니다.\nAlex Nguyen")
                self.assertIsNone(local.to_supplier("We cannot ship the goods.", "ko"))

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
