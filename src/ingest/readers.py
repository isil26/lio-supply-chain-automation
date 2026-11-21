"""Find source rows by header and preserve their original locations."""

import csv
import io
import posixpath
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from pydantic import BaseModel, ValidationError

from . import models


@dataclass(frozen=True)
class Dataset:
    table: str
    model: type[BaseModel]
    pattern: str
    aliases: dict[str, tuple[str, ...]]

    def matches(self, path: PurePosixPath) -> bool:
        return len(path.parts) == self.pattern.count("/") + 1 and path.match(self.pattern)


MATERIAL = ("component", "component_id", "material", "material_number", "matnr", "sku")
SUPPLIER = ("supplier", "vendor", "vendor_id", "vendor_number", "supplier_code", "lifnr")
PO = ("purchase_order", "purchase_order_number", "order_number", "po", "po_no", "ebeln")
LINE = ("line", "line_number", "line_item", "item_number", "po_item", "ebelp")
SITE = ("plant", "site_id", "warehouse", "werks")
QUANTITY = ("qty", "order_quantity", "menge")
ORIGIN = ("from", "origin_port", "origin_locode")
DESTINATION = ("to", "destination_port", "destination_locode")

DATASETS = (
    Dataset("purchase_orders", models.PurchaseOrder, "soony/erp/purchase_orders*.csv", {
        "po_number": PO, "po_line": LINE, "supplier_id": SUPPLIER, "material_id": MATERIAL,
        "plant": ("site", *SITE), "quantity": QUANTITY, "unit_price": ("net_price", "price", "netpr"),
        "currency": ("currency_code", "waers"), "order_date": ("po_date", "created_on", "bedat"),
        "requested_date": ("required_date", "requested_delivery", "eindt"),
        "promised_date": ("confirmed_date", "confirmed_delivery", "zzconf"),
        "actual_delivery_date": ("delivery_date", "received_date", "wedat"),
        "status": ("order_status", "status_code", "zzstat"), "buyer": ("purchaser", "ernam"),
        "incoterm": ("incoterms", "inco1"), "note": ("notes", "comment", "remark"),
    }),
    Dataset("goods_receipts", models.GoodsReceipt, "soony/erp/goods_receipts*.csv", {
        "gr_number": ("receipt_id", "receipt_number", "gr_no", "mblnr"),
        "gr_date": ("receipt_date", "posting_date", "budat"),
        "po_number": PO, "po_line": LINE, "supplier_id": SUPPLIER, "material_id": MATERIAL,
        "plant": ("site", *SITE), "qty_ordered": ("ordered_qty", "ordered_quantity"),
        "qty_received": ("received_qty", "received_quantity", "quantity", "qty", "menge"),
        "delivery_note": ("delivery_note_number", "delivery_note_no", "lief_nr"),
        "remark": ("note", "notes", "comment"),
    }),
    Dataset("stock", models.Stock, "soony/erp/stock_snapshot*.csv", {
        "snapshot_date": ("date", "as_of", "as_of_date"), "site": SITE, "material_id": MATERIAL,
        "batch": ("batch_id", "lot", "charg"), "quantity": ("on_hand", "on_hand_qty", *QUANTITY),
        "uom": ("unit", "unit_of_measure", "meins"), "safety_stock": ("safety_qty", "eisbe"),
        "weeks_of_cover": ("weeks_cover", "weeks_coverage", "woc"),
        "last_count": ("last_count_date", "last_stocktake"),
    }),
    Dataset("open_shipments", models.Shipment, "soony/erp/open_shipments*.csv", {
        "shipment_id": ("shipment", "shipment_number", "shipment_no"),
        "carrier_id": ("carrier", "logistics_provider"), "mode": ("transport_mode",),
        "reference": ("container_awb", "container", "awb", "tracking_number"),
        "supplier_id": ("vendor_id", "supplier_code", "lifnr"),
        "supplier_name": ("supplier", "vendor", "vendor_name"),
        "po_numbers": ("pos", "po_ids", "purchase_orders", *PO, "po_number"),
        "material_ids": ("materials", "components", *MATERIAL, "material_id"),
        "quantity": ("shipment_qty", "shipped_qty", "quantity_shipped", "qty"),
        "origin": ORIGIN, "destination": DESTINATION, "dest_site": ("destination_site",),
        "etd": ("departure", "departure_date", "estimated_departure"),
        "eta": ("arrival", "arrival_date", "estimated_arrival"),
        "status": ("shipment_status",), "last_lat": ("latitude", "lat"),
        "last_lon": ("longitude", "lon"), "updated_at": ("last_updated",),
        "note": ("notes", "comment", "comments", "remark"),
    }),
    Dataset("bom", models.BomItem, "soony/master/bom*.csv", {
        "parent_id": ("parent", "product_id", "parent_material"),
        "child_id": ("child", *MATERIAL),
        "qty_per": ("quantity_per", "units_per", "quantity", "qty"),
        "valid_from": ("effective_from", "start_date"), "valid_to": ("effective_to", "end_date"),
    }),
    Dataset("components", models.Component, "soony/master/components*.csv", {
        "component_id": ("material_id", *MATERIAL), "description": ("name", "material_description"),
        "uom": ("unit", "unit_of_measure"), "critical": ("is_critical",),
        "drawing_rev": ("drawing_revision", "revision"),
    }),
    Dataset("products", models.Product, "soony/master/products*.csv", {
        "product_id": ("finished_good_id", "material_id", "sku"),
        "name": ("product_name", "description"), "lifecycle": ("status",),
        "launch_date": ("release_date",), "plan_weekly_units": ("weekly_plan", "weekly_units"),
        "plants": ("plant", "site", "sites"), "std_cost_eur": ("standard_cost_eur",),
    }),
    Dataset("suppliers", models.Supplier, "suppliers/*/profile.csv", {
        "supplier_id": ("id", "vendor_id", "vendor_number", "supplier_code", "lifnr"),
        "name": ("supplier", "supplier_name", "vendor_name"),
        "legal_name": ("registered_name",), "lat": ("latitude",), "lon": ("longitude",),
        "supplier_since": ("since", "start_date"), "contact_email": ("email",),
        "phone": ("contact_phone", "telephone"), "preferred_language": ("language", "locale"),
        "notes": ("note", "comment"),
    }),
    Dataset("supplier_components", models.SupplierComponent, "suppliers/*/components.csv", {
        "supplier_id": SUPPLIER, "component_id": ("material_id", *MATERIAL),
        "description": ("name",), "share": ("allocation_share",),
        "unit_price": ("price", "netpr"), "lead_time_days": ("lead_days",),
        "moq": ("minimum_order_qty",), "primary": ("is_primary",), "note": ("notes", "comment"),
    }),
    Dataset("routes", models.Route, "soony/master/routes*.csv", {
        "route_id": ("route", "route_code"), "origin": ORIGIN, "destination": DESTINATION,
        "mode": ("transport_mode",), "carrier_id": ("carrier",), "transit_days": ("days",),
    }),
    Dataset("packout_log", models.Packout, "soony/erp/packout_log*.csv", {
        "date": ("pack_date", "production_date"), "site": SITE,
        "product_id": ("product", "material_id", "sku"), "line": ("packing_line",),
        "units_packed": ("packed_units", "qty_packed", "quantity", "units"),
    }),
)
SHIPMENT = next(dataset for dataset in DATASETS if dataset.table == "open_shipments")
SOURCES = (*DATASETS, Dataset(SHIPMENT.table, SHIPMENT.model,
                             "soony/logistics/open_shipments*.xlsx", SHIPMENT.aliases))


