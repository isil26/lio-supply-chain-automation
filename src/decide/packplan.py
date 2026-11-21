"""Exact, deterministic pack-out planner for the two Grand Heist 6 editions.

Built on the truth engine (``src.truth.readiness``): independent recipes (parts
supplied fitted inside another part are excluded), usable stock after
adjustments, non-held inbound with earliest arrival plus a handling lag, the
shift windows, per-edition rates and remaining targets.

Method (proof sketch in docs/PACKPLAN.md). For final totals (X CE, Y STD) the
schedule that packs each edition as LATE as its hourly rate allows has the
pointwise minimum cumulative part consumption among all rate-feasible
schedules.  Part constraints only say "cumulative consumption <= cumulative
availability", availability never decreases, so (X, Y) is feasible iff that
late schedule is.  Feasibility becomes a closed form in (X, Y), the maximum
Y(X) is computed exactly for every integer X, and any weighted objective
w*CE + STD is maximised exactly by scanning X.  An early forward schedule for
the chosen point is then built with the same feasibility oracle.  The two
baseline policies (CE first, STD first; same per-slot logic as
``truth.simulate``) are feasible points, so the w=1 optimum is never worse
than either.  Pure Python, ~0.1 s.
"""

from __future__ import annotations

import argparse
import math
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path
from typing import Any

from src.truth import LAG_HOURS, SLOT

CE_MAX = 1_000_000  # "Collector's first" lexicographic weight
DEFAULT_WEIGHTS = (0, 0.5, 1, 2, 5, CE_MAX)
MAGNET_NOTE = ("assumes magnets are supplier-fitted; if the BOM line is real, "
               "CE cannot be packed")


