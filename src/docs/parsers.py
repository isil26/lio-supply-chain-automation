"""Deterministic parsers for procurement documents and receipt transcriptions."""

import re
from datetime import date
from pathlib import Path

from .schema import (
    DELIVERY_NOTE, ISO_DATE, ITEM_CODE, PO_NUMBER, QUANTITY,
    decimal_number, iso_date, quantity, search,
)

PRICE = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:[.,]\d+)?"
OC_ROW = re.compile(
    rf"^[ \t]*(?P<item>\d{{3,6}})[ \t]+(?P<material>{ITEM_CODE})[ \t]+"
    rf"(?P<description>.*?)[ \t]*(?P<quantity>{QUANTITY})[ \t]+"
    rf"(?P<price>{PRICE})[ \t]+(?P<currency>[A-Z]{{3}})[ \t]+(?P<date>{ISO_DATE})[ \t]*$",
    re.M,
)
OC_STACKED = re.compile(
    rf"^\s*(?P<item>\d{{3,6}})\s*\n[ \t]*(?P<material>{ITEM_CODE})[ \t]*\n"
    rf"(?P<description>(?:(?!^[ \t]*\d{{3,6}}[ \t]*$).)*?)"
    rf"^[ \t]*(?P<quantity>{QUANTITY})[ \t]*\n[ \t]*(?P<price>{PRICE})[ \t]*\n"
    rf"[ \t]*(?P<currency>[A-Z]{{3}})[ \t]*\n[ \t]*(?P<date>{ISO_DATE})[ \t]*$",
    re.M | re.S,
)
OC_FOOTER = re.compile(
    r"^(?:Terms of delivery|Supplier status|Artwork\b|Note\b|Conditions?\b|"
    r"[A-Z]{2,4}-[A-Z0-9-]+\s*:|The shipment|Revised|Delivery\b)", re.I
)


def order(facts, raw, page, confidence):
    flat = " ".join(raw.split())
    search(facts, "po", rf"(?:your\s+order|purchase\s+order|\bPO(?:\s*(?:no\.?|number))?)"
           rf"\s*[:#]?\s*({PO_NUMBER})", flat, page, confidence)
    search(facts, "confirmation_number", r"\b(OA\d{8})\b", flat, page, confidence)
    search(facts, "incoterm", r"\bIncoterms\s*:?\s*([^·•|]+?)(?=\s*[·•|]|\s+Payment|$)",
           flat, page, confidence)
    search(facts, "payment", r"\bPayment\s*:?\s*(NET\s*\d+)\b", flat, page, confidence)
    rows = list(OC_ROW.finditer(raw)) or list(OC_STACKED.finditer(raw))
    for row in rows:
        item = int(row["item"])
        if item <= 0 or item % 10 or iso_date(row["date"]) is None:
            continue
        facts.add("items", {
            "line": item // 10,
            "material": row["material"],
            "quantity": quantity(row["quantity"]),
            "unit_price": decimal_number(row["price"], decimal_comma="," in row["price"]
                                         and "." not in row["price"] and len(row["price"].split(",")[-1]) != 3),
            "currency": row["currency"],
            "promised_date": row["date"],
        }, page, row[0], confidence)

    suffix = raw[rows[-1].end():] if rows else raw
    if rows:
        footer = []
        item_indent = len(rows[-1][0]) - len(rows[-1][0].lstrip(" \t"))
        for line in suffix.splitlines():
            trimmed = line.strip()
            if not trimmed or re.search(r"\bPage\s+\d+(?:\s+of\s+\d+)?$", trimmed, re.I):
                continue
            if footer or OC_FOOTER.search(trimmed) or (
                rows[-1].re is OC_ROW and len(line) - len(line.lstrip()) <= item_indent
            ):
                footer.append(line)
        if footer:
            quote = "\n".join(footer)
            facts.add("conditions", " ".join(quote.split()), page, quote, confidence)
            search(facts, "revision", r"\brev(?:ision)?[. :]+([A-Z]\b)", quote, page, confidence)
    search(facts, "dock_hold", r"(The shipment is packed and on hold[\s\S]*?own forwarder\.)",
           suffix, page, confidence)
    for match in re.finditer(rf"AWB\s+([\d-]+):\s+({QUANTITY})\s+pcs flown", flat, re.I):
        facts.add("shipped", {"reference": match[1], "quantity": quantity(match[2])},
                  page, match[0], confidence)
    for match in re.finditer(rf"Balance\s+({QUANTITY})\s+pcs:.+?delivery to Hamburg\s+({ISO_DATE})", flat, re.I):
        facts.add("balance", {"quantity": quantity(match[1]), "hamburg_date": match[2]},
                  page, match[0], confidence)
    search(facts, "packing_list", r"\b(NHMU\d{7})\b", flat, page, confidence)


