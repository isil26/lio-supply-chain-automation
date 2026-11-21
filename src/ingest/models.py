"""Canonical ingestion records and source value normalization."""

import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ValidationInfo, field_validator


def identifier(value: object) -> str:
    return str(value).strip().upper()


def supplier_id(value: object) -> str:
    code = identifier(value)
    match = re.fullmatch(r"(?:SUP[ -]?)?([0-9]+)", code)
    return f"SUP-{int(match[1]):04d}" if match else code


def decimal_value(value: object) -> Decimal:
    number = re.sub(r"[\s'’]", "", str(value))
    if "," in number and "." in number:
        if number.rfind(",") > number.rfind("."):
            number = number.replace(".", "").replace(",", ".")
        else:
            number = number.replace(",", "")
    elif re.fullmatch(r"[+-]?\d{1,3}(,\d{3}){2,}", number):
        number = number.replace(",", "")
    else:
        number = number.replace(",", ".")
    try:
        return Decimal(number)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal number") from exc


def calendar_date(value: object, info: ValidationInfo) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    value = str(value)
    if value.isascii() and value.isdigit() and len(value) == 8:
        return datetime.strptime(value, "%Y%m%d").date()
    context = info.context or {}
    epoch = context.get("excel_epoch")
    if epoch and re.fullmatch(r"\d{1,7}(\.\d+)?", value):
        days = int(Decimal(value))
        if epoch == date(1899, 12, 30) and 0 < days < 60:
            days += 1  # Excel's 1900 date system includes a fictitious leap day.
        try:
            return epoch + timedelta(days=days)
        except OverflowError as exc:
            raise ValueError("invalid Excel date serial") from exc
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        pass

    formats = ["%Y/%m/%d", "%d.%m.%Y", "%d-%m-%Y"]
    slash_formats = ["%d/%m/%Y", "%m/%d/%Y"]
    if context.get("month_first"):
        slash_formats.reverse()
    for fmt in formats + slash_formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError("unrecognized calendar date")


def code(value: str) -> str:
    return re.sub(r"[\s-]+", "_", value.strip().casefold())


def id_list(value: object) -> str:
    return "|".join(identifier(part) for part in re.split(r"[|,;]", str(value)) if part.strip())


Identifier = Annotated[str, BeforeValidator(identifier)]
SupplierId = Annotated[str, BeforeValidator(supplier_id)]
Number = Annotated[Decimal, BeforeValidator(decimal_value)]
Integer = Annotated[int, BeforeValidator(decimal_value)]
Date = Annotated[date, BeforeValidator(calendar_date)]
Code = Annotated[str, BeforeValidator(code)]
IdList = Annotated[str, BeforeValidator(id_list)]


