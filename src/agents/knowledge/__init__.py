"""Small, deterministic knowledge-pack loader for Soony agent roles."""
from __future__ import annotations

from pathlib import Path


PACK_DIR = Path(__file__).resolve().parent
COMMON = ("domain.md", "data_map.md", "style.md")
ROLE_FILES = {
    "triage": ("policy.md", "pitfalls.md"),
    "analyst": ("policy.md", "pitfalls.md"),
    "verifier": ("policy.md", "pitfalls.md"),
    "planner": ("policy.md", "pitfalls.md", "negotiation.md"),
    "chaser": ("policy.md", "pitfalls.md", "negotiation.md"),
    "supplier_sim": ("negotiation.md",),
}


def load_pack(role: str) -> str:
    """Assemble the shared and role-relevant Markdown files for a role."""
    if role not in ROLE_FILES:
        raise ValueError(f"unknown agent role: {role}")
    names = COMMON + ROLE_FILES[role] + ("examples.md",)
    parts = []
    for name in names:
        path = PACK_DIR / name
        if not path.is_file():
            raise FileNotFoundError(f"knowledge pack file missing: {path}")
        parts.append(path.read_text(encoding="utf-8").strip())
    return "\n\n".join(parts)