CLAUSE_TOPICS = {
    "penalties": r"late delivery|delivery performance|delay|opóźnie|违约|지연",
    "force_majeure": r"force majeure|siła wyższa|不可抗力|불가항력",
    "lead_time": r"lead time|ordering|\borders\b|zamówieni|交期|납기",
    "payment": r"payment|transfer of risk|delivery terms|shipping|płatno|付款|지급",
    "qualification": r"scope|quality|jakość|质量|품질",
    "term": r"\bterm\b|termination|obowiązywania|期限|기간",
    "liability": r"liability|odpowiedzialność|责任|책임",
    "capacity": r"capacity|moce|产能|생산능력",
    "sub_suppliers": r"sub-suppliers|supply chain transparency|poddostaw|分包",
}

ANNEX_LINE = re.compile(
    rf"^\s*(CMP-[A-Z0-9-]+)\s+.+?\s+({PRICE}|included in .+?)\s+"
    rf"([A-Z]{{3}})\s+(?:MOQ\s+)?({QUANTITY}|n/a)\s+(?:LT\s+)?(\d+)(?:\s*d(?:ays)?)?\s*$",
    re.M,
)


def contract(facts, raw, page, confidence):
    flat = " ".join(raw.split())
    search(facts, "contract_number", r"\b(PC-\d{4}-\d{4})\b", flat, page, confidence)
    search(facts, "effective_at", rf"\bEffective\s+({ISO_DATE})", flat, page, confidence)
    search(facts, "expires_at", rf"\bExpires\s+({ISO_DATE})", flat, page, confidence)
    for match in re.finditer(r"^\s*§\s*\d+\s+([^\n]+)\n.*?(?=^[ \t]*(?:§|Annex\b)|\Z)", raw, re.M | re.S):
        heading, quote = match[1].strip(), match[0].strip()
        value = " ".join(quote.split())
        facts.add("clauses", value, page, quote, confidence)
        for name, pattern in CLAUSE_TOPICS.items():
            if re.search(pattern, heading, re.I):
                facts.add(name, value, page, quote, confidence)
    for match in ANNEX_LINE.finditer(raw):
        material, price, currency, moq, lead = match.groups()
        facts.add("annex", {"material": material, "unit_price": decimal_number(price), "currency": currency,
                            "moq": quantity(moq), "lead_time_days": int(lead)}, page, match[0], confidence)
    for match in re.finditer(rf"^[ \t]*(CMP-[A-Z0-9-]+)\s+((?!CMP-){ITEM_CODE})[ \t]*$", raw, re.M):
        facts.add("aliases", {"material": match[1], "supplier_material": match[2]}, page, match[0], confidence)
    search(facts, "rush_terms", r"\b\d+\.\d+ Rush orders\..*?(?=\s§|\s\d+\.\d+ |$)", flat, page, confidence)
    search(facts, "artwork", r"\b\d+\.\d+ Artwork\..*?(?=\s§|\s\d+\.\d+ |$)", flat, page, confidence)
    annex = re.search(r"^[ \t]*Annex B\b.*?(?=^[ \t]*Annex [C-Z]\b|\Z)", raw, re.M | re.S)
    if annex:
        facts.add("sub_suppliers", " ".join(annex[0].split()), page, annex[0], confidence)


LOCAL_TRANSLATIONS = (
    (r"Zawiadomienie o planowanym przestoju technicznym", "Notice of planned maintenance downtime."),
    (r"zlecenia w trybie ekspresowym.*?podanej w tabeli\.",
     "Rush orders are limited to the digital line during the shutdown, up to the quantity in the table."),
    (r"wysyłka\s+wyrobów gotowych z\s+magazynu możliwa", "Finished goods can still ship from warehouse stock."),
)
LOCAL_TIME = r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}"


