"""Supplier facts from the case files, for the best-supplier model.

Sources (cite these when explaining a score):
  suppliers/<id>_*/profile.csv     payment_terms, incoterm, country, qualification_status
  suppliers/<id>_*/components.csv  moq, unit_price (agreed list price), lead_time_days, share, primary
  soony/master/components.csv      critical flag (for single-supplier dependence)
"""
from __future__ import annotations

import csv
import os
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EU = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU",
      "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}
# Who carries transport and import risk under each Incoterm (1 = supplier carries it to our door).
INCOTERM_RISK = {"DDP": 1.0, "DAP": 0.85, "DPU": 0.85, "CIP": 0.6, "CIF": 0.55, "CPT": 0.55, "CFR": 0.5,
                 "FCA": 0.4, "FAS": 0.35, "FOB": 0.35, "EXW": 0.2}


def data_root():
    if env := os.getenv("SOONY_DATA"):
        return Path(env)
    return ROOT / "data" if (ROOT / "data" / "suppliers").is_dir() else ROOT / "case-data"


def _rows(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=8)
def _load(root: str):
    root = Path(root)
    suppliers, primaries, critical = {}, {}, set()
    master = root / "soony" / "master" / "components.csv"
    if master.is_file():
        critical = {r["component_id"] for r in _rows(master) if (r.get("critical") or "").upper() == "Y"}
    for profile in (root / "suppliers").glob("*/profile.csv"):
        p = _rows(profile)[0]
        sid = p["supplier_id"].strip()
        comps = {}
        comp_file = profile.parent / "components.csv"
        if comp_file.is_file():
            for r in _rows(comp_file):
                comps[r["component_id"]] = r
                if (r.get("primary") or "").upper() == "Y" and r["component_id"] in critical:
                    primaries.setdefault(sid, set()).add(r["component_id"])
        suppliers[sid] = {"profile": p, "components": comps,
                          "source": str(profile.relative_to(root))}
    return suppliers, primaries, critical


def facts(supplier_id, material, root=None):
    """Plain dict of the facts the model uses; missing data stays None."""
    suppliers, primaries, critical = _load(str(root or data_root()))
    entry = suppliers.get(supplier_id)
    if not entry:
        return {}
    p, comp = entry["profile"], entry["components"].get(material, {})
    terms = re.search(r"(\d+)", p.get("payment_terms") or "")
    incoterm = (p.get("incoterm") or "").split(" ")[0].upper() or None

    def num(key, cast=float):
        try:
            return cast(comp[key]) if comp.get(key) not in (None, "") else None
        except ValueError:
            return None

    own_critical = primaries.get(supplier_id, set())
    return {
        "payment_days": int(terms[1]) if terms else None,
        "payment_terms": p.get("payment_terms"),
        "incoterm": incoterm,
        "incoterm_full": p.get("incoterm"),
        "country": p.get("country"),
        "customs": (p.get("country") or "").upper() not in EU if p.get("country") else None,
        "qualification": (p.get("qualification_status") or "").strip().lower() or None,
        "moq": num("moq", int),
        "list_price": num("unit_price"),
        "list_currency": comp.get("currency") or None,
        "lead_days": num("lead_time_days", int),
        "share": num("share"),
        "critical_primary_count": len(own_critical),
        "critical_total": len(critical),
        "source": entry["source"],
    }
