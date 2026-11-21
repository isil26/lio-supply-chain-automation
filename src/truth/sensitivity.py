"""Paired what-if forecasts over the serialized readiness inputs.

PO actual minus promised date is a day-resolution proxy for residual arrival lag.
Use one completed, positive-quantity PO line per PO/line, with observed delivery
before the first forecast day. Sample nonnegative lateness empirically for
suppliers with at least five lines. This replaces the mode prior rather than
adding historical end-to-end delay to it. Open/late outstanding orders are
censored, and history may include transit as well as handling. Suppliers with
sparse or missing history use readiness's triangular mode priors.

Replay the readiness model's fixed shifts, 30-minute buckets and CE-first
allocation, using the rounded usable stock in its serialized output. Reuse
each shipment's random draws across changes (including newly unheld shipments).
Criticality counts trials where a part ties for the lowest material capacity
at either edition's first material stop. A trial counts once per component.
Combined on-time probability requires every edition to reach its target.
Stock additions assume usable units at first shift start. Releasing a dock
hold retains its modeled ETA unless the caller supplies a new one. These are
conditional scenarios, with no change to approval or shipment state.
"""

import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timedelta
import math
from pathlib import Path
import random
import sqlite3

from src.docs import documents
from src.ingest.store import DB, ROOT, day, rows
from src.truth import LAG_HOURS, MODEL_RUNS, SLOT, readiness


SEED = 1029
CHANGE_FIELDS = {"shipment_days", "supplier_days", "add_units", "release_shipments", "shipment_earliest"}


def calibrate_supplier_lags(con, *, before=None, min_samples=5):
    """Return empirical lag samples (hours), counts and source rows by supplier."""
    if min_samples < 1:
        raise ValueError("min_samples must be positive")
    cutoff = day(before) if before is not None else None
    latest = {}
    for row in rows(con, "po"):
        key = row["po_number"], row["po_line"]
        source = row["source"]
        priority = ("legacy" not in source["file"].lower(), source["file"], source["row"])
        if key not in latest or priority > latest[key][0]:
            latest[key] = priority, row

    samples = defaultdict(list)
    for _, row in latest.values():
        if row["quantity"] <= 0 or row["status"] not in {"delivered", "received", "closed"}:
            continue
        promised = day(row["promised_date"]) if row["promised_date"] else None
        actual = day(row["actual_delivery_date"]) if row["actual_delivery_date"] else None
        if promised and actual and (cutoff is None or actual < cutoff) and actual >= day(row["order_date"]):
            samples[row["supplier_id"]].append((max(0, (actual - promised).days) * 24, row["source"]))

    return {
        supplier: {
            "method": "empirical" if len(values) >= min_samples else "mode_prior",
            "sample_count": len(values),
            "hours": sorted(hours for hours, _ in values) if len(values) >= min_samples else [],
            "evidence": [source for _, source in values],
        }
        for supplier, values in sorted(samples.items())
    }


