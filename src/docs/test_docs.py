"""Tests for the document pipeline using fictional fixtures only."""

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from src.docs import documents, load_table, read_jsonl
from src.docs.extract import extract_file, merge_translation
from src.docs.parsers import classify, contract, notice, order, receipt_text, workbook
from src.docs.pipeline import digest, run_pipeline
from src.docs.providers import LocalVisionClient, configured_clients
from src.docs.schema import Facts


class ParserTests(unittest.TestCase):
    def test_confirmation_rows_and_wrapped_conditions(self):
        fields = Facts("confirmation.pdf")
        page = (
            "Order Confirmation OA12345678\n"
            "Customer · Your order 4500000001 · Incoterms EXW Boise · Payment NET45\n"
            "    00010    CMP-TST-001    Card 64       12,345    1,024.50    USD    2026-12-03\n"
            "                            and packaging\n"
            "    00020    CMP-TST-002    Sleeve        7,010        0.04    USD    2026-12-04\n"
            "Terms of delivery: Seller prepays freight.\n"
            "Buyer reimburses the cost. Artwork rev C."
        )
        order(fields, page, 2, 1.0)
        self.assertEqual(fields.first("po"), "4500000001")
        self.assertEqual(fields.first("incoterm"), "EXW Boise")
        first, second = fields["items"]
        self.assertEqual(first["value"], {
            "line": 1, "material": "CMP-TST-001", "quantity": 12345,
            "unit_price": 1024.5, "currency": "USD", "promised_date": "2026-12-03",
        })
        self.assertEqual((first["page"], second["value"]["line"]), (2, 2))
        self.assertIn("Buyer reimburses", fields.first("conditions"))
        self.assertEqual(fields.first("revision"), "C")

    def test_stacked_confirmation_layout(self):
        fields = Facts("confirmation.pdf")
        order(fields, "00030\nCMP-TST-004\nBook\n8 001\n12.4\nEUR\n2026-11-21", 1, 1)
        self.assertEqual(fields.first("items")["quantity"], 8001)

    def test_multiple_contract_pages_and_aliases(self):
        fields = Facts("contract.pdf")
        contract(fields, "§ 3 Ordering and lead time\nParts ship per Annex A.", 2, .75)
        contract(fields, "Annex A\nCMP-TST-004  Art book  6.70 EUR MOQ 5,000 LT 21d\n"
                 "Annex C\nCMP-TST-004    SUPPART-A-004\n", 3, .75)
        self.assertEqual(fields["lead_time"][0]["page"], 2)
        self.assertEqual(fields.first("annex")["moq"], 5000)
        self.assertEqual(fields.first("aliases")["supplier_material"], "SUPPART-A-004")

    def test_receipt_quantities_and_non_damage(self):
        fields = Facts("scan.jpg")
        receipt_text(fields, "Zamówienie: 4500000001\nCMP-TST-004 | Art book 12.345 PCS\n"
                     "CMP-TST-009 | Print 21 500 szt.\nRemarks: no visible damage", 1, .75)
        self.assertEqual([item["value"]["quantity"] for item in fields["items"]], [12345, 21500])
        self.assertFalse(fields.get("damage"))

    def test_translation_rejects_unsourced_claims(self):
        class Translator:
            def extract(self, text, *, kind):
                return {"translation_en": [
                    {"value": "Force majeure", "quote": "不可抗力", "confidence": .85},
                    {"value": "Made-up term", "quote": "Missing", "confidence": .9},
                ], "items": [{"value": "Out of scope", "quote": "不可抗力"}]}

        fields = Facts("contract.pdf")
        merge_translation(fields, Translator(), "§ 1 不可抗力", "contract", 4)
        self.assertEqual(len(fields["translation_en"]), 1)
        self.assertEqual(fields["translation_en"][0]["page"], 4)
        self.assertNotIn("items", fields)

    def test_rush_offer_survives_interleaved_table_columns(self):
        fields = Facts("notice.pdf")
        notice(fields, "Supplier\nOffer: rush service\n"
               "2   CMP-TST-001 Art   8 000 szt. / 8,000 pcs   załadunek w 4 h\n"
               "    book                                      zamówienia / loaded\n"
               "    hardcover                                 within 4 h", 1, 1)
        self.assertEqual(fields.first("available_offer"), {"material": "CMP-TST-001", "quantity": 8000,
                                                           "load_hours": 4})

    @unittest.skipUnless(importlib.util.find_spec("openpyxl"), "openpyxl is needed for XLSX")
    def test_price_list_headers_reordered_with_source_row(self):
        from io import BytesIO

        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active
        sheet.title = "Export"
        sheet.append(["Currency", "Valid from", "New price", "Material", "Current price"])
        sheet.append(["PLN", "2026-11-21", 1.24, "CMP-TST-004", 1.20])
        stream = BytesIO()
        book.save(stream)
        stream.seek(0)
        fields = Facts("prices.xlsx")
        workbook(fields, stream)
        item = fields["price_items"][0]
        self.assertEqual(item["value"]["unit_price"], 1.24)
        self.assertEqual((item["sheet"], item["row"], item["page"]), ("Export", 2, 1))


