"""Evidence-first document reader with deterministic and vision fallbacks.

The reader is intentionally narrower than the document pipeline: it returns a
small, stable contract for agent tools and never promotes model-proposed facts
to forecast input.  Every returned fact has source evidence; image evidence is
the model's verbatim transcription and remains provisional until approved.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from src.docs.media import LocalOCR, pdf_text, render_page
from src.docs.parsers import PARSERS, classify
from src.docs.schema import Facts
from src.llm.client import LLMCallError, LLMClient


_IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".tif": "image/tiff", ".tiff": "image/tiff"}
_EXPECTED = {
    "confirmation": {"po", "items"},
    "notice": {"what", "effective_at", "ends_at"},
    "contract": {"clauses"},
    "receiving": {"items"},
    "inspection": {"inspection"},
}
_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "language": {"type": "string"},
        "translation_en": {"type": "string"},
        "facts": {"type": "array", "items": {
            "type": "object", "additionalProperties": True,
            "required": ["field", "value", "quote", "page", "confidence"],
            "properties": {
                "field": {"type": "string"}, "value": {},
                "quote": {"type": "string", "minLength": 1},
                "page": {"type": "integer"},
                "confidence": {"type": "number"},
                "translation_en": {"type": "string"},
            },
        }},
    },
    "required": ["facts", "language", "translation_en"],
}


def _compact(value: str) -> str:
    return " ".join(str(value).split())


def _language(text: str) -> str:
    lowered = text.casefold()
    if any(token in lowered for token in ("zawiadomienie", "przestoju", "wysyłka")):
        return "pl"
    if any(token in lowered for token in ("lieferung", "wartung", "stillstand")):
        return "de"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    return "en"


def _kind(path: Path) -> str:
    return classify(path.as_posix())


def _facts_to_list(facts: Facts, *, provisional=False, method="deterministic",
                   translation_en="") -> list[dict]:
    result = []
    for field, entries in facts.items():
        for entry in entries:
            result.append({
                "field": field,
                "value": entry.get("value"),
                "quote": entry.get("quote", ""),
                "page": entry.get("page") or 1,
                "confidence": entry.get("confidence", 1.0),
                "translation_en": entry.get("translation_en", translation_en),
                "source_file": entry.get("source_file", facts.source),
                "method": entry.get("method", method),
                "provisional": bool(provisional),
            })
    return result


class DocumentReader:
    def __init__(self, *, llm: LLMClient | None = None,
                 review_db: str | Path = "store/reader.sqlite",
                 repo: str | Path | None = None):
        self.llm = llm
        self.review_db = Path(review_db)
        self.repo = Path(repo or Path(__file__).resolve().parents[2])

    def _review(self, filename: str, reason: str) -> dict:
        self.review_db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.review_db) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS doc_review (
                file TEXT PRIMARY KEY, reason TEXT NOT NULL, ts TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
            )""")
            db.execute("""INSERT INTO doc_review(file, reason, ts, status)
                VALUES (?, ?, ?, 'pending')
                ON CONFLICT(file) DO UPDATE SET reason=excluded.reason, ts=excluded.ts,
                status=CASE WHEN doc_review.status='approved' THEN 'approved' ELSE 'pending' END""",
                       (filename, reason, datetime.now(timezone.utc).isoformat()))
        return {"file": filename, "reason": reason, "status": "pending"}

    def approve(self, filename: str) -> dict:
        with sqlite3.connect(self.review_db) as db:
            row = db.execute("SELECT file FROM doc_review WHERE file=?", (filename,)).fetchone()
            if not row:
                raise ValueError(f"review item not found: {filename}")
            db.execute("UPDATE doc_review SET status='approved' WHERE file=?", (filename,))
        return {"file": filename, "status": "approved"}

    def _source_pages(self, path: Path) -> tuple[list[str], list[Path], str]:
        suffix = path.suffix.casefold()
        if suffix in {".txt", ".md"}:
            return [path.read_text(encoding="utf-8", errors="replace")], [], "text"
        if suffix == ".eml":
            message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
            body = message.get_body(preferencelist=("plain", "html"))
            return [body.get_content(errors="replace") if body else ""], [], "email"
        if suffix == ".pdf":
            with tempfile.TemporaryDirectory(prefix="reader-") as work:
                pages = pdf_text(path, Path(work))
            return pages, [], "pdf"
        if suffix in _IMAGE_TYPES:
            # A configured vision reader is the primary scan path; avoid an
            # unbounded local OCR attempt before sending the original pixels.
            if self.llm and self.llm.configured():
                return [], [path], "image"
            with tempfile.TemporaryDirectory(prefix="reader-") as work:
                image = path
                try:
                    ocr = LocalOCR(self.repo, Path(work))
                    text, _ = ocr.read(path, receiving=False)
                except (OSError, RuntimeError, ValueError):
                    text = ""
            return ([text] if text else []), [image], "image"
        raise ValueError(f"unsupported document format: {suffix or '<none>'}")

    def _deterministic(self, pages: list[str], path: Path, kind: str) -> tuple[list[dict], str]:
        facts = Facts(path.as_posix())
        parser = PARSERS.get(kind)
        for page, text in enumerate(pages, 1):
            if parser and text.strip():
                parser(facts, text, page, 1.0)
        return _facts_to_list(facts), _language("\n".join(pages))

    @staticmethod
    def _coverage(kind: str, facts: list[dict]) -> str:
        fields = {item["field"] for item in facts}
        expected = _EXPECTED.get(kind)
        if facts and (not expected or expected <= fields):
            return "full"
        return "partial" if facts else "none"

    def _model(self, path: Path, kind: str, pages: list[str], images: list[Path],
               language: str) -> tuple[list[dict], str]:
        if not self.llm or not self.llm.configured():
            return [], language
        text = "\n\n".join(pages)
        image_parts = []
        for image in images:
            mime = _IMAGE_TYPES.get(image.suffix.casefold(), "application/octet-stream")
            encoded = base64.b64encode(image.read_bytes()).decode("ascii")
            image_parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}})
        prompt = (
            f"Read this {kind} procurement document. Identify the language and translate every "
            "non-English fact into English. Transcribe evidence verbatim. Handwritten replacements "
            "must say 'read as X, uncertain' and include the printed value in the same quote. "
            "Never infer an illegible value. Return only the requested JSON."
        )
        try:
            result = self.llm.complete_json(
                "document-reader", _SCHEMA, prompt, source_text=text,
                images=image_parts or None, validate_quotes=bool(text),
            )
        except (LLMCallError, OSError, ValueError, KeyError, TypeError):
            return [], language
        output = []
        for item in result.get("facts", []):
            quote = str(item.get("quote", "")).strip()
            if not quote or (text and _compact(quote) not in _compact(text)):
                continue
            try:
                page = int(item.get("page", 1))
                confidence = float(item.get("confidence", .75))
            except (TypeError, ValueError):
                continue
            if not 0 < confidence <= 1:
                continue
            output.append({
                "field": str(item["field"]), "value": item.get("value"), "quote": quote,
                "page": page, "confidence": min(confidence, .95),
                "translation_en": str(item.get("translation_en") or result.get("translation_en") or ""),
                "source_file": path.as_posix(), "method": "llm_vision" if images else "llm_text",
                "provisional": True,
            })
        return output, str(result.get("language") or language)

    def read_document(self, path: str | Path, supplier_id: str | None = None) -> dict:
        resolved = Path(path)
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        filename = resolved.as_posix()
        kind = _kind(resolved)
        try:
            pages, images, source_type = self._source_pages(resolved)
        except (OSError, RuntimeError, ValueError, TypeError, EOFError):
            review = self._review(filename, "unreadable or unsupported document")
            return {"coverage": "none", "language": "unknown", "kind": kind, "facts": [],
                    "needs_review": True, "reason": review["reason"], "uncertainty": "document could not be read",
                    "review": review, "supplier_id": supplier_id}
        facts, language = self._deterministic(pages, resolved, kind)
        coverage = self._coverage(kind, facts)
        if coverage != "full":
            proposed, model_language = self._model(resolved, kind, pages, images, language)
            if proposed:
                facts.extend(proposed)
                language = model_language
                coverage = "partial" if coverage == "none" else coverage
        low_confidence = any(item["confidence"] < .7 for item in facts)
        needs_review = coverage != "full" or low_confidence or any(item["provisional"] for item in facts)
        reason = None
        review = None
        if needs_review:
            reason = "partial coverage" if coverage != "full" else "provisional or low-confidence facts"
            review = self._review(filename, reason)
        return {
            "coverage": coverage, "language": language, "kind": kind, "facts": facts,
            "needs_review": needs_review, "reason": reason, "uncertainty": (
                "Model facts are provisional until approved." if any(item["provisional"] for item in facts) else ""
            ), "review": review, "supplier_id": supplier_id, "source_type": source_type,
        }

    __call__ = read_document


def read_document(path: str | Path, supplier_id: str | None = None, *,
                  llm: LLMClient | None = None, review_db: str | Path = "store/reader.sqlite") -> dict:
    return DocumentReader(llm=llm, review_db=review_db).read_document(path, supplier_id)


def reader_tool(reader: DocumentReader | None = None) -> dict:
    """Return a runtime-compatible closed tool specification."""
    reader = reader or DocumentReader()
    return {
        "name": "read_document",
        "description": "Read a document with deterministic extraction and quote-validated vision fallback.",
        "function": lambda path, supplier_id=None: reader.read_document(path, supplier_id),
        "schema": {"type": "object", "properties": {
            "path": {"type": "string"}, "supplier_id": {"type": ["string", "null"]},
        }, "required": ["path"], "additionalProperties": False},
        "needs_approval": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path")
    parser.add_argument("--supplier-id")
    parser.add_argument("--review-db", default="store/reader.sqlite")
    args = parser.parse_args(argv)
    print(json.dumps(read_document(args.path, args.supplier_id, review_db=args.review_db),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
