"""Extract facts from one input document without consulting ERP."""

import math
import re
import subprocess
import tempfile
from pathlib import Path

from .media import checked_vision, pdf_text, render_page
from .parsers import PARSERS, workbook
from .schema import DELIVERY_NOTE, ITEM_CODE, PO_NUMBER, Facts, iso_date, quantity

TEXT_KINDS = {"notice", "contract", "price_list"}
TRANSLATED_FIELDS = {
    "what", "impact", "effective_at", "ends_at", "capacity", "penalties", "force_majeure",
    "lead_time", "moq", "payment", "liability", "qualification", "term", "translation_en",
}
PROVIDER_ERRORS = (OSError, ValueError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError)


def compact(text):
    return " ".join(text.split())


def candidates(payload, allowed):
    if not isinstance(payload, dict):
        raise ValueError("Provider facts must be an object")
    for name, entries in payload.items():
        if name not in allowed or not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            quote, value = entry.get("quote"), entry.get("value")
            score = entry.get("confidence", .75)
            if (not isinstance(quote, str) or not quote.strip() or value is None or
                    type(score) not in {int, float} or not math.isfinite(score) or not 0 < score <= 1):
                continue
            yield name, value, quote, min(score, .95)


def merge_translation(facts, translator, text, kind, page):
    normalized = compact(text)
    for name, value, quote, score in candidates(translator.extract(text, kind=kind), TRANSLATED_FIELDS):
        if compact(quote) in normalized:
            facts.add(name, value, page, quote, score)


def receiving_vision(facts, payload, page):
    allowed = {"po", "delivery_note", "document_date", "received_date", "damage", "items"}
    for name, value, quote, score in candidates(payload, allowed):
        if name == "items":
            if not isinstance(value, dict):
                continue
            material = value.get("material")
            if not isinstance(material, str) or not re.fullmatch(ITEM_CODE, material.upper()):
                continue
            material = material.upper()
            item = {"material": material}
            for key in ("printed_quantity", "handwritten_quantity"):
                count = value.get(key)
                if type(count) is int and count >= 0 and any(
                    quantity(token) == count for token in re.findall(r"\d+(?:[., \u00a0\u202f]\d{3})*", quote)
                ):
                    item[key] = count
            if "printed_quantity" not in item and "handwritten_quantity" not in item:
                continue
            if type(value.get("line")) is int and value["line"] > 0:
                item["line"] = value["line"]
            item["quantity"] = item.get("handwritten_quantity", item.get("printed_quantity"))
            facts.add(name, item, page, quote, score)
        elif isinstance(value, str):
            if name == "po" and (not re.fullmatch(PO_NUMBER, value) or value not in quote):
                continue
            if name == "delivery_note" and not re.fullmatch(DELIVERY_NOTE, value, re.I):
                continue
            if name in {"document_date", "received_date"} and not iso_date(value):
                continue
            facts.add(name, value, page, quote, score)


def merge_receiving(facts, modeled, page):
    for name, entries in modeled.items():
        if name == "items":
            if any(item["value"].get("line") for item in entries):
                # A model that identified separate PO lines provides stronger row identity.
                modeled_materials = {item["value"]["material"] for item in entries if item["value"].get("line")}
                facts[name] = [item for item in facts.get(name, [])
                               if item["value"]["material"] not in modeled_materials]
            for item in entries:
                value = item["value"]
                matching = [old for old in facts.get(name, [])
                            if old["value"]["material"] == value["material"] and old["page"] == page]
                if "handwritten_quantity" in value and len(matching) == 1:
                    previous = matching[0]
                    facts[name].remove(previous)
                    if "printed_quantity" not in value and "printed_quantity" in previous["value"]:
                        value["printed_quantity"] = previous["value"]["printed_quantity"]
                        item["printed_evidence"] = previous
                elif matching:
                    continue
                facts.setdefault(name, []).append(item)
        else:
            facts[name] = entries


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
        locator = {key: item[key] for key in ("locator", "printed_evidence", "corroboration") if key in item}
        facts.add("handwritten_quantity", correction, item["page"], item["quote"], item["confidence"], **locator)
        facts.add("handwritten_correction", {"material": value["material"], "line": value.get("line"),
                                            "printed_quantity": value.get("printed_quantity"),
                                            "corrected_quantity": correction},
                  item["page"], item["quote"], item["confidence"], **locator)


def extract_file(path, source, kind, ocr, vision=None, translator=None):
    facts = Facts(source)
    warnings, methods = [], set()
    if path.suffix.lower() == ".xlsx":
        workbook(facts, path)
        methods.add("workbook")
        if translator and kind == "price_list":
            texts = {}
            for entry in facts.get("conditions", []):
                texts.setdefault(entry["page"], []).append(entry["quote"])
            for page, lines in texts.items():
                try:
                    merge_translation(facts, translator, "\n".join(lines), kind, page)
                    methods.add("translation")
                except PROVIDER_ERRORS as exc:
                    warnings.append(f"Page {page} translation unavailable ({type(exc).__name__})")
        return facts, len({item["page"] for item in facts.get("rows", [])}), methods, warnings

    with tempfile.TemporaryDirectory(prefix="soony-doc-") as folder:
        work = Path(folder)
        pdf = path.suffix.lower() == ".pdf"
        pages = pdf_text(path, work) if pdf else [""]
        for page, raw in enumerate(pages, 1):
            score = 1.0
            modeled = Facts(source)
            lines = ()
            if raw.strip():
                methods.add("pdf_text")
            else:
                image = render_page(path, page, work) if pdf else path
                if vision:
                    try:
                        result = checked_vision(vision, image, kind)
                        raw = result.get("text", "")
                        if kind == "receiving":
                            receiving_vision(modeled, result.get("facts", {}), page)
                        if raw.strip() or modeled:
                            methods.add("vision")
                            score = .8
                    except PROVIDER_ERRORS as exc:
                        warnings.append(f"Page {page} vision unavailable ({type(exc).__name__})")
                if not raw.strip() and not modeled:
                    try:
                        raw, lines = ocr.read(image, receiving=kind == "receiving")
                    except PROVIDER_ERRORS:
                        warnings.append(f"Page {page} has no readable text")
                        continue
                    methods.add("ocr")
                    score = .75
            if raw.strip():
                PARSERS[kind](facts, raw, page, score)
            if kind == "receiving":
                if modeled:
                    merge_receiving(facts, modeled, page)
                if lines:
                    add_cropped_quantities(facts, ocr, image, lines, page)
            if translator and kind in TEXT_KINDS and raw.strip():
                try:
                    merge_translation(facts, translator, raw, kind, page)
                    methods.add("translation")
                except PROVIDER_ERRORS as exc:
                    warnings.append(f"Page {page} translation unavailable ({type(exc).__name__})")
        if kind == "receiving":
            finalize_receiving(facts)
        return facts, len(pages), methods, warnings


def add_cropped_quantities(facts, ocr, image, lines, page):
    material_evidence = {entry["value"]: entry for entry in facts.get("material", []) if entry["page"] == page}
    materials = set(material_evidence)
    known = {entry["value"]["material"] for entry in facts.get("items", []) if entry["page"] == page}
    for material, (units, quote) in ocr.missing_quantities(image, lines, materials - known).items():
        facts.add("items", {"material": material, "printed_quantity": units, "quantity": units},
                  page, quote, .65, locator="quantity_cell", material_evidence=material_evidence[material])
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
