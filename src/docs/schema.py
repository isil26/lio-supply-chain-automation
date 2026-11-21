"""Shared evidence and value normalization for document parsers."""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

ITEM_CODE = r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+){2,}"
QUANTITY = r"(?:\d{1,3}(?:[., \u00a0\u202f]\d{3})+|\d+)"
ISO_DATE = r"\d{4}-\d{2}-\d{2}"
PO_NUMBER = r"\b\d{10}\b"
DELIVERY_NOTE = r"\b(?:DN|WZ|SN)[-– ]\d{6}[-– ]\d{3}\b"


def evidence(value, source_file, page, quote, confidence=1.0, **locator):
    return {
        "value": value,
        "source_file": source_file,
        "page": page,
        "quote": quote.strip(),
        "confidence": confidence,
        **locator,
    }


class Facts(dict):
    def __init__(self, source):
        super().__init__()
        self.source = source

    def add(self, name, value, page, quote, confidence=1.0, **locator):
        if value is None or not quote.strip():
            return
        field = evidence(value, self.source, page, quote, confidence, **locator)
        entries = self.setdefault(name, [])
        if field not in entries:
            entries.append(field)

    def first(self, name):
        entries = self.get(name, [])
        return entries[0]["value"] if entries else None


def quantity(raw):
    token = str(raw).strip()
    if not re.fullmatch(QUANTITY, token):
        return None
    return int(re.sub(r"\D", "", token))


def decimal_number(raw, decimal_comma=False):
    token = re.sub(r"\s", "", str(raw))
    token = token.replace(".", "").replace(",", ".") if decimal_comma else token.replace(",", "")
    try:
        result = Decimal(token)
    except InvalidOperation:
        return None
    if result.is_finite():
        return int(result) if result == result.to_integral_value() else float(result)
    return None


def iso_date(raw, day_first=True):
    formats = ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%Y %H:%M")
    formats += ("%d/%m/%Y", "%m/%d/%Y") if day_first else ("%m/%d/%Y", "%d/%m/%Y")
    for fmt in formats:
        try:
            parsed = datetime.strptime(raw.strip(), fmt)
        except ValueError:
            continue
        return parsed.isoformat(timespec="minutes") if "%H" in fmt else parsed.date().isoformat()
    return None


def search(facts, name, pattern, text, page, confidence=1.0, convert=str):
    for match in re.finditer(pattern, text, re.I | re.M):
        value = match[1] if match.lastindex else match[0]
        facts.add(name, convert(value), page, match[0], confidence)
