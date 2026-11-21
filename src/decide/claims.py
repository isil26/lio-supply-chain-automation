"""Deterministic, cited supplier claims and price/freight/leakage exposure."""

import csv
from datetime import date, datetime
from math import ceil
from pathlib import Path


CONTRACTS = {
    "SUP-0010": ("case-data/suppliers/SUP-0010_Hwaseong_Memory/contracts/SUP-0010_LTA_2022.pdf", 0.02, 0.10),
    "SUP-0019": ("case-data/suppliers/SUP-0019_Dongguan_Precision_Housings/contracts/SUP-0019_Supply_Agreement_2018.pdf", 0.005, 0.05),
    "SUP-0029": ("case-data/suppliers/SUP-0029_Guangzhou_PackRight/contracts/SUP-0029_Framework_Supply_Agreement_2023.pdf", 0.005, 0.05),
    "SUP-0018": ("case-data/suppliers/SUP-0018_Pune_Diecast_Works/contracts/SUP-0018_Framework_Supply_Agreement_2026.pdf", 0.005, 0.05),
}

CURRENCIES = {
    "SUP-0010": "USD", "SUP-0011": "USD", "SUP-0019": "CNY",
    "SUP-0028": "EUR", "SUP-0029": "CNY", "SUP-0018": "INR",
}


def commenced_weeks(days_late):
    return ceil(days_late / 7) if days_late > 0 else 0


def twelve_month_deadline(delivery):
    try:
        return delivery.replace(year=delivery.year + 1)
    except ValueError:
        return delivery.replace(year=delivery.year + 1, month=2, day=28)


def late_delivery_damages(amount, days_late, rate, cap):
    """Return damage as amount * rate * commenced weeks, capped at amount * cap."""
    if days_late <= 0:
        return 0.0
    return round(min(amount * rate * commenced_weeks(days_late), amount * cap), 2)


def _modern_po_rows(data_root):
    path = data_root / "soony/erp/purchase_orders_2025H2-2026.csv"
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _legacy_po_rows(data_root):
    path = data_root / "soony/erp/purchase_orders_legacy_2024-2025H1.csv"
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