def notice(facts, raw, page, confidence):
    flat = " ".join(raw.split())
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) > 1:
        facts.add("what", lines[1], page, lines[1], confidence)
    for match in re.finditer(rf"^[ \t]*(\S.*?)[ \t]{{2,}}({LOCAL_TIME})\s+({LOCAL_TIME}).*$", raw, re.M):
        name = match[1].strip()
        start, end = iso_date(match[2]), iso_date(match[3])
        if start and end:
            facts.add("downtime", {"resource": name, "starts_at": start, "ends_at": end}, page, match[0], confidence)
            facts.add("effective_at", start, page, match[2], confidence)
            facts.add("ends_at", end, page, match[3], confidence)
    search(facts, "maximum_quantity", rf"\bdo ({QUANTITY}) szt\.", flat, page, confidence, quantity)
    capacity = re.search(rf"do ({QUANTITY}) szt\..{{0,220}}?\b(\d+) h\b", flat, re.I)
    if capacity and "Druk cyfrowy" in flat:
        units, hours = quantity(capacity[1]), int(capacity[2])
        facts.add("capacity", {"quantity": units, "hours": hours, "resource": "digital printing"},
                  page, capacity[0], confidence)
    deadline = re.search(r"(?:przyjmujemy do) (\d{2}\.\d{2}\.\d{4}),?\s+godz\.\s*(\d{2}:\d{2})", flat, re.I)
    if deadline:
        facts.add("rush_cutoff", iso_date(f"{deadline[1]} {deadline[2]}"), page, deadline[0], confidence)
    for pattern, translation in LOCAL_TRANSLATIONS:
        match = re.search(pattern, flat, re.I)
        if match:
            facts.add("translation_en", translation, page, match[0], confidence)
            if "Rush orders" in translation or "Finished goods" in translation:
                facts.add("impact", translation, page, match[0], confidence)
    for match in re.finditer(rf"({ITEM_CODE}).{{0,150}}?\b({QUANTITY})\s*pcs\b.{{0,220}}?loaded.{{0,160}}?within\s+(\d+) h",
                             flat, re.I):
        material, units, load = match.groups()
        facts.add("available_offer", {"material": material, "quantity": quantity(units), "load_hours": int(load)},
                  page, match[0], confidence)
    search(facts, "road_hours", r"about (\d+) h driving", flat, page, confidence, int)
    search(facts, "offer_valid_hours", r"valid (\d+) h", flat, page, confidence, int)


NO_DAMAGE = re.compile(
    r"no (?:visible )?damage|undamaged|no objections|bez zastrzeżeń|brak uszkodzeń|kein schaden|무파손|无破损|無破損", re.I
)
RECEIPT_ROW = re.compile(
    rf"^[ \t|]*(?P<material>{ITEM_CODE})(?=[ \t|])[^\n]*?"
    rf"(?<![\d.,])(?P<units>{QUANTITY})\s*\|?\s*(?:PCS?|EA|szt\.?|Stk\.?|件|个|個|개)(?!\w)",
    re.M | re.I,
)
PRINTED_CORRECTION = re.compile(
    rf"(?P<material>{ITEM_CODE})[^\n]*?\b(?:printed|crossed out|struck out)\s*[:=]?\s*"
    rf"(?P<printed>{QUANTITY})[^\n]*?\b(?:handwritten|corrected(?: to)?)\s*[:=]?\s*(?P<corrected>{QUANTITY})",
    re.I,
)
PO_LABEL = r"(?:purchasing order|purchase order|\bPO(?:\s*no\.?)?|Zam[oó]wienie|采\s*购\s*订\s*单|採\s*購\s*訂\s*單|발주(?:\s*번호)?)"


def receipt_text(facts, raw, page, confidence):
    for match in re.finditer(DELIVERY_NOTE, raw, re.I):
        facts.add("delivery_note", re.sub(r"[-– ]", "-", match[0].upper()), page, match[0], confidence)
    search(facts, "po", rf"{PO_LABEL}\s*[:：#]?\s*({PO_NUMBER})", raw, page, confidence)
    stamp_date = rf"(?:{ISO_DATE}|\d{{2}}[./]\d{{2}}[./]\d{{4}})"
    search(facts, "received_date", rf"RECEIVED\s+({stamp_date})", raw, page, confidence, iso_date)
    search(facts, "document_date", rf"(?:\bDate|\bData|日\s*期|날짜)\s*[:：]\s*({stamp_date})", raw, page,
           confidence, lambda value: iso_date(value, day_first="." in value))
    for line in raw.splitlines():
        if re.search(r"\bdamag\w+|uszkodz|beschädig|파손|破损|損壞", line, re.I) and not NO_DAMAGE.search(line):
            facts.add("damage", line.strip(), page, line, confidence)
    for match in re.finditer(rf"^[ \t|]*({ITEM_CODE})(?=[ \t|]).*$", raw, re.M):
        facts.add("material", match[1], page, match[1], confidence)
    corrected = {match["material"].upper(): match for match in PRINTED_CORRECTION.finditer(raw)}
    for material, match in corrected.items():
        facts.add("items", {"material": material, "printed_quantity": quantity(match["printed"]),
                            "handwritten_quantity": quantity(match["corrected"]),
                            "quantity": quantity(match["corrected"])}, page, match[0], confidence)
    for match in RECEIPT_ROW.finditer(raw):
        material = match["material"].upper()
        if material not in corrected:
            units = quantity(match["units"])
            facts.add("items", {"material": material, "printed_quantity": units, "quantity": units},
                      page, match[0], confidence)


