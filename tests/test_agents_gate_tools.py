import json
import unittest

from src.agents.harness import citation_check, numeric_grounding
from src.agents.tools import all_tools
from src.agents.prompts import ROLE_TOOLS
from src.ingest.store import DB


def _tool(name):
    return next(t for t in all_tools(DB) if t["name"] == name)


@unittest.skipUnless(DB.exists(), "needs store/soony.db")
class GateToolGroundingTests(unittest.TestCase):
    def test_roles(self):
        self.assertIn("release_gate_status", ROLE_TOOLS["analyst"])
        self.assertIn("release_gate_status", ROLE_TOOLS["verifier"])
        self.assertLessEqual({"packplan", "release_gate_status"}, ROLE_TOOLS["planner"])
        self.assertNotIn("packplan", ROLE_TOOLS["analyst"])

    def test_gate_numbers_and_citations_are_accepted(self):
        result = _tool("release_gate_status")["handler"]({"part_id": "CMP-GAM-004"})
        trace = [{"tool": "release_gate_status", "result": json.dumps(result)}]
        text = "Sleeve is HUMAN: rev B 64,000 delivered at PackRight, rev C 634,000 at Karton."
        self.assertTrue(numeric_grounding(text, trace)["ok"])
        self.assertFalse(numeric_grounding(text + " 12,345 spare.", trace)["ok"])
        cite = result["citations"][0]
        claim = [{"text": f"Karton confirms {cite['quote']}", "file": cite["file"], "quote": cite["quote"]}]
        self.assertTrue(citation_check(claim, trace)["ok"])

    def test_packplan_numbers_are_accepted(self):
        result = _tool("packplan")["handler"]({"changes": {"part_arrives_earlier": {"CMP-GAM-001": 12}}})
        trace = [{"tool": "packplan", "result": json.dumps(result)}]
        units = result["value"]["baseline"]["ce_first"]["units"]
        self.assertTrue(numeric_grounding(f"CE-first packs {units:,} units.", trace)["ok"])
        self.assertFalse(numeric_grounding("The air lot adds 91,234 units.", trace)["ok"])


if __name__ == "__main__":
    unittest.main()