def late_delivery_claims(data_root=Path("case-data"), as_of=None):
    as_of = as_of or date(2026, 11, 21)
    claims = []

    for line_number, row in enumerate(_modern_po_rows(data_root), 2):
        if row["status"] != "delivered" or not row["promised_date"] or not row["actual_delivery_date"]:
            continue
        supplier = row["supplier_id"]
        if supplier not in CONTRACTS:
            continue
        promised = date.fromisoformat(row["promised_date"])
        actual = date.fromisoformat(row["actual_delivery_date"])
        days = (actual - promised).days
        if days <= 0:
            continue
        contract_file, rate, cap = CONTRACTS[supplier]
        value = float(row["quantity"]) * float(row["unit_price"])
        damages = late_delivery_damages(value, days, rate, cap)
        deadline = twelve_month_deadline(actual) if supplier == "SUP-0010" else None
        claims.append({
            "supplier_id": supplier,
            "po_number": row["po_number"],
            "po_line": int(row["po_line"]),
            "days_late": days,
            "commenced_weeks": commenced_weeks(days),
            "value": round(value, 2),
            "currency": row["currency"],
            "damages": damages,
            "claim_deadline": deadline.isoformat() if deadline else "Not stated in supplied contract",
            "claim_status": "Open" if deadline and deadline >= as_of else ("Deadline passed" if deadline else "Plausible"),
            "evidence": {
                "file": "case-data/soony/erp/purchase_orders_2025H2-2026.csv",
                "row": line_number,
                "quote": (
                    f'{row["po_number"]} line {row["po_line"]}: promised {row["promised_date"]}, '
                    f'actual {row["actual_delivery_date"]}, quantity {row["quantity"]}, '
                    f'unit price {row["unit_price"]} {row["currency"]}'
                ),
            },
            "contract": {
                "file": contract_file,
                "page": 1,
                "quote": "2 % per commenced week, capped at 10 %." if supplier == "SUP-0010"
                else "0.5 % of the delayed order value per commenced week, capped at 5 %.",
            },
        })

    for line_number, row in enumerate(_legacy_po_rows(data_root), 2):
        supplier = {
            "10": "SUP-0010", "11": "SUP-0011", "19": "SUP-0019",
            "28": "SUP-0028", "29": "SUP-0029", "18": "SUP-0018",
        }.get(row["LIFNR"])
        if not supplier or supplier not in CONTRACTS or row["ZZSTAT"] != "GL":
            continue
        promised = datetime.strptime(row["ZZCONF"], "%m/%d/%Y").date()
        actual = datetime.strptime(row["WEDAT"], "%m/%d/%Y").date()
        days = (actual - promised).days
        if days <= 0:
            continue
        contract_file, rate, cap = CONTRACTS[supplier]
        quantity = float(row["MENGE"])
        unit_price = float(row["NETPR"].replace(",", "."))
        value = quantity * unit_price
        damages = late_delivery_damages(value, days, rate, cap)
        deadline = twelve_month_deadline(actual) if supplier == "SUP-0010" else None
        claims.append({
            "supplier_id": supplier,
            "po_number": row["EBELN"],
            "po_line": int(row["EBELP"]),
            "days_late": days,
            "commenced_weeks": commenced_weeks(days),
            "value": round(value, 2),
            "currency": CURRENCIES[supplier],
            "damages": damages,
            "claim_deadline": deadline.isoformat() if deadline else "Not stated in supplied contract",
            "claim_status": "Open" if deadline and deadline >= as_of else ("Deadline passed" if deadline else "Plausible"),
            "evidence": {
                "file": "case-data/soony/erp/purchase_orders_legacy_2024-2025H1.csv",
                "row": line_number,
                "quote": (
                    f'{row["EBELN"]} line {row["EBELP"]}: promised {row["ZZCONF"]}, '
                    f'actual {row["WEDAT"]}, quantity {row["MENGE"]}, '
                    f'decimal-comma unit price {row["NETPR"]}'
                ),
            },
            "contract": {
                "file": contract_file,
                "page": 1,
                "quote": "2 % per commenced week, capped at 10 %." if supplier == "SUP-0010"
                else "0.5 % of the delayed order value per commenced week, capped at 5 %.",
            },
        })
    return claims


def price_drift(data_root=Path("case-data")):
    rows = []
    notice_files = [
        ("SUP-0011", "CMP-GAM-001", 10.20, "USD", "boise"),
        ("SUP-0011", "CMP-GAM-002", 5.70, "USD", "boise"),
        ("SUP-0029", "CMP-GAM-003", 1.38, "CNY", "packright"),
        ("SUP-0029", "CMP-GAM-004", 0.3984, "CNY", "packright"),
        ("SUP-0029", "CMP-GAM-007", 24.63, "CNY", "packright"),
        ("SUP-0010", "CMP-GAM-001", 9.80, "USD", "hwaseong"),
        ("SUP-0010", "CMP-GAM-002", 5.40, "USD", "hwaseong"),
    ]
    contract_files = {
        "boise": "case-data/suppliers/SUP-0011_Boise_Semi/contracts/SUP-0011_Sales_Agreement_2023.pdf",
        "packright": "case-data/suppliers/SUP-0029_Guangzhou_PackRight/contracts/SUP-0029_Framework_Supply_Agreement_2023.pdf",
        "hwaseong": "case-data/suppliers/SUP-0010_Hwaseong_Memory/contracts/SUP-0010_LTA_2022.pdf",
    }
    for supplier, material, contract_price, currency, kind in notice_files:
        po_qty = 0.0
        latest_price = contract_price
        for row in _modern_po_rows(data_root):
            if row["supplier_id"] == supplier and row["material_id"] == material:
                po_qty += float(row["quantity"])
                latest_price = float(row["unit_price"])
        drift = round(latest_price - contract_price, 6)
        amount = round(max(drift, 0) * po_qty, 2)
        revision_allowed = kind == "boise"
        fixed = kind in {"packright", "hwaseong"}
        rows.append({
            "supplier_id": supplier,
            "material_id": material,
            "contract_price": contract_price,
            "latest_po_or_notice_price": latest_price,
            "currency": currency,
            "drift_per_unit": drift,
            "quantity_considered": int(po_qty),
            "potential_amount": amount,
            "status": "Revision allowed with 60 days' written notice" if revision_allowed
            else ("Potential breach: price fixed" if fixed and drift > 0 else "No contract drift in PO snapshot"),
            "evidence": {
                "file": contract_files[kind],
                "page": 2 if kind == "boise" else 3,
                "quote": f"Annex A contracted {material} price {contract_price} {currency}; latest PO price {latest_price}",
            },
        })
    return rows


