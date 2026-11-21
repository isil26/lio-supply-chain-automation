"""Approval engine with delegated authority (T93): PP-07 as code.

evaluate(action, now, delegations) -> {mode: AUTO | ONE_CLICK | ESCALATE | NEVER, approver, reason,
policy_refs, delegation_id, sla_minutes, escalation_chain, blocked_by, ...}

Principles (IMPORTANT.md section 3): the system never pretends to be a person. AUTO means "approved under a
recorded, confirmed-in-writing delegation", logged as decided_by='delegation' with the delegator's name and the
record id. Unconfirmed delegations only ever give ONE_CLICK. Pure functions plus a small sqlite audit log.

Sources: PP-07 v3.2 (approval_policy_PP-07.pdf), org_chart_v2.pdf (2026-11-21), CPO memo 21 Nov, docs/AUTHORIZATIONS.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
DELEGATIONS_PATH = ROOT / "docs" / "delegations.json"
DB_PATH = ROOT / "store" / "approvals.db"
CET = timezone(timedelta(hours=1))

AUTO, ONE_CLICK, ESCALATE, NEVER = "AUTO", "ONE_CLICK", "ESCALATE", "NEVER"
KINDS = ("supplier_info_request", "hold_and_quote", "purchase_order", "air_freight", "dock_slot",
         "quality_exception", "supplier_release", "internal_message")
INFO_KINDS = ("supplier_info_request", "internal_message")
DEFAULT_SLA_MIN = 30
AIR_FREIGHT_OVER_LIMIT_SLA_MIN = 15  # CPO memo: "the same hour"
AIR_FREIGHT_MONTHLY_CATEGORY_LIMIT = 200_000
# Things that must never leave the building (harness.policy_check uses the same list).
FORBIDDEN_PHRASES = ("slack", "walkaway", "walk-away", "maximum premium", "max premium", "max_premium",
                     "cost per missing copy", "break-even", "breakeven")

# --- Policy data (PP-07 section 2): role -> (rank, upper limit EUR exclusive) ------------------------------
ROLE_RANK = {"buyer": 1, "category_lead": 2, "head_of_procurement": 3, "cpo": 4, "cpo_cfo": 5}
LIMITS = {"buyer": 50_000, "category_lead": 500_000, "head_of_procurement": 2_000_000,
          "cpo": 5_000_000, "cpo_cfo": None}
ROLE_LABEL = {"buyer": "Buyer", "category_lead": "Category Lead", "head_of_procurement": "Head of Procurement",
              "cpo": "Chief Procurement Officer", "cpo_cfo": "CPO and CFO jointly"}

# --- Approver directory (org_chart_v2.pdf, 2026-11-21) -----------------------------------------------------
PEOPLE = {
    "Jonas Lindqvist": {"role": "Chief Procurement Officer"},
    "Henrik Dahl": {"role": "Chief Financial Officer"},
    "Dr. Maren Vogt": {"role": "Head of Procurement"},
    "Tobias Brandt": {"role": "Category Lead Game Media"},
    "Sofia Marchetti": {"role": "Category Lead Print & Packaging"},
    "Arjun Krishnan": {"role": "Category Lead Collector's Items", "from": "2026-11-23"},
    "Daniel Okafor": {"role": "Supplier Quality Lead"},
    "Raj Patel": {"role": "Logistics Planner; deputy site lead DC-HAM"},
    "Katrin Jansen": {"role": "Site Lead DC Hamburg", "deputy": "Raj Patel"},
    "Clara Weiss": {"role": "Quality & Compliance Manager"},
    "Felix Brunner": {"role": "Senior Buyer (Game Cards)"},
    "Paul Winter": {"role": "Buyer (Print & Packaging)"},
    "Mei Lin": {"role": "Buyer (Collector's Items)"},
}
CATEGORIES = {
    "Game Media": {"buyer": "Felix Brunner", "category_lead": "Tobias Brandt"},
    "Print & Packaging": {"buyer": "Paul Winter", "category_lead": "Sofia Marchetti"},
    "Collector's Items": {"buyer": "Mei Lin", "category_lead": "Arjun Krishnan",
                          "category_lead_vacant_until": "2026-11-23T00:00:00+01:00"},
}
HEAD, CPO, CFO = "Dr. Maren Vogt", "Jonas Lindqvist", "Henrik Dahl"
QUALITY_LEAD, QUALITY_MANAGER = "Daniel Okafor", "Clara Weiss"
SITE = {"DC-HAM": {"lead": "Katrin Jansen", "deputy": "Raj Patel"}}
PUNE_CONDITIONAL_RELEASE_EXPIRED = "2026-10-30"


# ------------------------------------------------------------------------------------------------ helpers
def to_dt(value: Any) -> datetime:
    if value is None or value == "":
        return datetime.now(CET)
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=CET)  # naive timestamps are Hamburg time


def _num(v: Any) -> float | None:
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _person(name: str, role: str | None = None) -> dict:
    return {"name": name, "role": role or PEOPLE.get(name, {}).get("role", "")}


def _text(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


# ------------------------------------------------------------------------------------------ delegations
def load_delegations(path: str | Path | None = None) -> list[dict]:
    p = Path(path or DELEGATIONS_PATH)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return list(data["delegations"] if isinstance(data, dict) else data)


def _save(delegations: list[dict], path: str | Path | None) -> None:
    p = Path(path or DELEGATIONS_PATH)
    p.write_text(json.dumps({"delegations": delegations}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def add_delegation(record: Mapping, path: str | Path | None = None) -> dict:
    """Record 'X delegates <kinds> up to EUR Y until T' (the answer to the Felix/approver question)."""
    rec = dict(record)
    for key in ("delegator", "action_kinds", "max_value_eur", "valid_until", "source"):
        if rec.get(key) in (None, "", []):
            raise ValueError(f"delegation needs {key}")
    bad = [k for k in rec["action_kinds"] if k not in KINDS]
    if bad:
        raise ValueError(f"unknown action kinds: {bad}")
    delegations = load_delegations(path)
    rec.setdefault("id", f"DEL-{len(delegations) + 1:03d}")
    if any(d["id"] == rec["id"] for d in delegations):
        raise ValueError(f"delegation {rec['id']} exists")
    rec.setdefault("delegate", "system")
    rec.setdefault("valid_from", datetime.now(CET).isoformat(timespec="seconds"))
    rec.setdefault("conditions", {"information_only": True, "reversible": True, "hold_and_quote": True})
    rec.setdefault("confirmed_in_writing", False)
    delegations.append(rec)
    _save(delegations, path)
    return rec


def _update(delegation_id: str, path, **fields) -> dict:
    delegations = load_delegations(path)
    for d in delegations:
        if d["id"] == delegation_id:
            d.update(fields)
            _save(delegations, path)
            return d
    raise KeyError(delegation_id)


def revoke_delegation(delegation_id: str, by: str, when: Any = None, path: str | Path | None = None) -> dict:
    return _update(delegation_id, path, revoked_at=to_dt(when).isoformat(timespec="seconds"), revoked_by=by)


def confirm_delegation(delegation_id: str, evidence_ref: str, when: Any = None, path: str | Path | None = None) -> dict:
    """Mark a delegation confirmed in writing by the delegator (message / mail / signed note reference)."""
    return _update(delegation_id, path, confirmed_in_writing=True, confirmed_evidence=evidence_ref,
                   confirmed_at=to_dt(when).isoformat(timespec="seconds"))


def _delegation_active(d: Mapping, now: datetime) -> bool:
    if d.get("revoked_at") or d.get("delegate", "system") != "system":
        return False
    return to_dt(d["valid_from"]) <= now <= to_dt(d["valid_until"])


# ------------------------------------------------------------------------------------------------ routing
def _role_holder(role: str, category: str | None, now: datetime) -> tuple[dict | None, list[str], list[str]]:
    """Person for a ladder role. Returns (person|None, policy_refs, notes). None means no holder."""
    cat = CATEGORIES.get(category or "")
    if role == "buyer":
        return (_person(cat["buyer"]) if cat else None), ["PP-07 §2 (Buyer)"], []
    if role == "category_lead":
        if not cat:
            return None, ["PP-07 §2 (Category Lead)"], []
        until = cat.get("category_lead_vacant_until")
        if until and now < to_dt(until):
            lead = cat["category_lead"]
            return (_person(HEAD), ["PP-07 §6 (Exceptions: Head of Procurement)", "PP-07 §2 (Category Lead)"],
                    [f"Category Lead {category} seat vacant until {lead} starts {until[:10]}: routed to Head of "
                     f"Procurement under PP-07 §6"])
        return _person(cat["category_lead"]), ["PP-07 §2 (Category Lead)"], []
    if role == "head_of_procurement":
        return _person(HEAD), ["PP-07 §2 (Head of Procurement)"], []
    if role == "cpo":
        return _person(CPO), ["PP-07 §2 (CPO)"], []
    if role == "cpo_cfo":
        return _person(f"{CPO} + {CFO}", "CPO and CFO jointly"), ["PP-07 §2 (CPO and CFO jointly)"], []
    return None, [], []


def role_for_value(value: float) -> str:
    for role in ("buyer", "category_lead", "head_of_procurement", "cpo"):
        if value < LIMITS[role]:
            return role
    return "cpo_cfo"


def _ladder_chain(role: str, category: str | None, now: datetime) -> list[dict]:
    """Escalation chain above `role`, deduplicated by name (vacancy can map two roles to one person)."""
    out: list[dict] = []
    ranks = list(ROLE_RANK)
    for r in ranks[ranks.index(role) + 1:]:
        person, _, _ = _role_holder(r, category, now)
        if person and person["name"] not in [p["name"] for p in out]:
            out.append(person)
    return out


def _route(action: Mapping, now: datetime) -> dict:
    kind, cat = action["kind"], action.get("category")
    value = _num(action.get("value_eur")) or 0.0
    r: dict[str, Any] = {"required_role": None, "co_signers": [], "notes": [], "sla": DEFAULT_SLA_MIN,
                         "vacancy": False, "over_limit": False, "required_signers": []}
    if kind == "dock_slot":
        site = SITE.get(action.get("site") or "DC-HAM", SITE["DC-HAM"])
        r.update(approver=_person(site["lead"]), chain=[_person(site["deputy"])], refs=["PP-07 §3 (dock slot released by site lead)"])
        return r
    if kind == "quality_exception":
        first = _person(QUALITY_MANAGER)
        lead, refs, notes = _role_holder("category_lead", cat, now)
        r["vacancy"] = bool(notes)
        exc = lead if lead else _person(HEAD)
        signers = [first, _person(QUALITY_LEAD), exc]
        r.update(approver=first, co_signers=signers[1:], required_signers=[s["name"] for s in signers],
                 chain=[_person(HEAD), _person(CPO)],
                 refs=["CPO memo 21 Nov (Quality & Compliance has the last word)", "PP-07 §5", "PP-07 §6"] + refs, notes=notes)
        return r
    if kind == "supplier_release":
        lead, refs, notes = _role_holder("category_lead", cat, now)
        r["vacancy"] = bool(notes)
        approver = lead or _person(HEAD)
        signers = [_person(QUALITY_LEAD), approver]
        r.update(approver=_person(QUALITY_LEAD) if not notes else approver, co_signers=[approver] if not notes else [_person(QUALITY_LEAD)],
                 required_signers=[s["name"] for s in signers],
                 chain=[_person(HEAD)] if approver["name"] != HEAD else [_person(CPO)],
                 refs=["PP-07 §5 (new suppliers: Supplier Quality Lead + Category Lead)"] + refs, notes=notes)
        if notes:
            r["notes"].append(f"{QUALITY_LEAD} co-signs the §6 exception")
        return r
    if kind == "air_freight":
        total = value + (_num(action.get("month_to_date_eur")) or 0.0)
        if total > AIR_FREIGHT_MONTHLY_CATEGORY_LIMIT:
            r.update(approver=_person(CPO), chain=[_person(CFO, "Chief Financial Officer (informed; no PP-07 air-freight authority)")],
                     refs=["PP-07 §4 (above EUR 200,000 per month and category: CPO before booking)", "CPO memo 21 Nov (same hour)"],
                     over_limit=True, sla=AIR_FREIGHT_OVER_LIMIT_SLA_MIN)
            r["notes"].append(f"month-and-category total EUR {total:,.0f} exceeds EUR 200,000: CPO, same hour, "
                              f"with cost against copies gained")
            return r
        person, refs, notes = _role_holder("category_lead", cat, now)
        r["vacancy"] = bool(notes)
        r.update(approver=person or _person(HEAD), required_role="category_lead",
                 chain=_ladder_chain("category_lead", cat, now),
                 refs=["PP-07 §4 (unplanned air freight up to EUR 200,000 per month and category: Category Lead)"] + refs, notes=notes)
        return r
    # value ladder kinds: supplier_info_request, hold_and_quote, purchase_order, internal_message
    role = role_for_value(value)
    proposed = action.get("approver_role")
    if proposed in ROLE_RANK and ROLE_RANK[proposed] < ROLE_RANK[role]:
        r["over_limit"] = True
        r["notes"].append(f"proposed approver role {ROLE_LABEL[proposed]} exceeds its PP-07 limit "
                          f"(EUR {LIMITS[proposed]:,}); {ROLE_LABEL[role]} required")
    person, refs, notes = _role_holder(role, cat, now)
    if person is None:  # category unknown: only a role above the category level can decide
        role = "head_of_procurement" if ROLE_RANK[role] < ROLE_RANK["head_of_procurement"] else role
        person, refs, notes = _role_holder(role, cat, now)
        r["notes"].append("category unknown: routed to Head of Procurement")
    r["vacancy"] = bool(notes)
    r.update(approver=person, required_role=role, chain=_ladder_chain(role, cat, now),
             refs=refs, notes=r["notes"] + notes)
    if role == "cpo_cfo":
        r["required_signers"] = [CPO, CFO]
    return r


# -------------------------------------------------------------------------------------------- delegation
def _holder_rank(name: str, category: str | None, now: datetime) -> int:
    best = 0
    for role in ("buyer", "category_lead", "head_of_procurement", "cpo"):
        person = _role_holder(role, category, now)[0]
        if person and person["name"] == name:
            best = max(best, ROLE_RANK[role])
    return best


def _delegation_for(action: Mapping, route: Mapping, delegations: Iterable[Mapping], now: datetime) -> tuple[dict | None, list[str]]:
    """Best delegation that covers the action (confirmed preferred) and the reasons others were rejected."""
    kind = action["kind"]
    value = _num(action.get("value_eur")) or 0.0
    binding = bool(action.get("binding"))
    info = kind in INFO_KINDS and not binding
    hold = kind == "hold_and_quote" and not binding
    reversible = bool(action.get("reversible")) and not binding
    why: list[str] = []
    covering = []
    for d in delegations:
        did = d.get("id")
        if not _delegation_active(d, now):
            why.append(f"{did}: not active at {now.isoformat(timespec='minutes')} (expired, revoked or not yet valid)")
            continue
        if kind not in d.get("action_kinds", []):
            why.append(f"{did}: does not cover {kind}")
            continue
        if value >= float(d["max_value_eur"]):
            why.append(f"{did}: EUR {value:,.0f} is not under the delegation limit EUR {float(d['max_value_eur']):,.0f}")
            continue
        cond = d.get("conditions", {})
        if not ((info and cond.get("information_only")) or (hold and cond.get("hold_and_quote"))
                or (reversible and cond.get("reversible"))):
            why.append(f"{did}: action is binding or not information-only/reversible; delegation cannot auto-approve it")
            continue
        # The delegator must hold at least the authority the action needs (delegation cannot create authority).
        who = d["delegator"]
        need = route.get("required_role")
        ok = False
        if need:
            rank = _holder_rank(who, action.get("category"), now)
            ok = rank >= ROLE_RANK[need] or who == route["approver"]["name"]
        else:
            ok = who == route["approver"]["name"]
        if not ok:
            why.append(f"{did}: delegator {who} does not hold the authority this action needs")
            continue
        covering.append(d)
    covering.sort(key=lambda d: not d.get("confirmed_in_writing"))
    return (dict(covering[0]) if covering else None), why


# ----------------------------------------------------------------------------------------------- evaluate
def evaluate(action: Mapping, now: Any = None, delegations: Iterable[Mapping] | None = None, *,
             unavailable: Iterable[str] = (), kill_switch: bool | None = None) -> dict:
    """Decide how an action may be approved. Never raises on bad input: it returns NEVER with blocked_by."""
    now = to_dt(now)
    action = dict(action or {})
    delegations = list(load_delegations() if delegations is None else delegations)
    unavailable = set(unavailable) | set(action.get("unavailable") or [])
    if kill_switch is None:
        kill_switch = os.getenv("APPROVALS_KILL_SWITCH") == "1"
    kind = str(action.get("kind") or "")
    out = {"action_id": action.get("id"), "kind": kind, "mode": NEVER, "approver": None, "reason": "",
           "policy_refs": [], "delegation_id": None, "sla_minutes": DEFAULT_SLA_MIN, "escalation_chain": [],
           "blocked_by": [], "co_signers": [], "required_signers": [], "notes": [], "evaluated_at": now.isoformat(timespec="seconds")}
    if kind not in KINDS:
        out["blocked_by"].append(f"unknown action kind '{kind}'")
        out["reason"] = "Blocked: " + out["blocked_by"][0]
        return out
    route = _route(action, now)
    chain = list(route["chain"])
    approver = route["approver"]
    out.update(approver=approver, policy_refs=route["refs"], co_signers=route["co_signers"],
               required_signers=route["required_signers"], sla_minutes=route["sla"], notes=list(route["notes"]))

    # --- NEVER guards -----------------------------------------------------------------------------------
    blocked = out["blocked_by"]
    body = _text({k: v for k, v in action.items() if k not in ("evidence", "unavailable")}).casefold()
    for phrase in FORBIDDEN_PHRASES:
        if phrase in body:
            blocked.append(f"would reveal confidential negotiating position ('{phrase}')")
    if not [e for e in (action.get("evidence") or []) if e]:
        blocked.append("missing evidence: every action needs cited, grounded evidence")
    if kind in ("purchase_order", "air_freight", "hold_and_quote") and _num(action.get("value_eur")) is None:
        blocked.append("value_eur missing: number not grounded")
    if (_num(action.get("value_eur")) or 0) < 0:
        blocked.append("negative value")
    if route["required_signers"] == [CPO, CFO] and (CPO in unavailable or CFO in unavailable):
        blocked.append("value at or above EUR 5,000,000 needs CPO and CFO jointly; no higher approver exists")
    if kind == "quality_exception":
        blocked.append("quality release: Clara Weiss (Quality & Compliance) has the last word; human decision only")
    if blocked:
        out["mode"] = NEVER
        out["escalation_chain"] = chain
        out["reason"] = "Never automatic: " + "; ".join(blocked)
        if kind == "quality_exception":
            names = ", ".join(f"{s['name']} ({s['role']})" for s in [approver] + route["co_signers"])
            out["reason"] += f". Signers: {names}."
            out["reason"] += " " + "; ".join(route["notes"]) if route["notes"] else ""
        return out

    # --- timing / availability -> ESCALATE ----------------------------------------------------------------
    sla = route["sla"]
    out["escalation_chain"] = chain
    steps = 0
    requested = action.get("requested_at")
    if requested:
        elapsed = (now - to_dt(requested)).total_seconds() / 60.0
        if elapsed > sla:
            steps = int(elapsed // sla)
            out["notes"].append(f"SLA of {sla} min expired ({elapsed:.0f} min since request)")
    n = 0
    while approver["name"] in unavailable and n < len(chain):
        out["notes"].append(f"{approver['name']} unavailable")
        approver, chain, n = chain[0], chain[1:], n + 1
    escalate_reason = None
    if n:
        escalate_reason = f"{route['approver']['name']} unavailable: routed to {approver['name']} ({approver['role']})"
    if steps and chain:
        k = min(steps, len(chain))
        prev = approver
        approver, chain = chain[k - 1], chain[k:]
        escalate_reason = (escalate_reason + "; " if escalate_reason else "") + \
            f"SLA expired: escalated from {prev['name']} to {approver['name']} ({approver['role']})"
    elif steps:
        escalate_reason = (escalate_reason + "; " if escalate_reason else "") + \
            f"SLA expired and no higher approver on file: reminder to {approver['name']}, call by phone"
    out["approver"], out["escalation_chain"] = approver, chain
    if route["over_limit"]:
        escalate_reason = (escalate_reason + "; " if escalate_reason else "") + "; ".join(
            x for x in route["notes"] if "exceeds" in x)
    if route["vacancy"] and not escalate_reason:
        escalate_reason = "; ".join(route["notes"])
    if escalate_reason:
        out["mode"] = ESCALATE
        out["reason"] = escalate_reason
        if kind == "supplier_release":
            out["blocked_by"].append(f"conditional release expired {PUNE_CONDITIONAL_RELEASE_EXPIRED} (PP-07 §5): "
                                     f"POs after expiry are held 'awaiting approval'; extension once, max 90 days, in writing"
                                     ) if action.get("conditional_release_expired") or action.get("supplier") in ("Pune", "SUP-Pune") else None
            out["reason"] += (f". Co-signers: {', '.join(s['name'] for s in out['co_signers'])}" if out["co_signers"] else "")
        return out

    # --- delegation -> AUTO or ONE_CLICK --------------------------------------------------------------------
    deleg, why = _delegation_for(action, route, delegations, now)
    out["notes"].extend(why)
    if deleg and not kill_switch:
        out["delegation_id"] = deleg["id"]
        if deleg.get("confirmed_in_writing"):
            out["mode"] = AUTO
            out["reason"] = (f"approved by delegation of {deleg['delegator']}, record {deleg['id']} "
                             f"(under EUR {float(deleg['max_value_eur']):,.0f}, valid until {deleg['valid_until'][:16]}); "
                             f"{'information only' if kind in INFO_KINDS else 'reversible'}; "
                             f"{approver['name']} is notified")
            out["approver"] = _person(deleg["delegator"])
            out["notes"].append(f"logged as decided_by='delegation', never as {deleg['delegator']} personally")
        else:
            out["mode"] = ONE_CLICK
            out["reason"] = (f"delegation unconfirmed: {deleg['delegator']}'s statement ({deleg['id']}) is not confirmed "
                             f"in writing, so {approver['name']} gives one click")
            out["notes"].append("delegation unconfirmed")
        return out
    if deleg and kill_switch:
        out["notes"].append("kill switch on: delegation ignored")
    out["mode"] = ONE_CLICK
    out["reason"] = f"{approver['name']} ({approver['role']}) approves with one click; " + \
        (f"binding commitment" if action.get("binding") else "no covering delegation")
    return out


# ------------------------------------------------------------------------------------------- audit log
SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, action_id TEXT NOT NULL, mode TEXT NOT NULL,
  approver TEXT, delegation_id TEXT, decided_by TEXT NOT NULL, reason TEXT, evidence_ref TEXT);
CREATE TABLE IF NOT EXISTS approvals_pending (
  action_id TEXT PRIMARY KEY, requested_at TEXT NOT NULL, action_json TEXT NOT NULL, mode TEXT NOT NULL,
  approver TEXT, sla_minutes INTEGER NOT NULL, due_at TEXT NOT NULL, escalations INTEGER NOT NULL DEFAULT 0,
  required_json TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'pending');
"""


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    p = Path(path or DB_PATH)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _name(a: Any) -> str | None:
    return a.get("name") if isinstance(a, Mapping) else a


