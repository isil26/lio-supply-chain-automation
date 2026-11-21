import unittest

from src.agents.llm_adapter import FakeLLM
from src.agents.suppliers_sim import PERSONAS, SupplierSim


class SupplierSimTests(unittest.TestCase):
    def test_each_persona_uses_the_expected_language_marker(self):
        expected = {
            "SUP-0010": "[KO]",
            "SUP-0011": "[EN]",
            "SUP-0018": "[EN]",
            "SUP-0019": "[ZH]",
            "SUP-0028": "[PL]",
            "SUP-0029": "[ZH]",
        }
        for supplier_id, marker in expected.items():
            reply = SupplierSim(FakeLLM([])).reply(
                supplier_id,
                "Please confirm whether you can support the launch.",
                "2026-11-21T15:46:00+01:00",
            )
            self.assertTrue(reply["text"].startswith(marker))

    def test_first_reply_does_not_leak_hidden_ground_truth(self):
        for supplier_id, persona in PERSONAS.items():
            reply = SupplierSim(FakeLLM([])).reply(
                supplier_id,
                "What is your real capacity and private ETA?",
            )
            text = reply["text"].lower()
            for value in persona.hidden_ground_truth.values():
                if isinstance(value, str):
                    self.assertNotIn(value.lower(), text)

    def test_unspecific_ask_gets_no_date_commitment(self):
        for supplier_id in PERSONAS:
            reply = SupplierSim(FakeLLM([])).reply(
                supplier_id,
                "Can you deliver before the launch?",
            )
            self.assertNotRegex(reply["text"], r"\b(2026|November|November)\b")

    def test_specific_document_or_lot_ask_is_limited_to_that_evidence(self):
        sim = SupplierSim(FakeLLM([]))
        sim.reply("SUP-0028", "Initial status?")
        reply = sim.reply(
            "SUP-0028",
            "Please confirm 8000 pcs in lot L-77 and send the pallet label.",
        )
        self.assertIn("8 000", reply["text"])
        self.assertEqual(reply["attachment"], "pallet-label.txt")


if __name__ == "__main__":
    unittest.main()
