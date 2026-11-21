"""Deterministic, shift-constrained pack-out planning for the two editions.

The planner is intentionally independent of SQLite: the truth engine can pass its
serialized ``editions``, ``parts``, ``inbound`` and ``shifts`` payload directly.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

SLOT = timedelta(minutes=30)
CE = "FG-GH6-CE"
STD = "FG-GH6-STD"


def _dt(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def _max_units(stock, recipe, limit):
    if limit <= 0 or not recipe:
        return 0
    return max(0, min(int(limit), *(int(stock.get(part, 0) // qty) for part, qty in recipe.items())))


def _feasible_pairs(stock, ce_recipe, std_recipe, ce_limit, std_limit):
    """Return boundary candidates for the two-variable integer packing LP."""
    ce_limit, std_limit = int(ce_limit), int(std_limit)
    candidates = {0, ce_limit}
    for part, qty in ce_recipe.items():
        if qty:
            candidates.add(min(ce_limit, int(stock.get(part, 0) // qty)))
    for part, qty in std_recipe.items():
        if qty and part in ce_recipe:
            candidates.add(min(ce_limit, int(stock.get(part, 0) // ce_recipe[part])))
    pairs = []
    for ce_units in sorted(candidates):
        remaining = {part: stock.get(part, 0) - ce_units * qty for part, qty in ce_recipe.items()}
        if any(value < 0 for value in remaining.values()):
            continue
        std_units = _max_units(remaining, std_recipe, std_limit)
        pairs.append((ce_units, std_units))
    # Also include the STD-first corner; it can be missed when the CE recipe
    # has no shared parts.
    std_units = _max_units(stock, std_recipe, std_limit)
    pairs.append((0, std_units))
    return sorted(set(pairs))


def _consume(stock, recipes, quantities):
    for edition, units in quantities.items():
        for part, qty in recipes[edition].items():
            stock[part] = stock.get(part, 0) - units * qty


def _normalise(truth):
    editions = truth["editions"]
    parts = truth.get("parts", {})
    recipes = {
        pid: dict(editions[pid].get("needs") or {
            part: row["unit_usage"][pid] for part, row in parts.items()
            if pid in row.get("unit_usage", {})
        })
        for pid in editions
    }
    stock = {part: row.get("on_hand", 0) for part, row in parts.items()
             if not row.get("embedded_in")}
    return editions, recipes, stock


def _run(truth, weight):
    editions, recipes, inventory = _normalise(truth)
    ids = [pid for pid in (CE, STD) if pid in editions]
    if len(ids) != 2:
        ids = sorted(editions)
    ce_id, std_id = ids[0], ids[1]
    stock = defaultdict(float, inventory)
    arrivals = defaultdict(list)
    for item in truth.get("inbound", []):
        if item.get("held") or not item.get("earliest") or item.get("quantity", 0) <= 0:
            continue
        arrivals[_dt(item["earliest"])].append(item)
    packed = {pid: int(editions[pid].get("packed", 0)) for pid in ids}
    rows = []
    first_stop = {pid: None for pid in ids}
    shifts = [(_dt(start), _dt(end)) for start, end in truth.get("shifts", [])]
    for start, end in shifts:
        cursor = start
        while cursor < end:
            for when in sorted(key for key in arrivals if key <= cursor):
                for item in arrivals.pop(when):
                    stock[item["material"]] += item["quantity"]
            hours = (min(end, cursor + SLOT) - cursor).total_seconds() / 3600
            limits = {
                pid: max(0, min(int(editions[pid]["target"] - packed[pid]),
                                int(editions[pid]["rate"] * hours)))
                for pid in ids
            }
            candidates = _feasible_pairs(stock, recipes[ce_id], recipes[std_id],
                                         limits[ce_id], limits[std_id])
            # Keep both baselines in the candidate set, then select the best
            # weighted point. Ties prefer CE, making the result stable.
            ce_first_units = _max_units(stock, recipes[ce_id], limits[ce_id])
            ce_first = (ce_first_units, _max_units(
                {p: stock.get(p, 0) - ce_first_units * q for p, q in recipes[ce_id].items()},
                recipes[std_id], limits[std_id]))
            std_first = (0, _max_units(stock, recipes[std_id], limits[std_id]))
            candidates = set(candidates) | {ce_first, std_first, (ce_first_units, 0)}
            if weight >= 1:
                chosen = max(candidates, key=lambda pair: (pair[0], -pair[1]))
            elif weight <= 0:
                chosen = max(candidates, key=lambda pair: (pair[1], -pair[0]))
            else:
                chosen = max(candidates, key=lambda pair: (
                    weight * pair[0] + pair[1], pair[0], pair[1]))
            quantities = {ce_id: chosen[0], std_id: chosen[1]}
            _consume(stock, recipes, quantities)
            for pid in ids:
                packed[pid] += quantities[pid]
                planned = limits[pid]
                if quantities[pid] < planned and first_stop[pid] is None:
                    caps = {part: int(stock.get(part, 0) // qty)
                            for part, qty in recipes[pid].items() if qty}
                    first_stop[pid] = min(caps, key=caps.get) if caps else None
            if any(quantities.values()):
                rows.append({"start": cursor.isoformat(), "end": (cursor + SLOT).isoformat(),
                             "CE": quantities[ce_id], "STD": quantities[std_id],
                             "first_stop": {pid: first_stop[pid] for pid in ids if first_stop[pid]}})
            cursor += SLOT
    totals = {pid: packed[pid] for pid in ids}
    return {"weight": weight, "packed": totals, "units": sum(totals.values()),
            "first_stop": first_stop, "buckets": rows}


def allocation_rules(ce_shipped, preorder_count=72000):
    """Return transparent, human-owned rules for the numbered CE copies."""
    shipped = max(0, min(int(ce_shipped), preorder_count))
    return {
        "human_decision": True,
        "owner": "Head of Procurement / Head of Sales",
        "needs_to_know": ["pre-order timestamp/order number", "customer tier", "region/legal allocation constraints"],
        "rules": [
            {"name": "first-come by order number", "gets": shipped,
             "no_copy": f"orders ranked {shipped + 1:,}–{preorder_count:,}"},
            {"name": "highest-tier first", "gets": shipped,
             "no_copy": "lower-tier orders after tier quotas are filled; exact customers require tier data"},
            {"name": "region split", "gets": shipped,
             "no_copy": "the last-ranked orders within each region after proportional regional quotas"},
        ],
        "consequence": f"{preorder_count - shipped:,} numbered pre-orders remain unfulfilled under every rule.",
    }


def pareto_frontier(runs):
    points = {}
    for run in runs:
        ce = run["packed"].get(CE, run["packed"].get("CE", 0))
        std = run["packed"].get(STD, run["packed"].get("STD", 0))
        points[(ce, std)] = run
    frontier = []
    for point, run in sorted(points.items()):
        if not any(other[0] >= point[0] and other[1] >= point[1] and other != point
                   for other in points):
            frontier.append(run)
    return sorted(frontier, key=lambda run: (run["packed"].get(CE, run["packed"].get("CE", 0)),
                                              run["packed"].get(STD, run["packed"].get("STD", 0))))


def plan(truth, changes=None, weights=(0.0, 0.25, 0.5, 0.75, 1.0)):
    """Plan several CE-vs-STD objective weights and return the Pareto frontier.

    ``changes`` accepts ``{"part_arrives_earlier": {"CMP-X": hours},
    "release_quarantined": {"CMP-X": units}, "restore_stock": {"CMP-X": units}}``.
    """
    scenario = {**truth, "editions": {k: dict(v) for k, v in truth["editions"].items()},
                "parts": {k: dict(v) for k, v in truth.get("parts", {}).items()},
                "inbound": [dict(item) for item in truth.get("inbound", [])]}
    changes = changes or {}
    earlier = changes.get("part_arrives_earlier", {})
    for item in scenario["inbound"]:
        hours = earlier.get(item.get("material"), 0)
        if hours and item.get("earliest"):
            item["earliest"] = (_dt(item["earliest"]) - timedelta(hours=hours)).isoformat()
    for key in ("release_quarantined", "restore_stock"):
        for part, units in changes.get(key, {}).items():
            if part not in scenario["parts"]:
                raise ValueError(f"Unknown part: {part}")
            scenario["parts"][part]["on_hand"] = scenario["parts"][part].get("on_hand", 0) + units
    runs = [_run(scenario, float(weight)) for weight in weights]
    frontier = pareto_frontier(runs)
    best = max(runs, key=lambda run: (run["units"], run["packed"].get(CE, 0)))
    baseline = _run(scenario, 1.0)
    baseline_std = _run(scenario, 0.0)
    for run in runs:
        run["gain_vs_ce_first"] = run["units"] - baseline["units"]
        run["gain_vs_std_first"] = run["units"] - baseline_std["units"]
    return {"runs": runs, "frontier": frontier, "best": best,
            "allocation": allocation_rules(best["packed"].get(CE, 0)),
            "baseline": {"ce_first": baseline, "std_first": baseline_std}}


TOOLS = [{
    "name": "packplan",
    "description": "Build a deterministic 30-minute CE/STD pack-out plan and what-if frontier.",
    "parameters": {"type": "object", "properties": {"changes": {"type": "object"}}},
    "handler": plan,
}]


def _workbook_truth(path):
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True, read_only=True)
    sheets = {ws.title: list(ws.values) for ws in wb.worksheets}
    ed_rows = sheets["Editions"][3:]
    editions = {}
    for row in ed_rows:
        if not row[1]:
            continue
        pid = row[1]
        editions[pid] = {"target": int(row[2]), "packed": int(row[4]), "rate": int(row[6])}
    part_rows = sheets["Parts"][3:]
    parts = {}
    for row in part_rows:
        if not row[0]:
            continue
        parts[row[0]] = {"on_hand": int(row[5]), "unit_usage": {STD: row[2], CE: row[3]}}
    for pid in editions:
        editions[pid]["needs"] = {part: usage["unit_usage"][pid] for part, usage in parts.items()
                                  if usage["unit_usage"].get(pid)}
    shifts = []
    for row in sheets["Shifts"][1:]:
        if not row[0]:
            continue
        day = row[0]
        date = "2026-11-21" if day == "Saturday" else "2026-11-22"
        start, end = row[1].replace("–", "-").split("-")
        shifts.append((f"{date}T{start}:00+01:00", f"{date}T{end}:00+01:00"))
    inbound = []
    for row in sheets["Inbound"][1:]:
        if row[0]:
            inbound.append({"material": row[1], "quantity": row[2], "earliest": f"{row[6]}T12:00:00+01:00",
                            "held": "hold" in str(row[8] or "").lower()})
    return {"editions": editions, "parts": parts, "inbound": inbound, "shifts": shifts}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Print the CE/STD pack-out frontier.")
    parser.add_argument("--workbook", type=Path, default=Path("case-data/soony/context/launch_plan_GH6.xlsx"))
    args = parser.parse_args(argv)
    report = plan(_workbook_truth(args.workbook))
    print("# Pack-out plan\n")
    print("| Weight w (CE) | CE packed | STD packed | Total | Gain vs CE-first |")
    print("|---:|---:|---:|---:|---:|")
    for run in report["runs"]:
        print(f'| {run["weight"]:.2f} | {run["packed"].get(CE, 0):,} | {run["packed"].get(STD, 0):,} | '
              f'{run["units"]:,} | {run["gain_vs_ce_first"]:+,} |')
    print("\n## Numbered Collector's Edition allocation\n")
    print(f'Human decision owner: **{report["allocation"]["owner"]}**. '
          f'{report["allocation"]["consequence"]}')


if __name__ == "__main__":
    main()
