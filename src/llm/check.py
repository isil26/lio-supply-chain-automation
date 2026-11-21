"""Live proof command: `python3 -m src.llm.check`."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from pypdf import PdfReader

from .client import LLMCallError, LLMClient


def find_polish_notice() -> Path | None:
    data = Path("data")
    candidates = sorted(data.rglob("*.pdf")) if data.exists() else []
    for path in candidates:
        name = path.name.lower()
        if any(word in name for word in ("zawiadomienie", "przestoj", "notice")):
            return path
    return candidates[0] if candidates else None


def main() -> int:
    client = LLMClient()
    if not client.configured():
        print("LLM CHECK: FAIL - SOONY_LLM_MODEL/SOONY_LOCAL_MODEL is not configured")
        return 1

    notice = find_polish_notice()
    if notice is None:
        print("LLM CHECK: FAIL - no PDF available under data/")
        return 1

    start = time.monotonic()
    try:
        reader = PdfReader(str(notice))
        source_text = "\n".join((page.extract_text() or "") for page in reader.pages[:3])
        if not source_text.strip():
            print(f"LLM CHECK: FAIL file={notice} no extractable PDF text")
            return 1
        result = client.complete_json(
            "check",
            {
                "type": "object",
                "properties": {
                    "facts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "value": {"type": "string", "minLength": 1},
                                "quote": {"type": "string", "minLength": 1},
                            },
                            "required": ["value", "quote"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["facts"],
                "additionalProperties": False,
            },
            f"Extract one meaningful procurement fact from this Polish or English notice. "
            f"Source file: {notice}\n\n{source_text[:12000]}",
            source_text=source_text,
        )
        latency = time.monotonic() - start
        print(f"LLM CHECK: PASS model={client.model} file={notice} latency={latency:.3f}s")
        return 0 if isinstance(result.get("facts"), list) else 1
    except (LLMCallError, OSError, TimeoutError, ValueError) as exc:
        latency = time.monotonic() - start
        print(f"LLM CHECK: FAIL model={client.model} file={notice} latency={latency:.3f}s error={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
