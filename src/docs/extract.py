"""Extract facts from one input document without consulting ERP."""

import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from pathlib import Path

from src.ingest.readers import decode_csv

from .media import checked_vision, pdf_text, render_page
from .parsers import PARSERS, workbook
from .schema import DELIVERY_NOTE, Facts, quantity

TEXT_KINDS = {"notice", "contract", "price_list"}
TRANSLATED_FIELDS = {
    "what", "impact", "effective_at", "ends_at", "capacity", "penalties", "force_majeure",
    "lead_time", "moq", "payment", "liability", "qualification", "term", "translation_en",
}
PROVIDER_ERRORS = (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError)


def compact(text):
    return " ".join(text.split())


def record(activity, source, page, tool, status, action, output=None, quote=None, time=None):
    ref = f"{source}#page={page}"
    citation = {"file": source, "page": page}
    if quote:
        citation["quote"] = quote
    activity.append({"agent": "Document Agent", "tool": tool, "input_ref": ref,
                     "output_ref": f"{ref}&field={output}" if output else None, "status": status,
                     "citation": citation, "action": action, "time": time or datetime.now(timezone.utc).isoformat()})


def extract_with_model(facts, client, tool, page, activity, invoke, validate, warnings, evidence):
    source = facts.source
    model = getattr(client, "model", type(client).__name__)
    try:
        payload = invoke()
        if not isinstance(payload, dict):
            raise ValueError("Provider facts must be an object")
        # Reject values such as NaN before validation or publication.
        json.dumps(payload, allow_nan=False)
    except PROVIDER_ERRORS as exc:
        warnings.append(f"Page {page} {tool} unavailable ({type(exc).__name__})")
        record(activity, source, page, tool, "error", f"{tool} · {model} failed ({type(exc).__name__})",
               quote=evidence)
        return
    record(activity, source, page, tool, "succeeded", f"{tool} · {model} returned candidate facts",
           "candidates", evidence)
    validate(payload)


def validate_facts(facts, payload, allowed, page, activity, check, method):
    checked_count = 0
    for name, entries in payload.items():
        for entry in entries if isinstance(entries, list) else [None]:
            checked_count += 1
            output, quote = None, None
            if name in allowed and isinstance(entry, dict):
                quote, value, score = entry.get("quote"), entry.get("value"), entry.get("confidence", .75)
                if (isinstance(quote, str) and quote.strip() and type(score) in {int, float}
                        and 0 < score <= 1):
                    output = check(name, value, quote, min(score, .95))
            if output:
                record(activity, facts.source, page, "quote_validation", "accepted",
                       f"Accepted {output} from {method} after source quote validation", output, quote)
            else:
                record(activity, facts.source, page, "quote_validation", "rejected",
                       f"Rejected candidate from {method}: source quote or field did not validate")
    if not checked_count:
        record(activity, facts.source, page, "quote_validation", "no_facts",
               f"{method} returned no facts to validate")


def merge_translation(facts, translator, text, kind, page, activity=None, warnings=None):
    activity = [] if activity is None else activity
    warnings = [] if warnings is None else warnings
    normalized = compact(text)

    def check(name, value, quote, score):
        if compact(quote) in normalized and isinstance(value, str) and value.strip():
            facts.add(name, value, page, quote, score, method="llm_text")
            return name
        return None

    extract_with_model(facts, translator, "llm_text", page, activity,
                       lambda: translator.extract(text, kind=kind),
                       lambda payload: validate_facts(facts, payload, TRANSLATED_FIELDS, page, activity, check, "llm_text"),
                       warnings, text.strip()[:160])