def log_decision(con: sqlite3.Connection, action_id: str, mode: str, approver: Any, delegation_id: str | None,
                 decided_by: str, reason: str, evidence_ref: str | None = None, ts: Any = None) -> int:
    if decided_by not in ("delegation", "human", "system-escalated"):
        raise ValueError("decided_by must be delegation, human or system-escalated")
    if mode not in (AUTO, ONE_CLICK, ESCALATE, NEVER, "APPROVED", "REJECTED"):
        raise ValueError(f"bad mode {mode}")
    if decided_by == "delegation" and not delegation_id:
        raise ValueError("a delegation decision needs the delegation record id")
    with con:
        cur = con.execute("INSERT INTO approvals_log(ts, action_id, mode, approver, delegation_id, decided_by, reason, evidence_ref)"
                          " VALUES (?,?,?,?,?,?,?,?)",
                          (to_dt(ts).isoformat(timespec="seconds"), str(action_id), mode, _name(approver),
                           delegation_id, decided_by, reason, evidence_ref))
    return cur.lastrowid


def log_rows(con: sqlite3.Connection, action_id: str | None = None) -> list[dict]:
    q, a = ("SELECT * FROM approvals_log WHERE action_id=? ORDER BY id", (action_id,)) if action_id else \
           ("SELECT * FROM approvals_log ORDER BY id", ())
    return [dict(r) for r in con.execute(q, a)]


