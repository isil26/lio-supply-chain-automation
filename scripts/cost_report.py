#!/usr/bin/env python3
"""Report recorded LLM usage from the shared client log and SQLite agent traces."""

import argparse
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
HAMBURG = ZoneInfo("Europe/Berlin")


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    usd: Decimal = Decimal(0)
    missing: int = 0

    def add(self, row, cost_key):
        tokens = [number(row.get(key)) for key in ("input_tokens", "output_tokens")]
        cost = number(row.get(cost_key))
        self.input_tokens += int(tokens[0] or 0)
        self.output_tokens += int(tokens[1] or 0)
        self.usd += cost or Decimal(0)
        self.missing += int(None in (*tokens, cost))


def number(value):
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def day(value):
    try:
        if isinstance(value, (int, float)):
            stamp = datetime.fromtimestamp(value, timezone.utc)
        else:
            stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is not None:
            return stamp.astimezone(HAMBURG).date().isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        pass
    return "undated"


def objects(lines, warnings, source):
    for index, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError
        except ValueError:
            warnings.append(f"{source} record {index} could not be read.")
            continue
        yield row


def client_usage(path, days, runs, warnings):
    if not path.is_file():
        warnings.append("Shared client log is unavailable.")
        return
    with path.open(encoding="utf-8", errors="replace") as stream:
        for row in objects(stream, warnings, "Shared client log"):
            if row.get("status") == "cache":
                continue
            days[day(row.get("timestamp") or row.get("created_at"))].add(row, "cost_usd")
            if row.get("run_id"):
                runs[str(row["run_id"])].add(row, "cost_usd")


def trace_usage(path, days, runs, warnings):
    if not path.is_file():
        warnings.append("Agent database is unavailable.")
        return
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        con.execute("BEGIN")
        trace_columns = {row[1] for row in con.execute("PRAGMA table_info(agent_trace)")}
        if trace_columns:
            columns = ("created_at", "input_tokens", "output_tokens", "cost")
            select = ", ".join(col if col in trace_columns else f"NULL AS {col}" for col in columns)
            for row in con.execute(f"SELECT {select} FROM agent_trace"):
                values = dict(row)
                days[day(values["created_at"])].add(values, "cost")
        run_columns = {row[1] for row in con.execute("PRAGMA table_info(agent_runs)")}
        if {"id", "trace_json"} <= run_columns:
            for run_id, raw in con.execute("SELECT id, trace_json FROM agent_runs ORDER BY started"
                                           if "started" in run_columns
                                           else "SELECT id, trace_json FROM agent_runs ORDER BY id"):
                try:
                    trace = json.loads(raw or "[]")
                    if not isinstance(trace, list) or any(not isinstance(row, dict) for row in trace):
                        raise ValueError
                except ValueError:
                    warnings.append(f"Agent run {run_id} has an unreadable trace snapshot.")
                    continue
                for row in trace:
                    runs[str(run_id)].add(row, "cost")


def argument_amount(value):
    amount = number(value)
    if amount is None:
        raise argparse.ArgumentTypeError("expected a finite non-negative amount")
    return amount


def print_usage(label, usage, rate, budget):
    euros = usage.usd * rate
    missing = f" · {usage.missing} records with missing usage" if usage.missing else ""
    if label == "undated":
        budget = None
    warning = f" · OVER BUDGET (EUR {budget:.4f})" if budget is not None and euros > budget else ""
    print(f"    {label}: {usage.input_tokens:,} input / {usage.output_tokens:,} output tokens"
          f" · USD {usage.usd:.4f} · EUR {euros:.4f}{missing}{warning}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=ROOT / "store/llm_log.jsonl")
    parser.add_argument("--db", type=Path, default=Path(os.getenv("SOONY_DB", ROOT / "store/soony.db")))
    parser.add_argument("--eur-per-usd", type=argument_amount, default=os.getenv("SOONY_EUR_PER_USD", "1"))
    parser.add_argument("--run-budget-eur", type=argument_amount, default=os.getenv("SOONY_RUN_BUDGET_EUR"),
                        help="defaults to SOONY_AGENT_BUDGET_USD converted using the selected rate")
    parser.add_argument("--day-budget-eur", type=argument_amount, default=os.getenv("SOONY_DAY_BUDGET_EUR", "1"))
    args = parser.parse_args()
    if not args.eur_per_usd:
        parser.error("--eur-per-usd must be positive")
    run_budget = args.run_budget_eur
    if run_budget is None:
        run_budget_usd = number(os.getenv("SOONY_AGENT_BUDGET_USD", "0.10"))
        if run_budget_usd is None:
            parser.error("SOONY_AGENT_BUDGET_USD must be a finite non-negative amount")
        run_budget = run_budget_usd * args.eur_per_usd
    days, runs, warnings = defaultdict(Usage), defaultdict(Usage), []
    try:
        client_usage(args.log, days, runs, warnings)
    except OSError:
        warnings.append("Shared client log could not be read.")
    try:
        trace_usage(args.db, days, runs, warnings)
    except (sqlite3.Error, OSError):
        warnings.append("Agent database could not be read.")
    print(f"Recorded LLM usage (Hamburg days, EUR {args.eur_per_usd} per USD)")
    for group, budget, heading in ((days, args.day_budget_eur, "Day"), (runs, run_budget, "Run")):
        print(f"  {heading}")
        if not group:
            print("    No recorded usage.")
        for label, usage in sorted(group.items()):
            print_usage(label, usage, args.eur_per_usd, budget)
    for warning in warnings:
        print(f"  Warning: {warning}")


if __name__ == "__main__":
    main()
