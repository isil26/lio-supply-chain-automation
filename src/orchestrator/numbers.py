"""Render the deck's numbers from the evaluated launch snapshot and source rows."""

import re
from datetime import datetime

from src.ingest.store import get_state, rows
from src.truth import LOCAL


def number(value):
    return "—" if value is None else f"{value:,.0f}"


def source_refs(sources):
    refs = []
    for source in sources:
        ref = source["file"]
        if source.get("sheet"):
            ref += f' / {source["sheet"]}'
        if source.get("row"):
            ref += f' row {source["row"]}'
        if source.get("page"):
            ref += f' p. {source["page"]}'
        refs.append(ref)
    return ", ".join(dict.fromkeys(refs))


def table(headers, records):
    def line(values):
        return "| " + " | ".join(str(value).replace("|", r"\|") for value in values) + " |"

    return [line(headers), line(["---"] * len(headers)), *(line(record) for record in records)]


def numbers_report(con):
    truth = get_state(con, "truth")
    if truth is None:
        raise ValueError("No evaluated launch snapshot. Run the orchestrator with --once first.")
    options = get_state(con, "options", [])
    editions, parts, issues = truth["editions"], truth["parts"], truth["issues"]
    products = {row["product_id"]: row for row in rows(con, "product")}
    deadline = datetime.fromisoformat(truth["deadline"]).astimezone(LOCAL)
    labels = {pid: pid.rsplit("-", 1)[-1] for pid in editions}
    lines = [
        "# NUMBERS.md — live launch snapshot", "",
        "## Launch", "",
        f'- Deadline {deadline:%a %d %b %Y %H:%M} ({LOCAL.key}), {truth["site"]}.',
        f'- Deadline evidence: {source_refs([truth["source"]])}.', "",
    ]
    lines.extend(table(("Edition", "Demand", "Packed", "Packed share", "Remaining"), (
        (labels[pid], number(row["target"]), number(row["packed"]), f'{row["packed"] / row["target"]:.1%}',
         number(row["remaining"])) for pid, row in editions.items()
    )))
    lines += ["", f'Pack-out evidence: {source_refs(source for row in editions.values() for source in row["evidence"])}.',
              "", "## Forecast", "", f'{truth["model"]["runs"]} runs. {truth["model"]["allocation"]}. '
              f'{truth["model"]["assumptions"]}', ""]
    lines.extend(table(("Edition", "Target", "Expected packed (p10 / p50 / p90)", "P(reach target)", "First stop", "Gap at p50"), (
        (labels[pid], number(row["target"]), " / ".join(number(row[q]) for q in ("p10", "p50", "p90")),
         f'{row["probability"]:.1%}', parts.get(row["first_stop"], {}).get("label", "—"),
         number(max(0, row["target"] - row["p50"]))) for pid, row in editions.items()
    )))

    lines += ["", "## Component gaps", ""]
    component_rows, naive = [], []
    explainers = {"short_ship", "dock_hold", "handwriting", "quality_hold", "tracker", "embedded"}
    for part in parts.values():
        raw_gap = max(0, part["required"] - part["raw_stock"])
        if raw_gap:
            naive.append(f'{part["material"]} {number(raw_gap)}')
        if not (raw_gap or part["shortfall"] or part["embedded_in"]):
            continue
        evidence = [issue for issue in issues if issue["material"] == part["material"] and issue["kind"] in explainers]
        reason = " / ".join(issue["title"] for issue in evidence) or "Active BOM, reconciled stock and inbound"
        if part["embedded_in"]:
            reason += ". Confirm the BOM assumption with Engineering"
        refs = source_refs(src for issue in evidence for src in issue["evidence"])
        if refs:
            reason += f" ({refs})"
        component_rows.append((f'{part["material"]} {part["label"]}', number(part["required"]), number(part["raw_stock"]),
                               "Bundled" if part["embedded_in"] else number(part["on_hand"]),
                               "Bundled" if part["embedded_in"] else number(part["inbound"]),
                               number(part["shortfall"]), reason))
    lines.extend(table(("Part", "Need", "SAP stock", "Usable stock", "Inbound counted", "Gap", "Reason"), component_rows))
    lines += ["", "SAP stock-only gaps: " + (", ".join(naive) if naive else "none") + ".", "",
              "## Price of the first decision", ""]
    if options:
        decision = options[0]
        price = "quote pending" if decision["price"] is None else f'{decision["currency"]} {decision["price"]:,.2f}'
        lines += [f'- {decision["title"]} — {price}. {decision.get("price_label", "Cost estimate")}. '
                  f'{decision["recommendation"]} {decision["impact"]} {decision["threshold"]}',
                  f'- Evidence: {source_refs(decision["evidence"])}.',
                  f'- Options ({len(options)} total): ' + " / ".join(item["title"] for item in options) + "."]
    else:
        lines.append("- No decision options in the evaluated snapshot.")
    for option in options:
        if option.get("approval_block"):
            lines.extend([f'- {option["title"]}. {option["impact"]} {option["recommendation"]}',
                          f'- Approval evidence: {source_refs(option["approval_block"]["evidence"])}.'])

    quality = truth["data_quality"]
    receipts = [issue for issue in issues if issue["kind"] == "receipt"]
    lines += ["", "## Data quality", "",
              f'- {number(quality["documents"])} documents processed, {number(quality["errors"])} extraction errors.',
              f'- {len(receipts)} receipt-scan issues requiring review.']
    for issue in receipts:
        lines.append(f'- {issue["title"]} ({source_refs(issue["evidence"])}).')
    shipments = list(rows(con, "shipment"))
    erp_shipments = {row["shipment_id"] for row in shipments if "/erp/" in row["source"]["file"]}
    tracker_shipments = {row["shipment_id"] for row in shipments if "/logistics/" in row["source"]["file"]}
    lines.append(f'- Tracker coverage: {number(len(erp_shipments & tracker_shipments))} of {number(len(erp_shipments))} ERP shipments.')
    confirmations = [issue for issue in issues if issue["kind"] == "confirmation"]
    incoterms = [issue for issue in confirmations if "incoterm" in issue.get("changed_fields", [])
                 or "terms " in issue["title"]]
    incoterm_pos = {issue.get("po") or match[1] for issue in incoterms
                    if (match := re.match(r"PO (\S+)", issue["title"]))}
    lines.append(f'- Incoterm conflicts: {len(incoterms)} lines across {len(incoterm_pos)} POs.')
    for issue in confirmations:
        if "promised_date" in issue.get("changed_fields", []) or "promised_date " in issue["title"]:
            lines.append(f'- {issue["title"]} ({source_refs(issue["evidence"])}).')

    lines += ["", "## Value at stake at finished-goods standard cost", ""]
    lines.extend(table(("Edition", "Remaining", "Standard cost per copy", "Standard-cost exposure", "Evidence"), (
        (labels[pid], number(row["remaining"]), f'EUR {product["std_cost_eur"]:,.2f}',
         f'EUR {row["remaining"] * product["std_cost_eur"]:,.2f}', source_refs([product["source"]]))
        if product.get("std_cost_eur") is not None else (labels[pid], number(row["remaining"]), "—", "—", "—")
        for pid, row in editions.items() for product in [products.get(pid, {})]
    )))
    lines += ["", "Revenue, margin and retailer penalties per missed copy require confirmation from Procurement.",
              "Pickup availability and unquoted freight require supplier or site confirmation."]
    return "\n".join(lines)