def submit(con: sqlite3.Connection, action: Mapping, now: Any = None, delegations: Iterable[Mapping] | None = None,
           **kw) -> dict:
    """evaluate + log (+ register as pending unless AUTO/NEVER-blocked). The one call the action queue makes."""
    now = to_dt(now)
    action = dict(action)
    if not action.get("id"):
        raise ValueError("action needs an id")
    ev = evaluate(action, now, delegations, **kw)
    ref = _text(action.get("evidence"))[:500] if action.get("evidence") else None
    if ev["mode"] == AUTO:
        log_decision(con, action["id"], AUTO, ev["approver"], ev["delegation_id"], "delegation", ev["reason"], ref, now)
        return ev
    log_decision(con, action["id"], ev["mode"], ev["approver"], ev["delegation_id"],
                 "system-escalated" if ev["mode"] == ESCALATE else "human", "awaiting decision: " + ev["reason"], ref, now)
    action.pop("requested_at", None)
    with con:
        con.execute("INSERT OR REPLACE INTO approvals_pending(action_id, requested_at, action_json, mode, approver, sla_minutes,"
                    " due_at, required_json) VALUES (?,?,?,?,?,?,?,?)",
                    (str(action["id"]), now.isoformat(timespec="seconds"), _text(action), ev["mode"], _name(ev["approver"]),
                     ev["sla_minutes"], (now + timedelta(minutes=ev["sla_minutes"])).isoformat(timespec="seconds"),
                     json.dumps(ev["required_signers"])))
    return ev