class PurchaseOrder(BaseModel):
    po_number: Identifier
    po_line: Integer
    supplier_id: SupplierId
    material_id: Identifier
    plant: Identifier | None = None
    quantity: Number
    unit_price: Number | None = None
    currency: Identifier | None = None
    order_date: Date
    requested_date: Date | None = None
    promised_date: Date | None = None
    actual_delivery_date: Date | None = None
    status: str | None = None
    status_raw: str | None = None
    buyer: str | None = None
    incoterm: str | None = None
    note: str | None = None

    @field_validator("status")
    @classmethod
    def normalize_status(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = code(value)
        return {"gl": "delivered", "lo": "cancelled", "canceled": "cancelled"}.get(
            normalized, normalized
        )


class GoodsReceipt(BaseModel):
    gr_number: Identifier
    gr_date: Date
    po_number: Identifier | None = None
    po_line: Integer | None = None
    supplier_id: SupplierId | None = None
    material_id: Identifier
    plant: Identifier | None = None
    qty_ordered: Number | None = None
    qty_received: Number
    delivery_note: str | None = None
    inspector: str | None = None
    remark: str | None = None


class Stock(BaseModel):
    snapshot_date: Date
    site: Identifier
    material_id: Identifier
    batch: Identifier | None = None
    quantity: Number
    uom: Identifier | None = None
    safety_stock: Number | None = None
    weeks_of_cover: Number | None = None
    last_count: Date | None = None


class Shipment(BaseModel):
    shipment_id: Identifier
    carrier_id: Identifier | None = None
    mode: Code | None = None
    reference: str | None = None
    supplier_id: SupplierId | None = None
    supplier_name: str | None = None
    po_numbers: IdList | None = None
    material_ids: IdList | None = None
    quantity: Number | None = None
    route_id: Identifier | None = None
    origin: Identifier | None = None
    destination: Identifier | None = None
    via: Identifier | None = None
    dest_site: Identifier | None = None
    etd: Date | None = None
    eta: Date | None = None
    status: Code | None = None
    status_raw: str | None = None
    last_lat: Number | None = None
    last_lon: Number | None = None
    updated_at: datetime | None = None
    note: str | None = None


class BomItem(BaseModel):
    parent_id: Identifier
    child_id: Identifier
    qty_per: Number
    valid_from: Date | None = None
    valid_to: Date | None = None


class Component(BaseModel):
    component_id: Identifier
    description: str | None = None
    category: str | None = None
    uom: Identifier | None = None
    abc_class: Identifier | None = None
    critical: bool | None = None
    drawing_rev: str | None = None


class Product(BaseModel):
    product_id: Identifier
    name: str | None = None
    product_line: str | None = None
    lifecycle: Code | None = None
    launch_date: Date | None = None
    plan_weekly_units: Integer | None = None
    day_one_qty: Integer | None = None
    plants: IdList | None = None
    std_cost_eur: Number | None = None
    valid_from: Date | None = None


class Supplier(BaseModel):
    supplier_id: SupplierId
    name: str
    legal_name: str | None = None
    category: str | None = None
    country: Identifier | None = None
    city: str | None = None
    lat: Number | None = None
    lon: Number | None = None
    currency: Identifier | None = None
    payment_terms: str | None = None
    incoterm: str | None = None
    supplier_since: Date | None = None
    status: Code | None = None
    qualification_status: Code | None = None
    qualification_released_on: Date | None = None
    qualification_valid_until: Date | None = None
    qualification_extended_by: str | None = None
    vendor_no: Integer | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    phone: str | None = None
    preferred_language: Code | None = None
    notes: str | None = None


class SupplierComponent(BaseModel):
    supplier_id: SupplierId
    component_id: Identifier
    description: str | None = None
    category: str | None = None
    share: Number | None = None
    unit_price: Number | None = None
    currency: Identifier | None = None
    lead_time_days: Integer | None = None
    moq: Number | None = None
    primary: bool | None = None
    note: str | None = None


class Route(BaseModel):
    route_id: Identifier
    origin: Identifier
    destination: Identifier
    mode: Code | None = None
    carrier_id: Identifier | None = None
    transit_days: Number | None = None
    via: Identifier | None = None


class Packout(BaseModel):
    date: Date
    site: Identifier
    product_id: Identifier
    line: str | None = None
    units_packed: Integer


class LaunchStatus(BaseModel):
    """One edition line (kind=edition) or one note (kind=note) of launch_status.xlsx."""
    kind: str
    edition: str | None = None
    product_id: Identifier | None = None
    day_one_demand: Integer | None = None
    packed: Integer | None = None
    still_to_pack: Integer | None = None
    rate_per_hour: Integer | None = None
    line_status: str | None = None
    note: str | None = None
    as_of: str | None = None  # ISO local timestamp from workbook properties or title


class BomChange(BaseModel):
    change_id: Identifier
    parent_id: Identifier
    child_id: Identifier
    action: Code | None = None
    qty_per_old: Number | None = None
    qty_per_new: Number | None = None
    rev_old: str | None = None
    rev_new: str | None = None
    use_up_old_rev: bool | None = None
    effective_from: Date | None = None
    reason: str | None = None


class ComponentChange(BaseModel):
    component_id: Identifier
    field: Code
    old: str | None = None
    new: str | None = None
    changed_by: str | None = None


class SupplierComponentChange(BaseModel):
    supplier_id: SupplierId
    component_id: Identifier
    action: Code | None = None
    lead_time_days_old: Integer | None = None
    lead_time_days_new: Integer | None = None
    share: Number | None = None
    primary: bool | None = None
    note: str | None = None


class NewsItem(BaseModel):
    news_id: str
    published_at: datetime | None = None
    source_name: str | None = None
    headline: str
    summary: str | None = None
    regions: str | None = None
    tags: str | None = None
