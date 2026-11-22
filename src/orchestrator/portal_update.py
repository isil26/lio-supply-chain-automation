"""Present the last Lio file update alongside the latest reconciled plan."""
import re


def receipt_key(issue):
    source = issue["evidence"][0]
    return [issue["material"], issue["shipment"], issue["quantity"], source["file"], source.get("row")]


def portal_baseline(before, current):
    previous = before or {}
    known = [receipt_key(issue) for issue in previous.get("issues", []) if issue["kind"] == "shipment_received"]
    return {
        "forecastsBefore": {pid: row["p50"] for pid, row in previous.get("editions", {}).items()},
        "newReceipts": [receipt_key(issue) for issue in current["issues"]
                        if issue["kind"] == "shipment_received" and receipt_key(issue) not in known],
    }


def portal_update(drop, truth, actions, location):
    if not drop or drop.get("source") != "portal":
        return drop

    changes = {change["file"]: change["action"] for change in drop.get("changes", [])}
    previous = drop.get("forecastsBefore")
    if previous is None:
        # Previously published updates only saved the before value in the summary.
        # Its after values and its shortages can both be superseded by reconciliation.
        previous = {pid: int(match[1].replace(",", "")) for pid, row in truth["editions"].items()
                    if (match := re.search(r"(?:^| · )" + re.escape(row["edition"])
                                           + r" median forecast: ([\d,]+) → ", drop.get("detail", "")))}

    receipts = []
    for issue in truth["issues"]:
        if issue["kind"] != "shipment_received":
            continue
        source = issue["evidence"][0]
        key = receipt_key(issue)
        if source["file"] not in changes or changes[source["file"]] == "removed":
            continue
        if "newReceipts" in drop:
            if key not in drop["newReceipts"]:
                continue
        elif changes[source["file"]] != "added":
            continue  # An older export can include rows received before this update.
        part = truth["parts"].get(issue["material"])
        if part is None:
            continue
        quantity = issue["quantity"]
        label = part["label"]
        if issue["material"] == "CMP-GAM-001":
            units = "game card" if quantity == 1 else "game cards"
        else:
            units = f'{"unit" if quantity == 1 else "units"} of {label}'
        gap = part["shortfall"]
        headline = f"{location} received {quantity:,.0f} {units}."
        balance = (f"The launch still needs {gap:,} more." if gap else
                   "The current plan covers the full launch requirement for this part.")
        option = next((opt for opt in actions if gap and opt.get("material") == issue["material"]
                       and opt["status"] == "pending" and opt["approvalMode"]["mode"] != "NEVER"), None)
        receipts.append({"headline": headline, "balance": balance, "evidence": source,
                         "action": {"id": option["id"], "title": option["title"]} if option else None})

    findings = []
    if not receipts:
        for issue in truth["issues"]:
            if issue["kind"] not in {"quality_hold", "revision_hold", "dock_hold", "short_ship", "handwriting", "artwork"}:
                continue
            evidence = next((ref for ref in issue["evidence"] if changes.get(ref["file"]) in {"added", "changed"}), None)
            if evidence:
                findings.append({"title": issue["title"], "evidence": evidence})
            if len(findings) == 2:
                break

    forecasts = []
    for pid, row in truth["editions"].items():
        current = row.get("p50")
        if current is None:
            continue
        before = previous.get(pid)
        comparison = f" ({before:,} before this update)" if before is not None and before != current else ""
        edition = "Collector’s Edition" if row["edition"] == "Collector's" else row["edition"]
        forecasts.append(f"The {edition} forecast is {current:,} copies{comparison}.")

    count = len(changes)
    title = f'Lio updated {count} {"file" if count == 1 else "files"}' if count else "Latest Lio update"
    detail = " ".join([*(r["headline"] + " " + r["balance"] for r in receipts), *(f["title"] for f in findings), *forecasts])
    return {**drop, "title": title, "detail": detail, "receipts": receipts, "findings": findings, "forecasts": forecasts}