def freight_duty_exposure(data_root=Path("case-data")):
    rows = []
    for line_number, row in enumerate(_modern_po_rows(data_root), 2):
        if row["supplier_id"] == "SUP-0011" and row["incoterm"] == "DDP Hamburg":
            rows.append({
                "po_number": row["po_number"],
                "po_line": int(row["po_line"]),
                "quantity": float(row["quantity"]),
                "currency": row["currency"],
                "erp_incoterm": row["incoterm"],
                "contract_incoterm": "EXW Boise",
                "estimated_exposure": "Unquantified: freight, insurance, export and import duties are buyer account; invoices absent",
                "confidence": "PLAUSIBLE",
                "evidence": {
                    "file": "case-data/soony/erp/purchase_orders_2025H2-2026.csv",
                    "row": line_number,
                    "quote": f'{row["po_number"]} line {row["po_line"]} ERP incoterm DDP Hamburg',
                },
            })
    return rows


def leakage(data_root=Path("case-data")):
    pins = []
    gr_path = data_root / "soony/erp/goods_receipts.csv"
    if gr_path.is_file():
        with gr_path.open(newline="", encoding="utf-8-sig") as handle:
            for line_number, row in enumerate(csv.DictReader(handle), 2):
                if row["supplier_id"] == "SUP-0019" and row["material_id"] == "PRM-GH6-PIN":
                    pins.append({
                        "row": line_number,
                        "quantity": float(row["qty_received"]),
                        "date": row["gr_date"],
                        "delivery_note": row["delivery_note"],
                        "quote": row["remark"],
                    })
    cancellations = []
    for line_number, row in enumerate(_modern_po_rows(data_root), 2):
        if row["status"] == "cancelled" and float(row["quantity"]) < 0:
            cancellations.append({
                "po_number": row["po_number"],
                "po_line": int(row["po_line"]),
                "supplier_id": row["supplier_id"],
                "quantity": abs(float(row["quantity"])),
                "currency": row["currency"],
                "unit_price": float(row["unit_price"]),
                "evidence": {
                    "file": "case-data/soony/erp/purchase_orders_2025H2-2026.csv",
                    "row": line_number,
                    "quote": f'{row["po_number"]} line {row["po_line"]}: {row["quantity"]} {row["currency"]} {row["unit_price"]}, cancellation',
                },
            })
    return {"pins": pins, "cancellations": cancellations}


def totals(claims):
    result = {}
    for claim in claims:
        supplier = claim["supplier_id"]
        result.setdefault(supplier, {"currency": claim["currency"], "damages": 0.0, "lines": 0})
        result[supplier]["damages"] = round(result[supplier]["damages"] + claim["damages"], 2)
        result[supplier]["lines"] += 1
    return result