def _datetime(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Scenario quantities and shifts must be finite numbers")
    return value


class _Replay:
    def __init__(self, truth, lag_profiles, trials, seed):
        if not isinstance(trials, int) or isinstance(trials, bool) or trials < 1:
            raise ValueError("trials must be a positive integer")
        self.trials = trials
        self.editions = truth["editions"]
        self.ids = sorted(self.editions, key=lambda pid: "CE" not in pid)
        parts = {part: row for part, row in truth["parts"].items() if not row.get("embedded_in")}
        self.stock = {part: row["on_hand"] for part, row in parts.items()}
        self.recipes = [
            [(part, row["unit_usage"][pid]) for part, row in parts.items() if pid in row["unit_usage"]]
            for pid in self.ids
        ]
        self.targets = [self.editions[pid]["target"] for pid in self.ids]
        self.packed = [self.editions[pid]["packed"] for pid in self.ids]
        self.slots = []
        self.plans = []
        for start, end in truth["shifts"]:
            cursor, end = _datetime(start), _datetime(end)
            while cursor < end:
                hours = (min(end, cursor + SLOT) - cursor).total_seconds() / 3600
                self.slots.append(cursor)
                self.plans.append([math.floor(self.editions[pid]["rate"] * hours) for pid in self.ids])
                cursor += SLOT

        self.inbound = {item["id"]: item for item in truth["inbound"]}
        self.suppliers = {item.get("supplier") for item in self.inbound.values()} - {None, ""}
        priors = truth.get("model", {}).get("lag_hours", LAG_HOURS)
        self.lags = {}
        for sid, item in self.inbound.items():
            hours = lag_profiles.get(item.get("supplier"), {}).get("hours")
            rng = random.Random(f"{seed}:{sid}")
            if hours:
                draws = rng.choices(hours, k=trials)
            else:
                low, most, high = priors.get(item["mode"], (0, 4, 12))
                draws = [rng.triangular(low, high, most) for _ in range(trials)]
            self.lags[sid] = [timedelta(hours=lag) for lag in draws]
        self.arrival_cache = {}

    def _schedules(self, changes):
        unknown = changes.keys() - CHANGE_FIELDS
        if unknown:
            raise ValueError(f"Unknown scenario fields: {sorted(unknown)}")
        shipment_days = changes.get("shipment_days", {})
        supplier_days = changes.get("supplier_days", {})
        release = set(changes.get("release_shipments", ()))
        overrides = changes.get("shipment_earliest", {})
        unknown = (shipment_days.keys() | release | overrides.keys()) - self.inbound.keys()
        if unknown:
            raise ValueError(f"Unknown shipment IDs: {sorted(unknown)}")
        if supplier_days.keys() - self.suppliers:
            raise ValueError(f"Unknown supplier IDs: {sorted(supplier_days.keys() - self.suppliers)}")

        vectors = []
        arrivals = []
        for sid, item in self.inbound.items():
            slip = _number(shipment_days.get(sid, 0)) + _number(supplier_days.get(item.get("supplier"), 0))
            earliest = _datetime(overrides.get(sid, item["earliest"]))
            if not earliest or item["held"] and sid not in release or item["quantity"] <= 0:
                continue
            earliest += timedelta(days=slip)
            key = sid, earliest
            if key not in self.arrival_cache:
                self.arrival_cache[key] = [
                    bisect_left(self.slots, earliest + lag) for lag in self.lags[sid]
                ]
            vector = self.arrival_cache[key]
            if min(vector) < len(self.slots):
                vectors.append(vector)
                arrivals.append((item["material"], item["quantity"]))
        # A shipment only affects pack-out when it crosses a slot boundary.
        # Replay identical slot schedules once and give each its trial weight.
        return Counter(zip(*vectors)) if vectors else {(): self.trials}, arrivals

    def run(self, changes):
        stock = dict(self.stock)
        for part, units in changes.get("add_units", {}).items():
            if part not in stock:
                raise ValueError(f"Unknown independently stocked component: {part}")
            if _number(units) < 0:
                raise ValueError("Stock additions must be nonnegative")
            stock[part] += units

        schedules, arrivals = self._schedules(changes)
        totals = [Counter() for _ in self.ids]
        combined = Counter()
        on_time = 0
        first_stops = [Counter() for _ in self.ids]
        critical = Counter()
        for schedule, weight in schedules.items():
            due = defaultdict(list)
            for slot, arrival in zip(schedule, arrivals):
                due[slot].append(arrival)
            inventory = dict(stock)
            packed = self.packed.copy()
            stopped = set()
            bottlenecks = set()
            for slot, plans in enumerate(self.plans):
                for part, qty in due.get(slot, ()):
                    inventory[part] = inventory.get(part, 0) + qty
                for index, recipe in enumerate(self.recipes):
                    planned = min(plans[index], self.targets[index] - packed[index])
                    if planned <= 0 or not recipe:
                        continue
                    caps = [math.floor(inventory[part] / amount) for part, amount in recipe]
                    capacity = min(caps)
                    units = max(0, min(planned, capacity))
                    if capacity < planned and index not in stopped:
                        stopped.add(index)
                        for (part, _), cap in zip(recipe, caps):
                            if cap == capacity:
                                first_stops[index][part] += weight
                                bottlenecks.add(part)
                    if units:
                        packed[index] += units
                        for part, amount in recipe:
                            inventory[part] -= units * amount

            for part in bottlenecks:
                critical[part] += weight
            for total, units in zip(totals, packed):
                total[units] += weight
            combined[sum(packed)] += weight
            if all(units >= target for units, target in zip(packed, self.targets)):
                on_time += weight

        def summary(counts, successes):
            def percentile(rank):
                index = round((self.trials - 1) * rank)
                for units, count in sorted(counts.items()):
                    index -= count
                    if index < 0:
                        return units

            return {
                "expected_packed": sum(units * count for units, count in counts.items()) / self.trials,
                "probability": successes / self.trials,
                "p10": percentile(0.10),
                "p50": percentile(0.50),
                "p90": percentile(0.90),
            }

        return {
            "runs": self.trials,
            "combined": summary(combined, on_time),
            "editions": {
                pid: dict(summary(total, sum(count for units, count in total.items() if units >= target)),
                          first_stop_trials=dict(sorted(stops.items())))
                for pid, total, target, stops in zip(self.ids, totals, self.targets, first_stops)
            },
            "criticality": {part: critical[part] / self.trials for part in sorted(stock)},
        }


def counterfactual(truth, changes, *, lag_profiles=None, trials=MODEL_RUNS, seed=SEED):
    """Return JSON-safe forecast metrics without mutating readiness.

    Changes is a dict of shipment_days (shipment ID to signed days),
    supplier_days (supplier ID to signed days), add_units (component ID to
    nonnegative quantity), release_shipments (shipment IDs), and optionally
    shipment_earliest (shipment ID to ISO datetime with offset). Both slips add
    to the ETA, after any ETA override. Held freight requires explicit release.
    Pass calibrated profiles from calibrate_supplier_lags to match the CLI.
    """
    return _Replay(truth, lag_profiles or {}, trials, seed).run(changes)


def plan_b_cases(truth, docs):
    """Build cited stock and hold scenarios from the reconciled evidence."""
    for item in truth["inbound"]:
        if not item["held"] or item["quantity"] <= 0:
            continue
        sid = item["id"]
        label = f'Release {item["mode"]} lot {item.get("reference") or sid} ({item["quantity"]:,.0f} units)'
        evidence = item.get("evidence", [])
        if item["earliest"]:
            yield {
                "label": f"{label} at scheduled ETA",
                "changes": {"release_shipments": [sid]},
                "evidence": evidence,
            }
        if item["mode"] == "air" and truth["shifts"]:
            yield {
                "label": f"{label} if at DC before handling by first shift",
                "changes": {"release_shipments": [sid], "shipment_earliest": {sid: truth["shifts"][0][0]}},
                "evidence": evidence,
            }

    for doc in docs:
        for offer in doc["fields"].get("available_offer", []):
            detail = offer["value"]
            part = truth["parts"].get(detail.get("material"), {})
            qty = min(detail["quantity"], part.get("shortfall", 0))
            if qty > 0 and not part.get("embedded_in"):
                yield {
                    "label": f'Add {qty:,} usable units of {part["label"]} at first shift',
                    "changes": {"add_units": {part["material"]: qty}},
                    "evidence": [offer["citation"], *part.get("evidence", [])],
                }

    for issue in truth["issues"]:
        part = truth["parts"].get(issue["material"])
        if issue["kind"] == "quality_hold" and part and not part.get("embedded_in") and issue["quantity"] > 0:
            yield {
                "label": f'Release {issue["quantity"]:,} quarantined units of {part["label"]} at first shift',
                "changes": {"add_units": {part["material"]: issue["quantity"]}},
                "evidence": issue.get("evidence", []),
            }


def sensitivity(truth, *, lag_profiles=None, cases=(), trials=MODEL_RUNS, seed=SEED):
    """Return a paired baseline and per-shipment, supplier and custom deltas."""
    replay = _Replay(truth, lag_profiles or {}, trials, seed)
    baseline = replay.run({})
    variants = []
    groups = (("Shipment", "shipment_days", replay.inbound), ("Supplier", "supplier_days", replay.suppliers))
    for scope, field, ids in groups:
        for ref in sorted(ids):
            items = ([replay.inbound[ref]] if field == "shipment_days"
                     else [item for item in replay.inbound.values() if item.get("supplier") == ref])
            for days in (-1, 1):
                variants.append({
                    "label": f"{scope} {ref} {days:+d} day",
                    "changes": {field: {ref: days}},
                    "evidence": [source for item in items for source in item.get("evidence", [])],
                })

    def delta(before, after):
        return {metric: after[metric] - before[metric] for metric in ("expected_packed", "probability")}

    results = []
    for case in (*variants, *cases):
        scenario = replay.run(case["changes"])
        results.append(dict(case, delta={
            "combined": delta(baseline["combined"], scenario["combined"]),
            "editions": {pid: delta(baseline["editions"][pid], result)
                         for pid, result in scenario["editions"].items()},
        }))
    return {"baseline": baseline, "scenarios": results}


def _citations(evidence):
    locations = defaultdict(set)
    for source in evidence:
        place = source.get("file") or source.get("source_file")
        if not place:
            continue
        if source.get("sheet"):
            place += f' / {source["sheet"]}'
        row, page = source.get("row"), source.get("page")
        if row is not None:
            locations[place].add(f"row {row}")
        elif page is not None:
            locations[place].add(f"p. {page}")
        else:
            locations[place]
    return "; ".join(
        place + (" " + ", ".join(sorted(refs)) if refs else "")
        for place, refs in sorted(locations.items())
    ).replace("|", r"\|") or "—"


def _print_markdown(truth, profiles, report):
    baseline = report["baseline"]
    print("# Launch readiness sensitivity\n")
    print(f'{baseline["runs"]} paired trials. Combined P(on time) requires every edition to meet target. '
          'Stock scenarios assume usable units at the first shift. Supplier and shipment shifts preserve existing holds.\n')
    print("## Supplier lag calibration\n")
    print("Empirical lag uses the positive part of actual minus promised delivery for completed PO lines. "
          "Suppliers with fewer than five observations use the triangular mode prior.\n")
    print("| Supplier | Method | PO lines | P50 / P90 lag (h) | Evidence |")
    print("|---|---|---:|---:|---|")
    suppliers = {item.get("supplier") for item in truth["inbound"]}
    for supplier in sorted(suppliers, key=lambda item: item or ""):
        profile = profiles.get(supplier, {})
        hours = profile.get("hours", [])
        quantiles = " / ".join(str(hours[round((len(hours) - 1) * rank)]) for rank in (0.5, 0.9)) if hours else "—"
        print(f'| {supplier or "Unmapped"} | {profile.get("method", "mode_prior")} | '
              f'{profile.get("sample_count", 0)} | {quantiles} | {_citations(profile.get("evidence", []))} |')

    print("\n## Baseline\n")
    print("| Scope | Expected packed | P10 / P50 / P90 | P(on time) | Target evidence |")
    print("|---|---:|---:|---:|---|")
    targets = {pid: edition.get("evidence", [])[:1] for pid, edition in truth["editions"].items()}
    for scope, row in [("Combined", baseline["combined"]), *baseline["editions"].items()]:
        evidence = targets[scope] if scope in targets else [source for refs in targets.values() for source in refs]
        print(f'| {scope} | {row["expected_packed"]:,.1f} | {row["p10"]:,} / {row["p50"]:,} / {row["p90"]:,} | '
              f'{row["probability"]:.1%} | {_citations(evidence)} |')

    print("\n## First material stop criticality\n")
    print("| Component | Share of trials |")
    print("|---|---:|")
    for part, share in sorted(baseline["criticality"].items(), key=lambda item: (-item[1], item[0])):
        print(f"| {part} | {share:.1%} |")

    print("\n## Scenario deltas\n")
    editions = baseline["editions"]
    print("| Scenario | Combined Δ units / pp | " + " | ".join(f"{pid} Δ units / pp" for pid in editions) + " | Evidence |")
    print("|---|---:|" + "---:|" * len(editions) + "---|")
    for case in report["scenarios"]:
        delta = case["delta"]
        metrics = [delta["combined"], *(delta["editions"][pid] for pid in editions)]
        cells = " | ".join(f'{row["expected_packed"]:+,.1f} / {row["probability"] * 100:+.1f}' for row in metrics)
        label = case["label"].replace("|", r"\|")
        print(f'| {label} | {cells} | {_citations(case.get("evidence", []))} |')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--trials", type=int, default=MODEL_RUNS)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--add", action="append", default=[], metavar="COMPONENT=UNITS",
                        help="run an additional stock scenario (repeatable)")
    args = parser.parse_args(argv)
    if args.trials < 1:
        parser.error("--trials must be positive")
    try:
        with closing(sqlite3.connect(args.db.resolve().as_uri() + "?mode=ro", uri=True)) as con:
            con.row_factory = sqlite3.Row
            truth = readiness(con, args.data)
            first_day = truth["shifts"][0][0] if truth["shifts"] else truth["deadline"]
            profiles = calibrate_supplier_lags(con, before=first_day)
            cases = list(plan_b_cases(truth, documents(con)))
        for spec in args.add:
            part, units = spec.split("=", 1)
            cases.append({"label": f"Add {units} usable units of {part}",
                          "changes": {"add_units": {part: float(units)}},
                          "evidence": truth["parts"].get(part, {}).get("evidence", [])})
        report = sensitivity(truth, lag_profiles=profiles, cases=cases, trials=args.trials, seed=args.seed)
    except (ValueError, sqlite3.Error) as error:
        parser.error(str(error))
    _print_markdown(truth, profiles, report)


if __name__ == "__main__":
    main()
