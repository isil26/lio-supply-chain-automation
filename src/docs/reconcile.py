"""Compare extracted facts with independent ERP evidence on every run."""

import csv
import re
from collections import defaultdict

from .extract import finalize_receiving
from .schema import Facts, decimal_number, evidence, iso_date

PO_FIELDS = {
    "po": ("po_number", "EBELN"),
    "line": ("po_line", "EBELP"),
    "material": ("material_id", "MATNR"),
    "quantity": ("quantity", "MENGE"),
    "unit_price": ("unit_price", "NETPR"),
    "currency": ("currency", "WAERS"),
    "promised_date": ("promised_date", "ZZCONF"),
    "incoterm": ("incoterm", "INCO1"),
    "supplier_id": ("supplier_id", "LIFNR"),
}
GR_FIELDS = {
    "po": ("po_number", "EBELN"),
    "line": ("po_line", "EBELP"),
    "material": ("material_id", "MATNR"),
    "quantity": ("qty_received", "MENGE"),
    "delivery_note": ("delivery_note", "LFSNR"),
    "supplier_id": ("supplier_id", "LIFNR"),
}


def table_rows(data, pattern, names, manifest):
    for path in sorted((data / "soony/erp").glob(pattern), key=lambda p: ("legacy" not in p.name, p.name)):
        source = path.relative_to(data).as_posix()
        if not path.resolve().is_relative_to(data) or (manifest is not None and source not in manifest):
            continue
        with path.open(encoding="utf-8-sig", newline="") as stream:
            sample = stream.readline()
            stream.seek(0)
            delimiter = ";" if sample.count(";") > sample.count(",") else ","
            reader = csv.DictReader(stream, delimiter=delimiter)
            for row in reader:
                values = {}
                for name, columns in names.items():
                    for col in columns:
                        raw = (row.get(col) or "").strip()
                        if not raw:
                            continue
                        value = raw
                        if name == "line":
                            if not raw.isdigit():
                                break
                            value = int(raw) // 10 if col == "EBELP" else int(raw)
                        if name in {"quantity", "unit_price"}:
                            value = decimal_number(raw, decimal_comma=delimiter == ";")
                        if name == "promised_date":
                            value = iso_date(raw, day_first=False)
                        if name == "supplier_id" and raw.isdigit():
                            value = f"SUP-{int(raw):04d}"
                        if value is not None:
                            # One field per cell, with physical line number and original cell text.
                            values[name] = evidence(value, source, None, raw, row=reader.line_num, column=col,
                                                    confidence=1.0)
                        break
                yield values


def value(fields, name):
    item = fields.get(name)
    return item["value"] if item else None


def first(fields, name):
    entries = fields.get(name)
    return entries[0] if entries else None


def normalize_terms(value):
    return " ".join(re.findall(r"[\w]+", value.upper()))


