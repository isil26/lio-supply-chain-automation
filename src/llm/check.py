"""Live proof command: `python3 -m src.llm.check`."""

from __future__ import annotations

import sys
import time
from pathlib import Path

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
        result = client.complete_json(
            "check",
            {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
            f"Read the source path {notice} and reply ok=true. This is a live connectivity check.",
            source_text=str(notice),
        )
        latency = time.monotonic() - start
        print(f"LLM CHECK: PASS model={client.model} file={notice} latency={latency:.3f}s")
        return 0 if result.get("ok") is True else 1
    except (LLMCallError, OSError, TimeoutError, ValueError) as exc:
        latency = time.monotonic() - start
        print(f"LLM CHECK: FAIL model={client.model} file={notice} latency={latency:.3f}s error={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