def use_receiving_vision(facts, client, image, page, activity, warnings):
    handwriting = [entry for entry in facts.get("handwriting_candidate", []) if entry["page"] == page]
    if not handwriting:
        return

    def check(name, value, quote, score):
        if not isinstance(value, dict) or type(value.get("handwritten_quantity")) is not int:
            return None
        match = [entry for entry in handwriting if entry["value"]["material"] == value.get("material")
                 and entry["value"]["handwritten_quantity"] == value["handwritten_quantity"]
                 and compact(quote) == compact(entry["quote"]) and quantity(compact(quote)) == value["handwritten_quantity"]]
        if len(match) != 1:
            return None
        ocr = match[0]
        if any(entry["value"] == ocr["value"] and entry.get("method") == "llm_vision" for entry in facts.get(name, [])):
            return "handwritten_quantity"
        printed = ocr.get("printed_evidence")
        if printed and printed in facts.get("items", []):
            facts["items"].remove(printed)
        facts.add(name, ocr["value"], page, quote, score, locator="quantity_cell_crop", method="llm_vision",
                  **({"printed_evidence": printed} if printed else {}))
        return "handwritten_quantity"

    extract_with_model(facts, client, "llm_vision", page, activity,
                       lambda: checked_vision(client, image, "receiving").get("facts", {}),
                       lambda payload: validate_facts(facts, payload, {"items"}, page, activity, check, "llm_vision"),
                       warnings, handwriting[0]["quote"])


def bind_note_filename(facts, source):
    if not facts.get("delivery_note"):
        note = re.search(DELIVERY_NOTE, Path(source).stem, re.I)
        if note:
            facts.add("delivery_note", note[0].upper().replace(" ", "-"), 1, note[0], .5, locator="filename")


def finalize_receiving(facts):
    for item in facts.get("items", []):
        value = item["value"]
        correction = value.get("handwritten_quantity")
        if correction is None:
            continue
        locator = {key: item[key] for key in ("locator", "printed_evidence", "corroboration", "method") if key in item}
        facts.add("handwritten_quantity", correction, item["page"], item["quote"], item["confidence"], **locator)
        facts.add("handwritten_correction", {"material": value["material"], "line": value.get("line"),
                                            "printed_quantity": value.get("printed_quantity"),
                                            "corrected_quantity": correction},
                  item["page"], item["quote"], item["confidence"], **locator)


def extract_file(path, source, kind, ocr, vision=None, translator=None, activity=None):
    facts = Facts(source)
    activity = [] if activity is None else activity
    warnings, methods = [], set()
    if path.suffix.lower() == ".eml":
        with path.open("rb") as stream:
            message = BytesParser(policy=policy.default).parse(stream)
        for header in ("From", "To", "Date", "Subject", "Message-ID"):
            if header in message:
                raw = str(message[header])
                facts.add(header.lower().replace("-", "_"), raw, None, raw)
        body = message.get_body(preferencelist=("plain", "html"))
        if body is not None:
            text = body.get_content(errors="replace").strip()
            if text:
                facts.add("body", text, None, text[:450])
        return facts, 1, {"email"}, warnings
    if path.suffix.lower() == ".docx":
        text = docx_text(path)
        if text.strip():
            PARSERS[kind](facts, text, 1, 1.0) if kind in PARSERS else None
            methods.add("docx_text")
        return facts, 1, methods, warnings
    if path.suffix.lower() in {".txt", ".md"}:
        text = decode_csv(path.read_bytes())
        if text.strip():
            parser = PARSERS.get(kind)
            if parser:
                parser(facts, text, 1, 1.0)
            if kind == "context":
                facts.add("body", text, 1, text)
            methods.add("text")
        return facts, 1, methods, warnings
    if path.suffix.lower() == ".xlsx":
        workbook(facts, path)
        methods.add("workbook")
        if translator and kind == "price_list":
            texts = {}
            for entry in facts.get("conditions", []):
                texts.setdefault(entry["page"], []).append(entry["quote"])
            for page, lines in texts.items():
                initial = len(activity)
                merge_translation(facts, translator, "\n".join(lines), kind, page, activity, warnings)
                if any(event["tool"] == "llm_text" and event["status"] == "succeeded" for event in activity[initial:]):
                    methods.add("llm_text")
        return facts, len({item["page"] for item in facts.get("rows", [])}), methods, warnings

    with tempfile.TemporaryDirectory(prefix="soony-doc-") as folder:
        work = Path(folder)
        pdf = path.suffix.lower() == ".pdf"
        pages = pdf_text(path, work) if pdf else [""]
        for page, raw in enumerate(pages, 1):
            method, score, lines = "pdf_text", 1.0, ()
            if not raw.strip():
                method, score = "ocr", .75
                image = render_page(path, page, work) if pdf else path
                try:
                    raw, lines = ocr.read(image, receiving=kind == "receiving")
                except PROVIDER_ERRORS:
                    warnings.append(f"Page {page} has no readable text")
                    if kind in {"receiving", "notice"}:
                        record(activity, source, page, method, "error", "Independent OCR returned no readable text")
                    continue
            methods.add(method)
            PARSERS[kind](facts, raw, page, score)
            if kind in {"receiving", "notice"}:
                record(activity, source, page, method, "succeeded",
                       "Read source page with OCR" if method == "ocr" else "Read the PDF text layer",
                       "source_text", raw.strip()[:160])
            initial = len(activity)
            if kind == "receiving" and lines:
                add_cropped_quantities(facts, ocr, image, lines, page, activity)
                for entry in facts.get("handwriting_candidate", []):
                    if entry["page"] == page:
                        record(activity, source, page, "ocr_crop", "succeeded", "Read handwriting in the quantity cell",
                               "handwriting_candidate", entry["quote"])
                if vision:
                    use_receiving_vision(facts, vision, image, page, activity, warnings)
            if translator and kind in TEXT_KINDS:
                merge_translation(facts, translator, raw, kind, page, activity, warnings)
            methods.update(event["tool"] for event in activity[initial:]
                           if event["tool"] in {"llm_text", "llm_vision"} and event["status"] == "succeeded")
        if kind == "receiving":
            finalize_receiving(facts)
        return facts, len(pages), methods, warnings


