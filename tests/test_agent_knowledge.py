import re
import unittest
from pathlib import Path

from src.agents.knowledge import load_pack


ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "src" / "agents" / "knowledge"
FORBIDDEN_NUMBERS = ("5,900", "3,400", "6,800", "614,650")


class KnowledgePackTests(unittest.TestCase):
    def test_load_pack_all_roles(self):
        for role in ("triage", "analyst", "verifier", "planner", "chaser", "supplier_sim"):
            text = load_pack(role)
            self.assertIn("# Soony launch domain", text)
            self.assertIn("# Answer and citation style", text)
            self.assertIn("# Compact few-shot examples", text)

    def test_role_specific_content(self):
        self.assertIn("# Decision policy", load_pack("planner"))
        self.assertIn("# Chaser and negotiation", load_pack("chaser"))
        self.assertIn("single source", load_pack("supplier_sim").lower())

    def test_unknown_role_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown agent role"):
            load_pack("unknown")

    def test_no_published_computed_numbers(self):
        for path in PACK.glob("*.md"):
            text = path.read_text(encoding="utf-8")
            for forbidden in FORBIDDEN_NUMBERS:
                self.assertNotIn(forbidden, text, f"{forbidden} found in {path}")

    def test_stable_ids_exist_in_data(self):
        text = load_pack("analyst")
        components = (ROOT / "case-data" / "soony" / "master" / "components.csv").read_text(encoding="utf-8")
        for supplier_id in re.findall(r"SUP-\d{4}", text):
            matches = list((ROOT / "case-data").rglob(f"{supplier_id}_*"))
            self.assertTrue(matches, f"{supplier_id} missing from case-data")
        for component_id in re.findall(r"CMP-[A-Z]+-\d{3}", text):
            self.assertIn(component_id, components)


if __name__ == "__main__":
    unittest.main()