class ERP:
    def __init__(self, data, documents, manifest=None):
        self.orders = defaultdict(dict)
        self.receipts = defaultdict(list)
        self.aliases = {}
        for doc in documents:
            for item in doc["fields"].get("aliases", []):
                part = item["value"]
                self.aliases[(doc["supplier_id"], part["supplier_material"])] = item
        for row in table_rows(data, "purchase_orders*.csv", PO_FIELDS, manifest):
            po, line = value(row, "po"), value(row, "line")
            if po and line is not None:
                self.orders[po][line] = row
        for row in table_rows(data, "goods_receipts*.csv", GR_FIELDS, manifest):
            note = value(row, "delivery_note")
            if note:
                self.receipts[note.upper()].append(row)

    def apply_verified_crops(self, doc):
        """Promote OCR digits only when distinct PO and GR evidence corroborate the reading."""
        fields = doc["fields"]
        candidates = fields.get("handwriting_candidate", [])
        if not candidates or fields.get("handwritten_correction"):
            return
        po, note = first(fields, "po"), first(fields, "delivery_note")
        if not po or not note or note.get("locator") == "filename":
            return
        po_number = po["value"]
        receipts = self.receipts.get(note["value"], [])
        facts = Facts(doc["source"])
        facts.update(fields)
        for candidate in candidates:
            printed = candidate.get("printed_evidence")
            if not printed:
                continue
            item = candidate["value"]
            matches = [row for row in receipts if value(row, "po") == po_number
                       and value(row, "material") == item["material"]]
            if len(matches) != 1:
                continue
            receipt = matches[0]
            order = self.orders.get(po_number, {}).get(value(receipt, "line"))
            if (not order or value(order, "material") != item["material"] or
                    value(order, "quantity") != item["handwritten_quantity"] or
                    value(receipt, "quantity") != item.get("printed_quantity")):
                continue
            facts["items"] = [entry for entry in facts.get("items", []) if entry != printed]
            facts["items"].append(dict(candidate, corroboration=[order["quantity"], receipt["quantity"]]))
        finalize_receiving(facts)
        doc["fields"] = facts

    def flags(self, doc):
        flags = []
        fields, supplier = doc["fields"], doc["supplier_id"]
        if doc["kind"] not in {"confirmation", "receiving"}:
            return flags
        po, incoterm = first(fields, "po"), first(fields, "incoterm")
        po_number = value({"po": po}, "po")
        po_rows = self.orders.get(po_number, {})
        note = first(fields, "delivery_note")
        note_rows = self.receipts.get(note["value"], []) if note else []
        erp_suppliers = {value(row, "supplier_id") for row in (*po_rows.values(), *note_rows)} - {None}
        if not supplier and len(erp_suppliers) == 1:
            supplier = next(iter(erp_suppliers))

        def flag(code, name, document, erp=None, line=None, alias=None):
            entry = {"code": code, "field": name, "line": line, "document": document, "erp": erp}
            if alias:
                entry["material_alias"] = alias
            flags.append(entry)

        if po and not po_rows and self.orders:
            flag("po_not_found", "po", po)
        if doc["kind"] == "receiving" and po and note_rows:
            receipt_pos = [row["po"] for row in note_rows if "po" in row]
            if receipt_pos and all(item["value"] != po_number for item in receipt_pos):
                flag("goods_receipt_mismatch", "po", po, receipt_pos[0])

        for item in fields.get("items", []):
            details = item["value"]
            alias = self.aliases.get((supplier, details["material"]))
            material = alias["value"]["material"] if alias else details["material"]
            line = details.get("line")
            if doc["kind"] == "confirmation":
                erp = po_rows.get(line)
                if not erp:
                    if po_rows:
                        flag("po_line_not_found", "line", dict(item, value=line), line=line)
                    continue
                compare = ("material", "quantity", "currency", "unit_price", "promised_date")
                for name in compare:
                    actual = material if name == "material" else details.get(name)
                    expected = value(erp, name)
                    if name == "unit_price" and value(erp, "currency") not in (None, details.get("currency")):
                        continue
                    if actual is not None and expected is not None and actual != expected:
                        flag("po_mismatch", name, dict(item, value=actual), erp[name], line,
                             alias if name == "material" else None)
                if incoterm and erp.get("incoterm") and normalize_terms(incoterm["value"]) != normalize_terms(erp["incoterm"]["value"]):
                    flag("po_mismatch", "incoterm", incoterm, erp["incoterm"], line)
                continue

            number = details.get("quantity")
            matching_gr = [row for row in note_rows if value(row, "material") == material
                           and (line is None or value(row, "line") == line)
                           and (po_number is None or value(row, "po") == po_number)]
            gr = matching_gr[0] if len(matching_gr) == 1 else None
            order = po_rows.get(line) if line is not None else None
            if order is None and line is None:
                choices = [row for row in po_rows.values() if value(row, "material") == material]
                order = choices[0] if len(choices) == 1 else None
                if order is None and gr and value(gr, "po") == po_number:
                    order = po_rows.get(value(gr, "line"))
            if order:
                line = value(order, "line")
                if material != value(order, "material"):
                    flag("po_mismatch", "material", dict(item, value=material), order.get("material"), line, alias)
                ordered = value(order, "quantity")
                if number is not None and ordered is not None and number != ordered:
                    code = "partial_delivery" if number < ordered else "po_mismatch"
                    flag(code, "quantity", dict(item, value=number), order["quantity"], line)
            elif po_rows and not any(value(row, "material") == material for row in po_rows.values()):
                flag("po_material_not_found", "material", dict(item, value=material), line=line, alias=alias)
            if gr and number is not None and value(gr, "quantity") is not None and number != value(gr, "quantity"):
                flag("goods_receipt_mismatch", "quantity", dict(item, value=number),
                     gr["quantity"], line or value(gr, "line"))
        return flags