def docx_text(path):
    """Paragraph text of a .docx (one line per paragraph, list items included)."""
    import re as _re
    from xml.etree import ElementTree as ET
    from zipfile import ZipFile
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    lines = []
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    for paragraph in root.iter(ns + "p"):
        text = "".join(node.text or "" for node in paragraph.iter(ns + "t"))
        text = _re.sub(r"\s+", " ", text).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def add_cropped_quantities(facts, ocr, image, lines, page, activity):
    material_evidence = {entry["value"]: entry for entry in facts.get("material", []) if entry["page"] == page}
    materials = set(material_evidence)
    for material, (units, quote) in ocr.missing_quantities(image, lines, materials).items():
        matches = [entry for entry in facts.get("items", [])
                   if entry["page"] == page and entry["value"]["material"] == material]
        if matches:
            if len(matches) != 1 or "handwritten_quantity" in matches[0]["value"] or matches[0]["value"]["quantity"] == units:
                continue
            facts["items"].remove(matches[0])
        facts.add("items", {"material": material, "printed_quantity": units, "quantity": units},
                  page, quote, .65, locator="quantity_cell", material_evidence=material_evidence[material])
        record(activity, facts.source, page, "ocr_quantity_cell", "succeeded", f"Read the quantity column for {material}",
               "items", quote)
    for material, (units, quote) in ocr.handwritten_quantities(image, lines, materials).items():
        matches = [entry for entry in facts.get("items", [])
                   if entry["page"] == page and entry["value"]["material"] == material]
        if len(matches) > 1:
            continue
        printed = matches[0] if matches else None
        item = {"material": material, "handwritten_quantity": units, "quantity": units}
        locator = {"locator": "quantity_cell_crop"}
        if printed:
            value = printed["value"]
            if "handwritten_quantity" in value or value["printed_quantity"] == units:
                continue
            item["printed_quantity"] = value["printed_quantity"]
            locator["printed_evidence"] = printed
        facts.add("handwriting_candidate", item, page, quote, .65, **locator)