# ---------------------------------------------------------------- inputs
def _dt(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def arrival_lag_hours(mode: str, lag: str = "median") -> float:
    """Handling lag after the earliest arrival (same triangular as simulate)."""
    low, most, high = LAG_HOURS.get(mode, (0, 4, 12))
    if lag == "earliest":
        return 0.0
    if lag == "mode":
        return float(most)
    if lag == "mean":
        return (low + most + high) / 3
    if lag != "median":
        raise ValueError(f"Unknown lag rule: {lag}")
    if high == low:
        return float(low)
    if (most - low) / (high - low) >= 0.5:
        return low + math.sqrt(0.5 * (high - low) * (most - low))
    return high - math.sqrt(0.5 * (high - low) * (high - most))


def _ids(editions):
    ce = next((pid for pid in sorted(editions) if "CE" in pid), None)
    std = next((pid for pid in sorted(editions) if pid != ce), None)
    if ce is None or std is None:
        raise ValueError("Need one CE and one standard edition")
    return ce, std


def _inputs(truth, lag="median", magnet_fitted=True, held_released=()):
    editions = truth["editions"]
    ce, std = _ids(editions)
    parts = truth.get("parts", {})
    skip = {p for p, row in parts.items() if row.get("embedded_in") and magnet_fitted}
    needs = {pid: {} for pid in (ce, std)}
    stock = {}
    for part, row in parts.items():
        if part in skip:
            continue
        stock[part] = row["on_hand"] if (magnet_fitted or not row.get("embedded_in")) else row.get("raw_stock", 0)
        for pid in (ce, std):
            qty = row.get("unit_usage", {}).get(pid)
            if qty:
                needs[pid][part] = qty
    arrivals = []
    for item in truth.get("inbound", []):
        released = item["material"] in held_released
        if (item.get("held") and not released) or not item.get("earliest") or item["quantity"] <= 0:
            continue
        if item["material"] in skip:
            continue
        when = _dt(item["earliest"]) + timedelta(hours=arrival_lag_hours(item.get("mode"), lag))
        arrivals.append((when, item["material"], item["quantity"]))
    arrivals.sort()
    shifts = [(_dt(a), _dt(b)) for a, b in truth["shifts"]]
    rem = {pid: max(0, int(editions[pid]["target"] - editions[pid]["packed"])) for pid in (ce, std)}
    rate = {pid: editions[pid]["rate"] for pid in (ce, std)}
    return {"ce": ce, "std": std, "needs": needs, "stock": stock, "arrivals": arrivals,
            "shifts": shifts, "rem": rem, "rate": rate}


def _slots(inp):
    """30-minute buckets with caps and cumulative availability at slot start."""
    ce, std = inp["ce"], inp["std"]
    slots, supply, nxt = [], dict(inp["stock"]), 0
    for start, end in inp["shifts"]:
        cursor = start
        while cursor < end:
            while nxt < len(inp["arrivals"]) and inp["arrivals"][nxt][0] <= cursor:
                _, part, qty = inp["arrivals"][nxt]
                supply[part] = supply.get(part, 0) + qty
                nxt += 1
            hours = (min(end, cursor + SLOT) - cursor).total_seconds() / 3600
            slots.append({"start": cursor, "S": dict(supply),
                          "cap": {pid: math.floor(inp["rate"][pid] * hours) for pid in (ce, std)}})
            cursor += SLOT
    for pid in (ce, std):  # capacity strictly after slot t
        run = 0
        for slot in reversed(slots):
            slot.setdefault("after", {})[pid] = run
            run += slot["cap"][pid]
    return slots


# -------------------------------------------------------------- baselines
def run_policy(inp, order, slots=None):
    """Per-slot priority policy, identical logic to truth.simulate (one trial)."""
    slots = slots or _slots(inp)
    ce, std = inp["ce"], inp["std"]
    packed = {ce: 0, std: 0}
    used = {}
    first_stop = {}
    for slot in slots:
        for pid in order:
            needs = inp["needs"][pid]
            planned = min(inp["rem"][pid] - packed[pid], slot["cap"][pid])
            if planned <= 0 or not needs:
                continue
            caps = {p: math.floor((slot["S"].get(p, 0) - used.get(p, 0)) / q) for p, q in needs.items()}
            units = max(0, min(planned, *caps.values()))
            if units < planned and pid not in first_stop:
                first_stop[pid] = min(caps, key=caps.get)
            packed[pid] += units
            for p, q in needs.items():
                used[p] = used.get(p, 0) + units * q
    return {"packed": packed, "units": sum(packed.values()), "first_stop": first_stop}


# ------------------------------------------------------- exact frontier
def _reduced(slots, part):
    """(slot index, supply) for the last slot of each constant-supply run."""
    out = []
    for t, slot in enumerate(slots):
        if t + 1 == len(slots) or slots[t + 1]["S"].get(part, 0) != slot["S"].get(part, 0):
            out.append((t, slot["S"].get(part, 0)))
    return out


def _frontier(inp, slots):
    """Return (ymax list indexed by X, constraint table)."""
    ce, std = inp["ce"], inp["std"]
    a, b = inp["needs"][ce], inp["needs"][std]
    total = {pid: sum(s["cap"][pid] for s in slots) for pid in (ce, std)}
    xcap = min(inp["rem"][ce], total[ce]) if a else 0
    ytop = min(inp["rem"][std], total[std]) if b else 0
    shared = []
    for part in set(a) | set(b):
        ap, bp = a.get(part, 0), b.get(part, 0)
        for t, supply in _reduced(slots, part):
            A, B = slots[t]["after"][ce], slots[t]["after"][std]
            if bp == 0:
                xcap = min(xcap, A + int(supply // ap))
            elif ap == 0:
                ytop = min(ytop, B + int(supply // bp))
            else:
                shared.append((ap, bp, supply, A, B))
    ymax = []
    for x in range(xcap + 1):
        y = ytop
        for ap, bp, supply, A, B in shared:
            left = supply - ap * max(0, x - A)
            if left < 0:
                y = -1
                break
            y = min(y, B + int(left // bp))
        if y < 0:
            break
        ymax.append(y)
    return ymax


def _hull(ymax):
    """Upper-hull vertices (X, Ymax): optimal for every non-negative weight."""
    pts, hull = list(enumerate(ymax)), []
    for p in pts:
        while len(hull) >= 2 and (hull[-1][0] - hull[-2][0]) * (p[1] - hull[-2][1]) >= \
                (p[0] - hull[-2][0]) * (hull[-1][1] - hull[-2][1]):
            hull.pop()
        hull.append(p)
    return hull


def _choose(ymax, w):
    w = Fraction(w).limit_denominator(10**6)
    return max(range(len(ymax)), key=lambda x: (w * x + ymax[x], x + ymax[x], x))


# ------------------------------------------------------ forward schedule
def _late(slots, pid, total):
    return [max(0, total - s["after"][pid]) for s in slots]  # cumulative through t


def _ok(inp, slots, t_from, tx, ty, px, py, xr, yr, tables):
    ce, std = inp["ce"], inp["std"]
    if xr < 0 or yr < 0:
        return False
    if xr > (slots[tx]["after"][ce] + slots[tx]["cap"][ce] if tx < len(slots) else 0):
        return False
    if yr > (slots[ty]["after"][std] + slots[ty]["cap"][std] if ty < len(slots) else 0):
        return False
    for ap, bp, rows in tables:
        for t, supply in rows:
            if t < t_from:
                continue
            cx = px + (max(0, xr - slots[t]["after"][ce]) if t >= tx else 0)
            cy = py + (max(0, yr - slots[t]["after"][std]) if t >= ty else 0)
            if ap * cx + bp * cy > supply:
                return False
    return True


def _forward(inp, slots, X, Y):
    """Earliest schedule reaching exactly (X, Y); CE decided first in a slot."""
    ce, std = inp["ce"], inp["std"]
    a, b = inp["needs"][ce], inp["needs"][std]
    tables = [(a.get(p, 0), b.get(p, 0), _reduced(slots, p)) for p in set(a) | set(b)]
    px = py = 0
    out = []
    for t, slot in enumerate(slots):
        got = {}
        for pid in (ce, std):
            rest = (X - px) if pid == ce else (Y - py)
            lo = max(0, rest - slot["after"][pid])
            hi = min(slot["cap"][pid], rest)
            def good(u):
                nx, ny = (px + u, py) if pid == ce else (px, py + u)
                ty = t if pid == ce else t + 1
                return _ok(inp, slots, t, t + 1, ty, nx, ny, X - nx, Y - ny, tables)
            if hi < lo or not good(lo):
                return None
            while lo < hi:  # largest feasible u (feasible set is an interval from lo)
                mid = (lo + hi + 1) // 2
                lo, hi = (mid, hi) if good(mid) else (lo, mid - 1)
            got[pid] = lo
            if pid == ce:
                px += lo
            else:
                py += lo
        out.append(got)
    return out if (px, py) == (X, Y) else None


def _describe(inp, slots, sched, w):
    ce, std = inp["ce"], inp["std"]
    packed = {ce: 0, std: 0}
    used, first_stop, buckets, events, paused = {}, {}, [], [], {}
    for slot, got in zip(slots, sched):
        for pid in (ce, std):
            needs = inp["needs"][pid]
            planned = min(inp["rem"][pid] - packed[pid], slot["cap"][pid])
            caps = {p: math.floor((slot["S"].get(p, 0) - used.get(p, 0)) / q) for p, q in needs.items()}
            blocker = min(caps, key=caps.get) if caps else None
            if got[pid] < planned and pid not in first_stop:
                first_stop[pid] = blocker
            stalled = bool(needs) and planned > 0 and got[pid] < planned
            tag = pid.split("-")[-1]
            if stalled and tag not in paused:
                paused[tag] = slot["start"]
                events.append({"at": slot["start"].isoformat(), "edition": tag,
                               "event": "pause" if got[pid] == 0 else "slow",
                               "part": blocker})
            elif not stalled and tag in paused and planned > 0:
                events.append({"at": slot["start"].isoformat(), "edition": tag, "event": "resume",
                               "part": None})
                del paused[tag]
            packed[pid] += got[pid]
            for p, q in needs.items():
                used[p] = used.get(p, 0) + got[pid] * q
        if got[ce] or got[std]:
            buckets.append({"start": slot["start"].isoformat(), "CE": got[ce], "STD": got[std]})
    return {"weight": w, "packed": packed, "units": sum(packed.values()),
            "first_stop": first_stop, "events": events, "buckets": buckets}


# ---------------------------------------------------------- public API
def allocation_rules(ce_shipped, preorder_count=72000):
    """Transparent, human-owned rules for the numbered CE copies.

    The data holds no customer-level pre-order records (only the fact that all
    72,000 numbered copies are pre-ordered), so each rule needs fields we do not have.
    """
    shipped = max(0, min(int(ce_shipped), preorder_count))
    short = preorder_count - shipped
    return {
        "human_decision": True,
        "owner": "Head of Procurement / Head of Sales",
        "data_available": "none at customer level: no order numbers, timestamps, tiers or regions in the data",
        "needs_to_know": ["pre-order timestamp / order number", "customer tier", "region and legal allocation constraints",
                          "whether refunds or a later ship date are acceptable"],
        "rules": [
            {"name": "first-come by order number", "gets": shipped,
             "no_copy": f"orders ranked {shipped + 1:,}-{preorder_count:,} by order time"},
            {"name": "highest-tier first", "gets": shipped,
             "no_copy": "lowest-tier orders once tier quotas fill; needs tier data"},
            {"name": "region split", "gets": shipped,
             "no_copy": "last-ranked orders inside each region after proportional quotas"},
        ],
        "consequence": f"{short:,} numbered pre-orders get no copy before the cutoff under every rule." if short
        else "All numbered pre-orders can be served.",
    }


def _solve(truth, weights, lag, magnet_fitted, held_released):
    inp = _inputs(truth, lag, magnet_fitted, held_released)
    slots = _slots(inp)
    ymax = _frontier(inp, slots)
    ce, std = inp["ce"], inp["std"]
    base = {name: run_policy(inp, order, slots) for name, order in
            (("ce_first", (ce, std)), ("std_first", (std, ce)))}
    best_base = max(base.values(), key=lambda r: r["units"])["units"]
    runs = []
    for w in weights:
        x = _choose(ymax, w)
        sched = _forward(inp, slots, x, ymax[x])
        if sched is None:  # exact fallback: latest schedule
            lx, ly = _late(slots, ce, x), _late(slots, std, ymax[x])
            sched = [{ce: lx[i] - (lx[i - 1] if i else 0), std: ly[i] - (ly[i - 1] if i else 0)}
                     for i in range(len(slots))]
        run = _describe(inp, slots, sched, w)
        run["gain_vs_ce_first"] = run["units"] - base["ce_first"]["units"]
        run["gain_vs_std_first"] = run["units"] - base["std_first"]["units"]
        run["gain_vs_best_baseline"] = run["units"] - best_base
        runs.append(run)
    frontier = [{"CE": x, "STD": y, "units": x + y} for x, y in _hull(ymax)]
    return {"inputs": {"ce": ce, "std": std, "remaining": inp["rem"], "rate_per_hour": inp["rate"],
                       "slots": len(slots), "usable_stock": inp["stock"],
                       "max_ce": len(ymax) - 1, "max_std_alone": ymax[0]},
            "baseline": base, "runs": runs, "frontier": frontier,
            "best": next((r for r in runs if r["weight"] == 1), max(runs, key=lambda r: r["units"]))}


def _apply(truth, changes):
    scenario = {**truth, "parts": {k: dict(v) for k, v in truth.get("parts", {}).items()},
                "inbound": [dict(i) for i in truth.get("inbound", [])]}
    for item in scenario["inbound"]:
        hours = changes.get("part_arrives_earlier", {}).get(item.get("material"), 0)
        if hours and item.get("earliest"):
            item["earliest"] = (_dt(item["earliest"]) - timedelta(hours=hours)).isoformat()
    for key in ("release_quarantined", "restore_stock"):
        for part, units in changes.get(key, {}).items():
            if part not in scenario["parts"]:
                raise ValueError(f"Unknown part: {part}")
            row = scenario["parts"][part]
            row["on_hand"] = row.get("on_hand", 0) + units
    return scenario


def plan(truth, changes=None, weights=DEFAULT_WEIGHTS, lag="median", magnet_fitted=True):
    """Pack plan for several CE weights w (CE worth w STD units; w=1 = max units).

    ``changes``: ``{"part_arrives_earlier": {part: hours}, "release_quarantined":
    {part: units}, "restore_stock": {part: units}, "release_held": [part]}``.
    Returns baseline policies, runs per weight, the Pareto hull, the allocation
    rules and, with changes, the delta against the unchanged plan.
    """
    changes = changes or {}
    held = tuple(changes.get("release_held", ()))
    base_report = _solve(truth, weights, lag, magnet_fitted, ())
    report = base_report
    if changes:
        report = _solve(_apply(truth, changes), weights, lag, magnet_fitted, held)
        ce, std = report["inputs"]["ce"], report["inputs"]["std"]
        deltas = []
        for new, old in zip(report["runs"], base_report["runs"]):
            deltas.append({"weight": new["weight"],
                           "units": new["units"] - old["units"],
                           "CE": new["packed"][ce] - old["packed"][ce],
                           "STD": new["packed"][std] - old["packed"][std]})
        report["delta_vs_unchanged"] = deltas
        top = deltas[-1]  # Collector's-first point
        report["preorders_saved"] = {"numbered_ce_copies": top["CE"],
                                     "note": "extra numbered CE copies at the Collector's-first point; "
                                             "which orders get them is the allocation decision"}
    ce = report["inputs"]["ce"]
    already = truth["editions"][ce]["packed"]
    report["allocation"] = allocation_rules(already + max(r["packed"][ce] for r in report["runs"]),
                                            preorder_count=truth["editions"][ce]["target"])
    report["assumptions"] = [f"arrival rule: earliest + {lag} handling lag (deterministic)", MAGNET_NOTE
                             if magnet_fitted else "magnet BOM line treated as real"]
    return report


def packplan(changes=None):
    """Agent tool: plan from the live truth engine (read-only)."""
    return summarize(plan(_load_truth(), changes))


def summarize(report):
    ce, std = report["inputs"]["ce"], report["inputs"]["std"]
    out = {"baseline": {k: {"CE": v["packed"][ce], "STD": v["packed"][std], "units": v["units"]}
                        for k, v in report["baseline"].items()},
           "runs": [{"w": r["weight"], "CE": r["packed"][ce], "STD": r["packed"][std], "units": r["units"],
                     "gain_vs_best_baseline": r["gain_vs_best_baseline"], "first_stop": r["first_stop"]}
                    for r in report["runs"]],
           "frontier": report["frontier"], "allocation": report["allocation"],
           "assumptions": report["assumptions"]}
    for key in ("delta_vs_unchanged", "preorders_saved"):
        if key in report:
            out[key] = report[key]
    return out


TOOLS = [{
    "name": "packplan",
    "description": "Exact pack-out plan for CE and STD from the truth engine (independent recipes, usable stock, "
                   "inbound, shifts): baselines, Pareto frontier over CE weight w, what-if changes.",
    "parameters": {"type": "object", "properties": {"changes": {"type": "object"}}},
    "handler": packplan,
}]


def _load_truth():
    import sqlite3
    from contextlib import closing

    from src.ingest.store import DB, ROOT
    from src.truth import readiness
    with closing(sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        return readiness(con, ROOT / "data")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Print the CE/STD pack-out plan.")
    parser.add_argument("--lag", default="median", choices=["median", "mode", "mean", "earliest"])
    parser.add_argument("--mc", action="store_true", help="also print truth.simulate() baselines (slower)")
    args = parser.parse_args(argv)
    truth = _load_truth()
    report = plan(truth, lag=args.lag)
    ce, std = report["inputs"]["ce"], report["inputs"]["std"]
    packed0 = {pid: truth["editions"][pid]["packed"] for pid in (ce, std)}
    print("# Pack-out plan\n")
    print(f"Assumption: {MAGNET_NOTE}.")
    print(f"Arrivals: earliest + {args.lag} handling lag; the cutoff is the last shift end. "
          f"Totals include already packed {packed0[std]:,} STD / {packed0[ce]:,} CE.\n")
    print("| Policy | CE total | STD total | Units added |")
    print("|---|---:|---:|---:|")
    for name, run in report["baseline"].items():
        print(f'| baseline {name} | {packed0[ce] + run["packed"][ce]:,} | {packed0[std] + run["packed"][std]:,} | {run["units"]:,} |')
    print("\n| w (CE value, STD=1) | CE total | STD total | Units added | Gain vs better baseline | First stop |")
    print("|---:|---:|---:|---:|---:|---|")
    for run in report["runs"]:
        label = "CE first" if run["weight"] == CE_MAX else f'{run["weight"]:g}'
        stop = ", ".join(f"{k.split('-')[-1]}: {v}" for k, v in run["first_stop"].items()) or "none"
        print(f'| {label} | {packed0[ce] + run["packed"][ce]:,} | {packed0[std] + run["packed"][std]:,} | '
              f'{run["units"]:,} | {run["gain_vs_best_baseline"]:+,} | {stop} |')
    print("\nPareto vertices (units added): " + "; ".join(f'CE {p["CE"]:,} / STD {p["STD"]:,}' for p in report["frontier"]))
    print("\n## What-if (vs unchanged, at w=1 and Collector's first)\n")
    cases = {"Restore 5,900 art books (CMP-GAM-008)": {"restore_stock": {"CMP-GAM-008": 5900}},
             "Release 5,600 quarantined statues (CMP-GAM-010)": {"release_quarantined": {"CMP-GAM-010": 5600}},
             "Game card air lot 12 h earlier (CMP-GAM-001)": {"part_arrives_earlier": {"CMP-GAM-001": 12}},
             "Release held game card lot (CMP-GAM-001)": {"release_held": ["CMP-GAM-001"]}}
    print("| Change | Units (w=1) | CE (w=1) | CE (Collector's first) | STD (Collector's first) |")
    print("|---|---:|---:|---:|---:|")
    for label, change in cases.items():
        d = plan(truth, change, weights=(1, CE_MAX), lag=args.lag)["delta_vs_unchanged"]
        print(f'| {label} | {d[0]["units"]:+,} | {d[0]["CE"]:+,} | {d[1]["CE"]:+,} | {d[1]["STD"]:+,} |')
    al = report["allocation"]
    print(f'\n## Numbered Collector\'s Edition allocation\n\nHuman decision, owner: **{al["owner"]}**. '
          f'{al["consequence"]} Data: {al["data_available"]}.')
    for rule in al["rules"]:
        print(f'- {rule["name"]}: {rule["gets"]:,} get a copy; no copy: {rule["no_copy"]}.')
    if args.mc:
        from src.truth import simulate
        needs = {pid: {p: q for p, row in truth["parts"].items() if not row.get("embedded_in")
                       for pid2, q in row["unit_usage"].items() if pid2 == pid} for pid in (ce, std)}
        stock = {p: row["on_hand"] for p, row in truth["parts"].items() if not row.get("embedded_in")}
        inbound = [{**i, "earliest": _dt(i["earliest"]) if i["earliest"] else None} for i in truth["inbound"]]
        shifts = [(_dt(a), _dt(b)) for a, b in truth["shifts"]]
        for mode in ("ce_first", "std_first"):
            sim = simulate(truth["editions"], needs, stock, inbound, shifts, mode=mode)
            print(f"\nsimulate() {mode}: " + ", ".join(f'{k.split("-")[-1]} p10/p50/p90 {v["p10"]:,}/{v["p50"]:,}/{v["p90"]:,}'
                                                         for k, v in sim.items()))


if __name__ == "__main__":
    main()