def header_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(character for character in value if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]", "", value)


@dataclass(frozen=True)
class Header:
    keys: tuple[str, ...]
    bindings: dict[str, tuple[str, ...]]
    missing: set[str]

    @classmethod
    def read(cls, cells: Iterable[str], dataset: Dataset, defaults: dict[str, str]) -> "Header":
        keys = tuple(header_key(cell) for cell in cells)
        available = set(keys)
        bindings = {}
        missing = set()
        for field, info in dataset.model.model_fields.items():
            aliases = dict.fromkeys(map(header_key, (field, *dataset.aliases.get(field, ()))))
            matches = tuple(alias for alias in aliases if alias in available)
            if matches:
                bindings[field] = matches
            elif info.is_required() and field not in defaults:
                missing.add(field)
        return cls(keys, bindings, missing)


SourceRow = tuple[str, int, Header, list[str], date | None]


def decode_csv(body: bytes) -> str:
    if body.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return body.decode("utf-32")
    if body.startswith((b"\xff\xfe", b"\xfe\xff")):
        return body.decode("utf-16")
    if b"\x00" in body[:1024]:
        even = body[:1024:2].count(0)
        odd = body[1:1024:2].count(0)
        if even != odd:
            return body.decode("utf-16-be" if even > odd else "utf-16-le")
    for encoding in ("utf-8-sig", "cp1252", "cp1250", "latin-1"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("could not decode CSV")


def read_csv(body: bytes, dataset: Dataset, defaults: dict[str, str]) -> Iterator[SourceRow]:
    contents = decode_csv(body)
    first = next((line for line in contents.splitlines() if line.strip()), "")
    if not first:
        raise ValueError("CSV has no header")
    # Score separators against known headers. Decimal commas in body rows cannot
    # outvote the semicolon-delimited SAP header.
    candidates = []
    for separator in (",", ";", "\t", "|"):
        cells = next(csv.reader([first], delimiter=separator))
        header = Header.read(cells, dataset, defaults)
        candidates.append((len(header.missing), -len(header.bindings), separator, header))
    _, _, separator, header = min(candidates)
    if header.missing:
        raise ValueError("missing columns " + ", ".join(sorted(header.missing)))
    reader = csv.reader(io.StringIO(contents, newline=""), delimiter=separator, strict=True)
    for cells in reader:
        if any(cell.strip() for cell in cells):
            break
    while True:
        row = reader.line_num + 1
        try:
            cells = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            raise ValueError(f"row {row}: {exc}") from exc
        yield "", row, header, cells, None


def cell_column(reference: str) -> int:
    index = 0
    for letter in re.match(r"[A-Z]+", reference)[0]:
        index = index * 26 + ord(letter) - ord("A") + 1
    return index - 1


def excel_cells(row: ET.Element, shared: list[str]) -> list[str]:
    cells: list[str] = []
    for cell in row.findall("{*}c"):
        index = cell_column(cell.attrib["r"]) if "r" in cell.attrib else len(cells)
        cells.extend([""] * (index + 1 - len(cells)))
        value = cell.findtext("{*}v", default="")
        kind = cell.get("t")
        if kind == "s":
            value = shared[int(value)]
        elif kind == "inlineStr":
            value = excel_text(cell.find("{*}is"))
        cells[index] = value
    return cells


def excel_text(item: ET.Element | None) -> str:
    if item is None:
        return ""
    return item.findtext("{*}t", default="") + "".join(
        run.findtext("{*}t", default="") for run in item.findall("{*}r")
    )


def read_xlsx(body: bytes, dataset: Dataset, defaults: dict[str, str]) -> Iterator[SourceRow]:
    """Read OOXML cell values, including sparse rows and cached formula values."""
    with ZipFile(io.BytesIO(body)) as workbook:
        book = ET.fromstring(workbook.read("xl/workbook.xml"))
        props = book.find("{*}workbookPr")
        date_1904 = props is not None and props.get("date1904") in ("1", "true")
        epoch = date(1904, 1, 1) if date_1904 else date(1899, 12, 30)
        relations = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
        targets = {r.attrib["Id"]: r.attrib["Target"] for r in relations
                   if r.get("TargetMode") != "External"}
        shared = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            strings = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            shared = [excel_text(item) for item in strings.findall("{*}si")]
        found = False
        for sheet in book.findall("{*}sheets/{*}sheet"):
            name = sheet.attrib["name"]
            relation = next(value for key, value in sheet.attrib.items() if key.endswith("}id"))
            target = targets.get(relation, "")
            path = posixpath.normpath(posixpath.join("xl", target)).lstrip("/")
            if not target or path not in workbook.namelist():
                continue
            worksheet = ET.fromstring(workbook.read(path))
            header = None
            for index, row in enumerate(worksheet.findall("{*}sheetData/{*}row"), 1):
                cells = excel_cells(row, shared)
                if header is None:
                    candidate = Header.read(cells, dataset, defaults)
                    if not candidate.missing and len(candidate.bindings) > 1:
                        header = candidate
                        found = True
                    continue
                yield name, int(row.get("r", index)), header, cells, epoch
        if not found:
            raise ValueError("no worksheet has the shipment header")


@dataclass(frozen=True)
class Record:
    value: BaseModel
    sheet: str
    row: int


def read_records(
    source: str, body: bytes, dataset: Dataset, supplier_names: dict[str, str]
) -> Iterator[Record]:
    path = PurePosixPath(source)
    defaults = {}
    if path.parts[0] == "suppliers":
        folder_id = path.parts[1].split("_", 1)[0]
        if re.fullmatch(r"SUP-\d+", folder_id, re.IGNORECASE):
            defaults["supplier_id"] = folder_id
    reader = read_xlsx if path.suffix == ".xlsx" else read_csv
    for sheet, row, header, cells, epoch in reader(body, dataset, defaults):
        if not any(cell.strip() for cell in cells):
            continue
        location = f"{sheet} row {row}" if sheet else f"row {row}"
        if any(cell.strip() for cell in cells[len(header.keys):]):
            raise ValueError(f"{location}: row has more cells than the header")
        raw = {key: cell.strip() for key, cell in zip(header.keys, cells) if key and cell.strip()}
        values = dict(defaults)
        for field, candidates in header.bindings.items():
            key = next((candidate for candidate in candidates if candidate in raw), None)
            if key:
                values[field] = raw[key]
                if field == "po_line" and key == "ebelp":
                    # The SAP export uses 10-spaced item IDs. Preserve nonstandard IDs.
                    line = models.decimal_value(raw[key])
                    if line.is_finite() and line % 10 == 0:
                        values[field] = line / 10
        if "status_raw" in dataset.model.model_fields and "status" in values:
            values["status_raw"] = values["status"]
        if dataset.model is models.Shipment and "supplier_id" not in values:
            name = values.get("supplier_name", "")
            resolved = supplier_names.get(" ".join(name.casefold().split()))
            if resolved or re.fullmatch(r"(?:SUP[ -]?)?\d+", name, re.IGNORECASE):
                values["supplier_id"] = resolved or name
        try:
            month_first = "ebeln" in header.keys or "legacy" in path.stem.casefold()
            record = dataset.model.model_validate(
                values, context={"excel_epoch": epoch, "month_first": month_first}
            )
        except ValidationError as exc:
            errors = exc.errors(include_input=False, include_context=False, include_url=False)
            message = ", ".join(f"{error['loc'][0]} {error['msg']}" for error in errors)
            raise ValueError(f"{location}: {message}") from exc
        yield Record(record, sheet, row)