def markdown_report(data_root=Path("case-data"), as_of=None):
    claims = late_delivery_claims(data_root, as_of)
    drift = price_drift(data_root)
    freight = freight_duty_exposure(data_root)
    leak = leakage(data_root)
    grand = totals(claims)
    lines = [
        "# Supplier claims and recoverable amounts",
        "",
        "## Late-delivery damages",
        "| Supplier | PO line | Days late | Weeks | Delayed value | Damages | Currency | Claim deadline | Confidence | Evidence |",
        "|---|---|---:|---:|---:|---:|---|---|---|---|",
    ]
    for claim in claims:
        lines.append(
            f"| {claim['supplier_id']} | {claim['po_number']} / {claim['po_line']} | "
            f"{claim['days_late']} | {claim['commenced_weeks']} | {claim['value']:,.2f} | "
            f"{claim['damages']:,.2f} | {claim['currency']} | {claim['claim_deadline']} | "
            f"{claim['claim_status']} | `{claim['evidence']['file']}:{claim['evidence']['row']}`; "
            f"{claim['contract']['file']} p. {claim['contract']['page']}: \"{claim['contract']['quote']}\" |"
        )
    lines += [
        "", "## Totals by supplier",
        "| Supplier | Currency | Damages | Late lines |",
        "|---|---|---:|---:|",
    ]
    for supplier, value in sorted(grand.items()):
        lines.append(f"| {supplier} | {value['currency']} | {value['damages']:,.2f} | {value['lines']} |")
    lines += [
        "", "## Price drift",
        "| Supplier | Material | Contract / latest PO | Drift / unit | Potential amount | Currency | Status | Evidence |",
        "|---|---|---:|---:|---:|---|---|---|",
    ]
    for row in drift:
        lines.append(
            f"| {row['supplier_id']} | {row['material_id']} | "
            f"{row['contract_price']} / {row['latest_po_or_notice_price']} | "
            f"{row['drift_per_unit']:+.4f} | {row['potential_amount']:,.2f} | "
            f"{row['currency']} | {row['status']} | `{row['evidence']['file']}` p. "
            f"{row['evidence']['page']}: \"{row['evidence']['quote']}\" |"
        )
    lines += [
        "", "## Freight and duty",
        f"- Boise ERP rows marked DDP Hamburg: {len(freight)}.",
        "- Contract: EXW Boise; freight, insurance, export and import duties are Soony's account. "
        "No freight invoices or duty rates are supplied, so the amount is unquantified.",
        "- POs and lines:",
        "",
        "  " + "; ".join(
            f"{row['po_number']} / {row['po_line']} (qty {row['quantity']:,.0f})"
            for row in freight
        ) + ".",
        "## Leakage",
        f"- Pins received without PO: {sum(p['quantity'] for p in leak['pins']):,.0f} units "
        f"({len(leak['pins'])} receipts).",
        "  " + "; ".join(
            f"{p['date']}, GR row {p['row']}, {p['delivery_note']}, qty {p['quantity']:,.0f}, "
            f"`case-data/soony/erp/goods_receipts.csv:{p['row']}`"
            for p in leak["pins"]
        ) + ".",
        f"- Negative cancellation lines on already-delivered POs: "
        f"{sum(c['quantity'] for c in leak['cancellations']):,.0f} units "
        f"({len(leak['cancellations'])} lines).",
        "  " + "; ".join(
            f"{c['po_number']} / {c['po_line']}, qty {c['quantity']:,.0f}, "
            f"`{c['evidence']['file']}:{c['evidence']['row']}`"
            for c in leak["cancellations"]
        ) + ".",
        "",
        "## LTA renewal",
        "- SUP-0010 Hwaseong agreement expires 31 December 2026. Renewal signed amendment deadline: 15 December 2026.",
        "- Absent renewal: then-current list prices and standard NET30 terms, with no capacity reservation.",
        "",
        "## Evidence and limits",
        "- Source: `case-data/soony/erp/purchase_orders_2025H2-2026.csv`, "
        "`case-data/soony/erp/purchase_orders_legacy_2024-2025H1.csv`, supplier contracts and goods-receipts snapshot.",
        "- Invoices are not supplied. This is a claims exposure estimate, not a legal opinion or a demand payable now.",
        "- Damages use promised versus actual delivery, commenced calendar weeks, and supplied contract caps.",
        "- Force majeure and set-off are not independently assessed. No FX conversion is applied.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(markdown_report())