class FakeVision:
    cache_key = "test-provider-v1"

    def __init__(self):
        self.calls = 0

    def extract(self, image, *, kind):
        self.calls += 1
        suffix = image.read_bytes()
        count = 8000 if suffix == b"scan-a" else 9000
        return {"facts": {"items": [{"value": {"material": "CMP-TST-004", "handwritten_quantity": count},
                                     "quote": f"{count:,}".replace(",", " "), "confidence": .91}]}}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.data = self.root / "data"
        self.receiving = self.data / "soony/receiving/DC-HAM"
        self.receiving.mkdir(parents=True)
        self.erp = self.data / "soony/erp"
        self.erp.mkdir()
        self.scan = self.receiving / "example.jpg"
        self.scan.write_bytes(b"scan-a")
        self.po = self.erp / "purchase_orders_fresh.csv"
        self.po.write_text("po_number,po_line,material_id,quantity\n4500000001,1,CMP-TST-004,8000\n")
        self.gr = self.erp / "goods_receipts.csv"
        self.gr.write_text("delivery_note,po_number,po_line,material_id,qty_received\n"
                           "WZ-261116-999,4500000001,1,CMP-TST-004,80000\n")
        self.output = self.root / "store/docs.jsonl"
        self.state = self.root / "state.json"
        self.write_state(self.scan)
        self.client = FakeVision()

    def write_state(self, *scans):
        paths = (*scans, self.po, self.gr)
        self.state.write_text(json.dumps({path.relative_to(self.data).as_posix(): digest(path) for path in paths}))

    def run_docs(self):
        raw = "Nr: WZ-261116-999\nZamowienie: 4500000001\nCMP-TST-004 | Art book 80.000 PCS"
        count = 8000 if not self.scan.exists() or self.scan.read_bytes() == b"scan-a" else 9000
        with patch("src.docs.media.LocalOCR.read", return_value=(raw, [object()])), patch(
            "src.docs.media.LocalOCR.missing_quantities", return_value={}
        ), patch("src.docs.media.LocalOCR.handwritten_quantities",
                 return_value={"CMP-TST-004": (count, f"{count:,}".replace(",", " "))}):
            return run_pipeline(self.data, self.state, self.output, vision=self.client)

    def test_erp_workbook_rows_are_available_for_review(self):
        from openpyxl import Workbook
        update = self.erp / "stock_update.xlsx"
        book = Workbook()
        book.active.title = "Components"
        book.active.append(["Site", "Material", "Qty"])
        book.active.append(["DC-HAM", "CMP-TST-004", 4500])
        book.save(update)
        self.write_state(update)
        self.run_docs()
        doc, = read_jsonl(self.output)
        self.assertEqual(doc["source"], "soony/erp/stock_update.xlsx")
        self.assertIn("unrecognized workbook layout", doc["review_reasons"])
        row = doc["fields"]["rows"][1]
        self.assertEqual((row["sheet"], row["row"]), ("Components", 2))
        self.assertIn("4500", row["quote"])

    def test_cache_update_removal_erp_changes_and_sqlite_loader(self):
        self.assertEqual(self.run_docs()["cache_hits"], 0)
        doc, = read_jsonl(self.output)
        field, = doc["fields"]["handwritten_quantity"]
        mismatch, = doc["mismatches"]
        self.assertEqual(field["value"], 8000)
        self.assertEqual(field["method"], "llm_vision")
        self.assertEqual([(e["tool"], e["status"]) for e in doc["activity"]],
                         [("ocr", "succeeded"), ("ocr_crop", "succeeded"), ("llm_vision", "succeeded"),
                          ("quote_validation", "accepted")])
        self.assertEqual((mismatch["code"], mismatch["erp"]["value"], mismatch["erp"]["row"]),
                         ("goods_receipt_mismatch", 80000, 2))
        content = self.output.read_bytes()
        self.assertEqual(self.run_docs()["cache_hits"], 1)
        self.assertEqual(self.output.read_bytes(), content)
        self.assertEqual(self.client.calls, 1)

        twin = self.receiving / "identical.jpg"
        twin.write_bytes(self.scan.read_bytes())
        self.write_state(self.scan, twin)
        self.assertEqual(self.run_docs()["cache_hits"], 2)
        for row in read_jsonl(self.output):
            self.assertEqual(row["fields"]["delivery_note"][0]["source_file"], row["source"])
            for event in row["activity"]:
                self.assertEqual(event["citation"]["file"], row["source"])
                self.assertTrue(event["input_ref"].startswith(row["source"] + "#"))
        self.write_state(self.scan)
        self.assertTrue(twin.exists())
        self.assertEqual(self.run_docs()["documents"], 1)

        self.gr.write_text(self.gr.read_text().replace("80000", "8000"))
        self.assertEqual(self.run_docs()["mismatches"], 0)
        self.assertEqual(self.client.calls, 1)

        self.scan.write_bytes(b"scan-b")
        self.assertEqual(self.run_docs()["mismatches"], 2)
        doc, = read_jsonl(self.output)
        self.assertEqual(doc["sha"], digest(self.scan))
        self.assertNotEqual(doc["bridge_sha"], doc["sha"])
        self.assertEqual(self.client.calls, 2)

        with closing(sqlite3.connect(":memory:")) as db:
            self.assertEqual(load_table(db, self.output), 1)
            loaded, = documents(db)
            self.assertEqual(loaded["fields"]["handwritten_quantity"][0]["citation"]["file"], doc["source"])
            bad = self.root / "invalid.jsonl"
            bad.write_text("invalid JSON")
            with self.assertRaises(ValueError):
                load_table(db, bad)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM doc_extractions").fetchone()[0], 1)
            self.scan.unlink()
            self.assertEqual(self.run_docs()["documents"], 0)
            self.assertEqual(load_table(db, self.output), 0)

    def test_failed_provider_falls_back_and_retries(self):
        with patch.object(self.client, "extract", side_effect=OSError("simulated failure")) as provider:
            for _ in range(2):
                stats = self.run_docs()
                self.assertEqual((stats["warnings"], stats["errors"], stats["cache_hits"]), (1, 0, 0))
        self.assertEqual(provider.call_count, 2)
        doc, = read_jsonl(self.output)
        self.assertEqual(doc["methods"], ["ocr"])
        self.assertEqual(doc["fields"]["items"][0]["value"]["quantity"], 8000)
        self.assertIn(("llm_vision", "error"), [(e["tool"], e["status"]) for e in doc["activity"]])

    def test_model_transcription_cannot_validate_its_own_quote(self):
        self.po.write_text(self.po.read_text().replace(",8000", ",7000"))
        payload = {"text": "CMP-TST-004 9 000", "facts": {"items": [
            {"value": {"material": "CMP-TST-004", "handwritten_quantity": 9000}, "quote": "9 000"},
            {"value": {"material": "CMP-TST-005", "handwritten_quantity": 8000}, "quote": "8 000"},
            {"value": {"material": "CMP-TST-004", "handwritten_quantity": 8000}, "quote": "8,000"},
        ]}}
        with patch.object(self.client, "extract", return_value=payload):
            self.run_docs()
        doc, = read_jsonl(self.output)
        self.assertNotIn("handwritten_quantity", doc["fields"])
        self.assertEqual(doc["fields"]["items"][0]["value"]["quantity"], 80000)
        self.assertEqual([event["status"] for event in doc["activity"] if event["tool"] == "quote_validation"],
                         ["rejected", "rejected", "rejected"])

    def test_notice_extraction_checks_polish_korean_and_chinese_against_source(self):
        for raw in ("Wysyłki wstrzymane do poniedziałku.", "월요일까지 배송 중단.", "暂停发货至周一。"):
            with self.subTest(raw=raw), patch("src.docs.extract.pdf_text", return_value=[raw]):
                provider = unittest.mock.Mock()
                provider.extract.return_value = {"impact": [
                    {"value": "Shipping paused until Monday", "quote": raw},
                    {"value": "Forged replacement", "quote": "This text was never on the page."},
                ]}
                activity = []
                facts, _, methods, _ = extract_file(Path("notice.pdf"), "notice.pdf", "notice", None,
                                                    translator=provider, activity=activity)
                self.assertEqual([field["value"] for field in facts["impact"]], ["Shipping paused until Monday"])
                self.assertEqual(methods, {"pdf_text", "llm_text"})
                self.assertEqual([e["status"] for e in activity], ["succeeded", "succeeded", "accepted", "rejected"])
                self.assertEqual(activity[2]["citation"]["quote"], raw)

    def test_supplier_email_body_and_attachments_are_extracted_with_citations(self):
        from email.message import EmailMessage
        message = EmailMessage()
        message["From"], message["To"] = "logistics@suppliers.example", "team@example.com"
        message["Subject"], message["Date"] = "Delay notice", "Sun, 22 Nov 2026 06:10:00 +0000"
        message.set_content("Delay notice\nRevised FRA ETA 2026-11-23 for the air lot.")
        message.add_attachment("Attachment title\nSecond line of the attached notice.".encode(),
                               maintype="application", subtype="octet-stream", filename="update.txt")
        message.add_attachment(b"MZ", maintype="application", subtype="octet-stream", filename="tool.exe")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "reply.eml"
            path.write_bytes(bytes(message))
            self.assertEqual(classify(str(path)), "notice")
            facts, pages, methods, warnings = extract_file(path, "reply.eml", "notice", None)
        self.assertEqual(facts.first("subject"), "Delay notice")
        self.assertEqual(facts.first("what"), "Revised FRA ETA 2026-11-23 for the air lot.")
        self.assertEqual(facts.first("attachment"), "update.txt")
        self.assertIn("reply.eml#update.txt", {entry["source_file"] for entry in facts["what"]})
        self.assertEqual((pages, "text" in methods, "email" in methods), (2, True, True))
        self.assertEqual(len(warnings), 1)
        self.assertIn("tool.exe", warnings[0])

    def test_llm_environment_can_select_models_and_disable_the_provider(self):
        config = {"SOONY_LLM_MODEL": "text", "SOONY_LLM_VISION_MODEL": "vision",
                  "SOONY_LLM_URL": "http://127.0.0.1:8100/v1/chat/completions"}
        with patch.dict("os.environ", config, clear=True):
            vision, text = configured_clients()
            self.assertEqual((vision.model, text.model, text.url), ("vision", "text", config["SOONY_LLM_URL"]))
        with patch.dict("os.environ", dict(config, SOONY_LLM_PROVIDER="none"), clear=True):
            self.assertEqual(configured_clients(), (None, None))

    def test_loopback_adapter_passes_the_image_to_completion(self):
        with patch("src.docs.providers._complete", return_value={"text": "OCR from model"}) as completion:
            result = LocalVisionClient("image-model").extract(self.scan, kind="receiving")
        self.assertEqual(result, {"text": "OCR from model"})
        model, _, request = completion.call_args.args
        self.assertEqual(model, "image-model")
        self.assertEqual(request[1]["image_url"]["url"], "data:image/jpeg;base64,c2Nhbi1h")

    def test_loopback_adapter_decodes_the_ollama_chat_response(self):
        response = {"choices": [{"message": {"content": '{"facts":{"items":[]}}'}}]}
        with patch("src.docs.providers.urllib.request.build_opener") as build:
            build.return_value.open.return_value = BytesIO(json.dumps(response).encode())
            self.assertEqual(LocalVisionClient("image-model").extract(self.scan, kind="receiving"),
                             {"facts": {"items": []}})
        request, = build.return_value.open.call_args.args
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/v1/chat/completions")
        self.assertEqual(json.loads(request.data)["model"], "image-model")

    def test_local_crop_requires_corroboration_and_is_rechecked_from_cache(self):
        raw = ("No: WZ-261116-999\nPO: 4500000001\n"
               "CMP-TST-004 | Art book 80.000 PCS")
        with patch("src.docs.media.LocalOCR.read", return_value=(raw, [object()])), patch(
            "src.docs.media.LocalOCR.missing_quantities", return_value={}
        ), patch("src.docs.media.LocalOCR.handwritten_quantities", return_value={"CMP-TST-004": (8000, "8 000")}):
            run_pipeline(self.data, self.state, self.output)

        doc, = read_jsonl(self.output)
        item, = doc["fields"]["items"]
        self.assertEqual((item["value"]["quantity"], item["printed_evidence"]["value"]["quantity"]), (8000, 80000))
        self.assertEqual(doc["mismatches"][0]["code"], "goods_receipt_mismatch")

        self.po.write_text(self.po.read_text().replace(",8000", ",7000"))
        self.assertEqual(run_pipeline(self.data, self.state, self.output)["cache_hits"], 1)
        doc, = read_jsonl(self.output)
        self.assertNotIn("handwritten_correction", doc["fields"])
        self.assertIn("unverified_handwriting", doc["review_reasons"])

    def test_local_crop_with_unreadable_printed_digits_accepts_a_linked_over_receipt(self):
        raw = "Nr: WZ-261116-999\nZamowienie: 4500000001\nCMP-TST-004 | Art book unreadable PCS"
        with patch("src.docs.media.LocalOCR.read", return_value=(raw, [object()])), patch(
            "src.docs.media.LocalOCR.missing_quantities", return_value={}
        ), patch("src.docs.media.LocalOCR.handwritten_quantities", return_value={"CMP-TST-004": (8000, "8 000")}):
            run_pipeline(self.data, self.state, self.output)
        doc, = read_jsonl(self.output)
        item, = doc["fields"]["items"]
        self.assertEqual(item["value"]["quantity"], 8000)
        self.assertNotIn("printed_quantity", item["value"])
        self.assertEqual(doc["activity"][-1]["tool"], "erp_corroboration")


if __name__ == "__main__":
    unittest.main()