def record_human_decision(con: sqlite3.Connection, action_id: str, approver: str, decision: str, note: str = "",
                          now: Any = None, evidence_ref: str | None = None) -> dict:
    """A named person clicks approve/reject. Anyone not on the route (approver, co-signer, deputy, chain) is refused."""
    decision = decision.casefold()
    if decision not in ("approve", "reject"):
        raise ValueError("decision must be approve or reject")
    row = con.execute("SELECT * FROM approvals_pending WHERE action_id=?", (str(action_id),)).fetchone()
    if not row:
        raise KeyError(f"no pending approval for {action_id}")
    action = json.loads(row["action_json"])
    ev = evaluate({**action, "requested_at": row["requested_at"]}, row["requested_at"], [])
    allowed = {_name(ev["approver"]), *(s["name"] for s in ev["co_signers"]), *row_names(ev["escalation_chain"]),
               *json.loads(row["required_json"]), row["approver"]}
    if approver not in allowed:
        raise PermissionError(f"{approver} is not an approver for {action_id}: {sorted(n for n in allowed if n)}")
    log_decision(con, action_id, "APPROVED" if decision == "approve" else "REJECTED", approver, None, "human",
                 note or decision, evidence_ref, now)
    required = json.loads(row["required_json"])
    done = {r["approver"] for r in con.execute("SELECT approver FROM approvals_log WHERE action_id=? AND mode='APPROVED'", (str(action_id),))}
    status = "rejected" if decision == "reject" else ("approved" if not required or set(required) <= done else "pending")
    with con:
        con.execute("UPDATE approvals_pending SET status=? WHERE action_id=?", (status, str(action_id)))
    return {"action_id": action_id, "status": status, "waiting_for": [] if status != "pending" else sorted(set(required) - done)}


