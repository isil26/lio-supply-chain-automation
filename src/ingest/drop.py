"""Readers for the formats added by the 21 Nov 19:25 portal drop.

Each reader yields ``Record`` rows with the original sheet/row (or item index) so every
value in the store keeps its source citation. They are tolerant: unknown columns and extra
sheets are ignored, and German thousands separators ("554.000") are understood.
"""
import io
import json
import re
from datetime import datetime, timedelta

from openpyxl import load_workbook

from . import models

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def thousands(value):
    """'554.000' is a German thousands separator, not a decimal. Plain numbers pass through."""
    if isinstance(value, str) and re.fullmatch(r"\d{1,3}(\.\d{3})+", value.strip()):
        return value.strip().replace(".", "")
    return value


def cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def text_key(text):
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def status_as_of(title, modified):
    """Resolve 'Saturday 13:00' against the workbook modification date; fall back to the label."""
    match = re.search(r"(" + "|".join(WEEKDAYS) + r")\s+(\d{1,2}):(\d\d)", title or "", re.I)
    if match and isinstance(modified, datetime):
        target = WEEKDAYS.index(match[1].lower())
        stamp = modified.replace(hour=int(match[2]), minute=int(match[3]), second=0, microsecond=0)
        stamp -= timedelta(days=(stamp.weekday() - target) % 7)
        return stamp.isoformat()
    if isinstance(modified, datetime):
        return modified.isoformat()
    return title or None


def read_launch_status(source, body, dataset):
    from .readers import Record
    with io.BytesIO(body) as stream:
        book = load_workbook(stream, read_only=True, data_only=True)
        try:
            modified = book.properties.modified
            found = False
            for sheet in book:
                grid = list(sheet.iter_rows(values_only=True))
                title = next((cell_text(row[0]) for row in grid if row and row[0]), "")
                heads = None
                for number, row in enumerate(grid, 1):
                    cells = [cell_text(cell) for cell in row]
                    if not any(cells):
                        continue
                    lowered = [text_key(cell) for cell in cells]
                    if heads is None:
                        if "product" in lowered and "packed" in lowered:
                            heads, found = lowered, True
                        elif [cell for cell in lowered if cell] == ["note"]:
                            heads = ["note"]
                        continue
                    if heads == ["note"]:
                        yield Record(models.LaunchStatus(kind="note", note=cells[0]), sheet.title, number)
                        continue
                    raw = dict(zip(heads, cells))
                    if not raw.get("product"):
                        continue
                    yield Record(models.LaunchStatus(
                        kind="edition", edition=raw.get("name") or None, product_id=raw["product"],
                        day_one_demand=thousands(raw.get("dayonedemand") or "") or None,
                        packed=thousands(raw.get("packed") or "") or None,
                        still_to_pack=thousands(raw.get("stilltopack") or "") or None,
                        rate_per_hour=thousands(raw.get("rateperhour") or "") or None,
                        line_status=raw.get("linestatus") or None,
                        as_of=status_as_of(title, modified)), sheet.title, number)
            if not found:
                raise ValueError("no worksheet has the launch status header")
        finally:
            book.close()


def read_supplier_json(source, body, dataset):
    """Vendor master v2 export (SAP XK03 JSON). Nested fields map to flat supplier columns."""
    from .readers import Record
    data = json.loads(body.decode("utf-8-sig"))
    info = data.get("supplier") or data
    address, terms = info.get("address") or {}, info.get("terms") or {}
    qualification, contact = info.get("qualification") or {}, info.get("contact") or {}
    geo = address.get("geo") or {}
    values = {
        "supplier_id": info.get("supplierId") or info.get("vendorNo"), "name": info.get("name"),
        "legal_name": info.get("legalName"), "category": info.get("category"),
        "country": address.get("country"), "city": address.get("city"),
        "lat": geo.get("lat"), "lon": geo.get("lng", geo.get("lon")),
        "currency": terms.get("currency"), "payment_terms": terms.get("payment"),
        "incoterm": terms.get("incoterm"), "supplier_since": info.get("since"),
        "status": info.get("status"), "qualification_status": qualification.get("status"),
        "qualification_released_on": qualification.get("releasedOn"),
        "qualification_valid_until": qualification.get("validUntil"),
        "qualification_extended_by": qualification.get("extendedBy"),
        "vendor_no": info.get("vendorNo"), "contact_name": contact.get("name"),
        "contact_email": contact.get("email"), "phone": contact.get("phone"),
        "preferred_language": contact.get("language"), "notes": info.get("notes"),
    }
    values = {key: value for key, value in values.items() if value not in (None, "")}
    yield Record(dataset.model.model_validate(values), "", 1)


def read_news(source, body, dataset):
    from .readers import Record
    data = json.loads(body.decode("utf-8-sig"))
    items = data.get("items") if isinstance(data, dict) else data
    for index, item in enumerate(items or [], 1):
        yield Record(models.NewsItem(
            news_id=item.get("id") or f"item-{index}", published_at=item.get("published_at"),
            source_name=item.get("source"), headline=item["headline"], summary=item.get("summary"),
            regions="|".join(item.get("regions") or []) or None,
            tags="|".join(item.get("tags") or []) or None,
        ), "items", index)
