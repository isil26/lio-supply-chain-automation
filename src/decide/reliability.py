"""Deadline forecasts from cited PO-line lateness and observed outcomes."""

from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from typing import NamedTuple

from src.ingest.store import DB
from src.truth import LOCAL
from src.truth.sensitivity import calibrate_supplier_lags


MIN_OBSERVATIONS = 5
MIN_SLIP_HOURS = 24  # PO delivery data has day-level resolution.


class DiscountedETA(NamedTuple):
    eta_p50: datetime
    eta_p90: datetime
    p_on_time: float | None


def _datetime(value):
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=LOCAL)


class SupplierReliability:
    """Fit empirical counts and update the share arriving by the promise.

    Binary outcomes reweight the historical positive-slip distribution. With
    no positive slips, use the global tail or a one-day slip. With no PO
    history, start from one hit and one miss.
    """

    def __init__(self, con, *, before=None):
        self._profiles = calibrate_supplier_lags(con, before=before, min_samples=1)
        self._global_hours = sorted(
            hours for profile in self._profiles.values() for hours in profile["hours"]
        )
        self._global_evidence = [
            source for profile in self._profiles.values() for source in profile["evidence"]
        ]
        self._global_tail = [hour for hour in self._global_hours if hour > 0]
        self._outcomes = Counter()

    @classmethod
    def from_store(cls, path=DB, *, before=None):
        uri = Path(path).resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as con:
            con.row_factory = sqlite3.Row
            return cls(con, before=before)

    def update(self, supplier, observed_on_time: bool):
        """Record one actual outcome against its promise in this model."""
        if not isinstance(observed_on_time, bool):
            raise TypeError("observed_on_time must be a bool")
        self._outcomes[supplier, observed_on_time] += 1

    def _prior(self, supplier):
        local = self._profiles.get(supplier, {})
        count = local.get("sample_count", 0)
        if count < MIN_OBSERVATIONS:
            return count, self._global_hours, self._global_evidence
        return count, local["hours"], local["evidence"]

    def _distribution(self, supplier, hours):
        late_hours = [hour for hour in hours if hour > 0]
        hits = len(hours) - len(late_hours) + self._outcomes[supplier, True]
        misses = len(late_hours) + self._outcomes[supplier, False]
        if not hours:
            hits += 1
            misses += 1
        tail = late_hours or self._global_tail or [MIN_SLIP_HOURS]
        total = hits + misses
        return hits / total, misses / total, tail

    def profile(self, supplier):
        """Return empirical metadata, current lateness rate and source rows."""
        count, hours, evidence = self._prior(supplier)
        _, late_share, tail = self._distribution(supplier, hours)
        low_data = count < MIN_OBSERVATIONS
        if late_share and tail is self._global_tail:
            evidence = self._global_evidence
        return {
            "supplier": supplier,
            "low_data": low_data,
            "method": "supplier" if not low_data else ("global" if hours else "cold_start"),
            "sample_count": count,
            "prior_sample_count": len(hours),
            "observed_hits": self._outcomes[supplier, True],
            "observed_misses": self._outcomes[supplier, False],
            "late_share": late_share,
            "mean_slip_days": late_share * sum(tail) / len(tail) / 24,
            "max_slip_days": tail[-1] / 24 if late_share else 0,
            "evidence": list(evidence),
        }

    def p_on_time(self, supplier, promised_eta, deadline):
        _, hours, _ = self._prior(supplier)
        hits, misses, tail = self._distribution(supplier, hours)
        cutoff = _datetime(deadline).astimezone(timezone.utc)
        promised = _datetime(promised_eta).astimezone(timezone.utc)
        slack_hours = (cutoff - promised).total_seconds() / 3600
        if slack_hours < 0:
            return 0.0
        within = sum(hour <= slack_hours for hour in tail)
        return hits + misses * (within / len(tail))

    def discounted_eta(self, supplier, promised_eta, *, deadline=None):
        _, hours, _ = self._prior(supplier)
        hits, misses, tail = self._distribution(supplier, hours)
        promised = _datetime(promised_eta)

        def eta(quantile):
            if quantile <= hits:
                return promised
            for rank, hour in enumerate(tail, 1):
                if quantile <= hits + misses * (rank / len(tail)):
                    arrival = promised.astimezone(timezone.utc) + timedelta(hours=hour)
                    return arrival.astimezone(promised.tzinfo)
            raise AssertionError("Quantile exceeds the distribution")

        probability = self.p_on_time(supplier, promised, deadline) if deadline is not None else None
        return DiscountedETA(eta(0.5), eta(0.9), probability)


def discounted_eta(supplier, promised_eta, *, model=None, deadline=None):
    return (model or SupplierReliability.from_store()).discounted_eta(supplier, promised_eta, deadline=deadline)


def p_on_time(supplier, promised_eta, deadline, *, model=None):
    return (model or SupplierReliability.from_store()).p_on_time(supplier, promised_eta, deadline)