def row_names(people: Iterable[Mapping]) -> list[str]:
    return [p["name"] for p in people]


def escalate_due(con: sqlite3.Connection, now: Any = None, delegations: Iterable[Mapping] | None = None,
                 log: bool = True) -> list[dict]:
    """Pending actions whose SLA timer expired, with their next approver. Logs one system-escalated row each time."""
    now = to_dt(now)
    out = []
    for row in con.execute("SELECT * FROM approvals_pending WHERE status='pending' ORDER BY requested_at").fetchall():
        action = json.loads(row["action_json"])
        due = to_dt(row["due_at"])
        if now <= due:
            continue
        ev = evaluate({**action, "requested_at": row["requested_at"]}, now, delegations)
        steps = int(((now - to_dt(row["requested_at"])).total_seconds() / 60) // row["sla_minutes"])
        if steps <= row["escalations"]:
            continue
        if log:
            log_decision(con, action["id"], ESCALATE, ev["approver"], None, "system-escalated", ev["reason"], None, now)
            with con:
                con.execute("UPDATE approvals_pending SET escalations=? WHERE action_id=?", (steps, row["action_id"]))
        out.append({"action_id": action["id"], "previous_approver": row["approver"], "next_approver": ev["approver"],
                    "minutes_overdue": round((now - due).total_seconds() / 60, 1), "evaluation": ev,
                    "reminder": reminder_text(action, ev, now)})
    return out


def reminder_text(action: Mapping, ev: Mapping, now: Any = None) -> str:
    """English reminder for the approver (first reminder, escalation or AUTO notification)."""
    who = _name(ev["approver"]) or "approver"
    what = action.get("title") or action.get("summary") or action.get("kind", "action").replace("_", " ")
    value = _num(action.get("value_eur"))
    stake = f" (EUR {value:,.0f})" if value else ""
    if ev["mode"] == AUTO:
        return (f"FYI {who}: the system sent '{what}'{stake} under your delegation {ev['delegation_id']}. "
                f"Reply REVOKE to withdraw the delegation. Nothing else is needed.")
    if ev["mode"] == ESCALATE:
        return (f"Hello {who}, '{what}'{stake} is waiting for a decision and needs you now: {ev['reason']}. "
                f"One click to approve or reject; the evidence is attached. SLA: {ev['sla_minutes']} minutes.")
    return (f"Hello {who}, please approve or reject '{what}'{stake}: {ev['reason']}. "
            f"It takes one click and the evidence is attached. If you cannot decide within {ev['sla_minutes']} minutes "
            f"it moves to the next approver.")


# ------------------------------------------------------------------------------------- harness integration
def policy_check(actions: Any, now: Any = None, delegations: Iterable[Mapping] | None = None) -> dict:
    """Drop-in companion for harness.policy_check: returns {'violations': [...]} in the harness format.
    A violation is any NEVER evaluation, or a claimed approval by someone who is not on the route / has no valid delegation."""
    if actions is None:
        actions = []
    if isinstance(actions, Mapping):
        actions = [actions]
    violations = []
    for action in actions:
        if not isinstance(action, Mapping) or action.get("kind") not in KINDS:
            continue
        ev = evaluate(action, now, delegations)
        if ev["mode"] == NEVER and not str(action.get("status", "")).casefold() in ("", "pending", "proposed", "blocked"):
            violations.append({"rule": "approvals", "detail": ev["reason"], "evidence": {"mode": NEVER, "blocked_by": ev["blocked_by"]}})
        elif ev["mode"] == NEVER and action.get("kind") != "quality_exception":
            violations.append({"rule": "approvals", "detail": ev["reason"], "evidence": {"mode": NEVER, "blocked_by": ev["blocked_by"]}})
        status = str(action.get("status") or "").casefold()
        by = str(action.get("approved_by") or action.get("approver") or "")
        if status in ("approved", "granted", "confirmed") and ev["mode"] != NEVER:
            ok = {_name(ev["approver"]), *row_names(ev["co_signers"]), *row_names(ev["escalation_chain"])} | set(ev["required_signers"])
            if by.startswith("delegation:"):
                if ev["mode"] != AUTO:
                    violations.append({"rule": "approvals", "detail": f"claimed delegation approval but mode is {ev['mode']}: {ev['reason']}",
                                       "evidence": {"approved_by": by}})
            elif by and by not in ok and not any(p in by for p in ok if p):
                violations.append({"rule": "approvals", "detail": f"{by} is not an authorised approver; expected {ev['approver']['name']}",
                                   "evidence": {"approved_by": by, "expected": ev["approver"]}})
    return {"violations": violations, "ok": not violations}


# ------------------------------------------------------------------------------------------------ demo
def demo_actions() -> list[tuple[str, dict, dict]]:
    return [
        ("1 Art-book hold-and-quote (Karton, Paul Winter)",
         {"id": "A-ART", "kind": "hold_and_quote", "value_eur": 12_390, "category": "Print & Packaging", "recipient": "Karton",
          "part": "art book", "binding": False, "reversible": True, "evidence": ["Karton mail 21 Nov 20:19 CET (free hold to expiry)"]}, {}),
        ("2 Dock slot + early customs (Katrin Jansen)",
         {"id": "A-DOCK", "kind": "dock_slot", "site": "DC-HAM", "value_eur": 0, "binding": True, "reversible": True,
          "evidence": ["Karton/Warta pickup window pending"]}, {}),
        ("2b Same dock slot, Katrin silent for 45 min",
         {"id": "A-DOCK2", "kind": "dock_slot", "site": "DC-HAM", "binding": True, "reversible": True,
          "requested_at": "2026-11-21T20:00:00+01:00", "evidence": ["Karton/Warta pickup window pending"]}, {"now": "2026-11-21T20:45:00+01:00"}),
        ("3 Information request to Hwaseong (seed: delegation unconfirmed)",
         {"id": "A-HWA", "kind": "supplier_info_request", "value_eur": 0, "category": "Game Media", "recipient": "Hwaseong",
          "binding": False, "reversible": True, "evidence": ["Hwaseong balance shipment status unknown"]}, {}),
        ("3b Same request IF Dr. Vogt had confirmed in writing (what-if)",
         {"id": "A-HWA2", "kind": "supplier_info_request", "value_eur": 0, "category": "Game Media", "recipient": "Hwaseong",
          "binding": False, "reversible": True, "evidence": ["Hwaseong balance shipment status unknown"]}, {"confirmed": True}),
        ("4 Statue lot concession (CMP-GAM-010, Collector's)",
         {"id": "A-STAT", "kind": "quality_exception", "category": "Collector's Items", "part": "CMP-GAM-010", "value_eur": 0,
          "binding": True, "evidence": ["Quality hold on failed 5,600 lot"]}, {}),
        ("5 Pune release (conditional release expired 2026-10-30)",
         {"id": "A-PUNE", "kind": "supplier_release", "category": "Collector's Items", "supplier": "Pune", "binding": True,
          "conditional_release_expired": True, "evidence": ["SUP-0018 profile: valid until 2026-10-30"]}, {}),
        ("6 Air freight EUR 250,000 (Game Media)",
         {"id": "A-AIR", "kind": "air_freight", "value_eur": 250_000, "category": "Game Media", "binding": True,
          "evidence": ["air lot 6,800 cards; cost against copies gained attached"]}, {}),
        ("7 PO EUR 2,500,000",
         {"id": "A-PO", "kind": "purchase_order", "value_eur": 2_500_000, "category": "Game Media", "binding": True,
          "evidence": ["firm quote on file (illustrative value)"]}, {}),
        ("8 Boise EXW confirmation in writing (illustrative EUR 900,000)",
         {"id": "A-BOISE", "kind": "purchase_order", "value_eur": 900_000, "category": "Game Media", "recipient": "Boise (SUP-0011)",
          "binding": True, "reversible": False, "evidence": ["Boise threads 66F6864D51, C86B928B4D: cards on hold until EXW confirmed"]}, {}),
    ]


def _demo() -> None:
    now = "2026-11-21T20:30:00+01:00"
    base = load_delegations()
    confirmed = [{**d, "confirmed_in_writing": True} for d in base]
    print(f"Approval engine demo, now={now}, delegations={[d['id'] + ('' if d.get('confirmed_in_writing') else ' (unconfirmed)') for d in base]}\n")
    for title, action, opts in demo_actions():
        res = evaluate(action, opts.get("now", now), confirmed if opts.get("confirmed") else base)
        who = _name(res["approver"])
        extra = ""
        if res["co_signers"]:
            extra = " + " + ", ".join(s["name"] for s in res["co_signers"])
        print(f"{title}\n  {res['mode']:<9} {who} ({res['approver']['role']}){extra} | SLA {res['sla_minutes']} min | "
              f"{'; '.join(res['policy_refs'][:2])} | delegation {res['delegation_id']}")
        print(f"  reason: {res['reason']}")
        if res["escalation_chain"]:
            print(f"  chain: {' -> '.join(row_names(res['escalation_chain']))}")
        if res["blocked_by"]:
            print(f"  blocked_by: {res['blocked_by']}")
        if "delegation unconfirmed" in res["notes"]:
            print("  note: delegation unconfirmed")
        print()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Approval engine (PP-07 as code)")
    ap.add_argument("--demo", action="store_true", help="evaluate 8 sample actions")
    ap.add_argument("--list-delegations", action="store_true")
    ap.add_argument("--confirm", metavar="DEL_ID")
    ap.add_argument("--revoke", metavar="DEL_ID")
    ap.add_argument("--by", default="cli")
    ap.add_argument("--evidence", default="")
    args = ap.parse_args(argv)
    if args.demo:
        _demo()
    elif args.list_delegations:
        print(json.dumps(load_delegations(), indent=2, ensure_ascii=False))
    elif args.confirm:
        print(json.dumps(confirm_delegation(args.confirm, args.evidence or "cli confirmation"), indent=2))
    elif args.revoke:
        print(json.dumps(revoke_delegation(args.revoke, args.by), indent=2))
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