def inspection(facts, raw, page, confidence):
    flat = " ".join(raw.split())
    search(facts, "receipt", r"Goods receipt\s+(\d+)", flat, page, confidence)
    search(facts, "material", r"\b(CMP-[A-Z0-9-]+)\b", flat, page, confidence)
    search(facts, "hold", r"(Lot does not meet AQL\..*?Category Lead\.)", flat, page, confidence)
    search(facts, "sample_defects", r"(\d+) of \d+ [^.]+? with\b", flat, page, confidence, int)


def context(facts, raw, page, confidence):
    lines = [line for line in raw.splitlines() if line.strip()]
    for names, roles in zip(lines, lines[1:]):
        names_in_row = re.split(r"\s{2,}", names.strip())
        roles_in_row = re.split(r"\s{2,}", roles.strip())
        if len(names_in_row) != len(roles_in_row):
            continue
        for name, role in zip(names_in_row, roles_in_row):
            if re.fullmatch(r"Head of Procurement|Supplier Quality Lead|Category Lead .+", role):
                facts.add("org_role", {"role": role, "name": name}, page, f"{names}\n{roles}", confidence)
    stripped = "\n".join(line.strip() for line in raw.splitlines())
    stripped = re.sub(r"^Soony · PP-07 Approval policy · .*Page \d+\s*$", "", stripped, flags=re.M)
    search(facts, "policy_clause", r"^\d\. [^\n]+\n[\s\S]*?(?=^\d\. |\Z)", stripped, page, confidence)


def workbook(facts, path):
    from openpyxl import load_workbook

    aliases = {
        "material": r"material|part(?: number| no)?|indeks|materiał|物料|품번",
        "description": r"description|opis|描述|품명",
        "current_price": r"current price|old price|cena dotychczasowa|现价|기존 단가",
        "unit_price": r"new price|unit price|price|nowa cena|新价格|신규 단가",
        "currency": r"currency|waluta|币种|통화",
        "effective_at": r"valid from|effective(?: date)?|obowiązuje od|生效日期|적용일",
    }
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        for page, sheet in enumerate(book, 1):
            header = {}
            for row_number, row in enumerate(sheet.values, 1):
                if not any(value is not None for value in row):
                    continue
                normalized = [re.sub(r"[_\s]+", " ", str(value).strip().lower()) for value in row]
                columns = {
                    field: index for index, value in enumerate(normalized)
                    for field, pattern in aliases.items() if re.fullmatch(pattern, value)
                }
                if {"material", "unit_price"}.issubset(columns):
                    header = columns
                    continue
                quote = " | ".join(str(value) if value is not None else "" for value in row).strip(" |")
                locator = {"sheet": sheet.title, "row": row_number}
                serialized = [value.isoformat() if isinstance(value, date) else value for value in row]
                if header and re.fullmatch(ITEM_CODE, str(row[header["material"]]), re.I):
                    item = {field: serialized[index] for field, index in header.items()
                            if serialized[index] is not None}
                    for field in ("current_price", "unit_price"):
                        if field in item:
                            raw_price = item[field]
                            item[field] = decimal_number(raw_price, isinstance(raw_price, str)
                                                         and "," in raw_price and "." not in raw_price)
                    if isinstance(item.get("effective_at"), str):
                        item["effective_at"] = iso_date(item["effective_at"]) or item["effective_at"]
                    facts.add("price_items", item, page, quote, **locator)
                elif header:
                    facts.add("conditions", quote, page, quote, **locator)
                facts.add("rows", serialized, page, quote, **locator)
    finally:
        book.close()


PARSERS = {"confirmation": order, "contract": contract, "notice": notice, "receiving": receipt_text,
           "inspection": inspection, "context": context}


def classify(source):
    path = Path(source)
    if "order_confirmations" in path.parts:
        return "confirmation"
    if "contracts" in path.parts:
        return "contract"
    if "notices" in path.parts:
        return "price_list" if path.suffix.lower() == ".xlsx" else "notice"
    if "receiving" in path.parts:
        return "inspection" if "inspection" in path.name.lower() else "receiving"
    return "workbook" if path.suffix.lower() == ".xlsx" else "context"
