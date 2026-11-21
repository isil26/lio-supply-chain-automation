"""Pick the best supplier per material, split orders, and draft negotiation emails.

The model is deterministic: numbers come from supplier replies, the reliability model and
the clock, never from an LLM. Every output explains itself in plain words.

How "best" is decided (see score_material):
  1. Read the situation for this material:
     - time pressure: how close the cut-off is, and how little slack the offers leave;
     - price spread: how far apart the offered prices are.
  2. Shift the weights: high time pressure moves weight to on-time delivery and delivery
     buffer; a wide price spread moves weight to price. Otherwise the model stays balanced.
  3. Score every offer on seven factors (0..1 each): chance to arrive on time, quantity
     covered, price, delivery buffer, proof given, how fast they answered, and track record.
  4. Offers below a minimum on-time chance are backups only. That floor rises with time pressure.
  5. If no single supplier covers the need on time, split the order across the best ones.
  6. For the pick(s), choose what to negotiate: price, an earlier date, an early partial
     shipment, or a firm expedited freight quote. Each ask is a draft that a person must approve and send.

Negotiation drafts are normal `draft` chases. They pass the guardrails: no binding
commitments, no maximum price, no deadline slack, no mention of other suppliers.

    python3 -m src.chaser.mail_agent compare [--material CMP-GAM-001] [--db store/soony.db] [--save-drafts]
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .guardrails import Guardrails
from .followup import hamburg_time

# Assumed EUR conversion, overridable with CHASER_FX_EUR="USD=0.92,CNY=0.13". Shown with every result.
DEFAULT_FX_EUR = {"EUR": 1.0, "USD": 0.92, "CNY": 0.13, "INR": 0.011, "PLN": 0.23, "KRW": 0.00068}
DEFAULT_ASK_PCT = 5.0       # first price ask when no cheaper on-time offer exists
BASE_FLOOR = 0.30           # minimum on-time chance to be a pick when there is no time pressure
BASE_WEIGHTS = {"on_time": 0.20, "cover": 0.13, "price": 0.17, "buffer": 0.07, "evidence": 0.08,
                "speed": 0.04, "track": 0.08, "logistics": 0.07, "approval": 0.05, "moq": 0.04,
                "terms": 0.04, "diversity": 0.03}
FACTOR_LABELS = {"on_time": "on-time chance", "cover": "quantity covered", "price": "price",
                 "buffer": "delivery buffer", "evidence": "proof given", "speed": "reply speed",
                 "track": "track record", "logistics": "shipping and customs risk",
                 "approval": "supplier approval status", "moq": "minimum order size",
                 "terms": "payment terms", "diversity": "not depending on one supplier"}

CURRENCY = r"(EUR|USD|CNY|RMB|INR|PLN|KRW|€|\$|¥|zł|₩)"
SYMBOLS = {"€": "EUR", "$": "USD", "¥": "CNY", "RMB": "CNY", "ZŁ": "PLN", "₩": "KRW"}
NUMBER = r"(\d{1,3}(?:[ ,.]\d{3})+|\d+)(?:[.,](\d{1,2}))?"
# Keep a currency prefix on a new line from attaching to the previous ETA's offset.
PRICE_RES = (re.compile(CURRENCY + r"[^\S\r\n]*" + NUMBER, re.I),
             re.compile(NUMBER + r"[^\S\r\n]*" + CURRENCY, re.I))
QTY_RES = (
    re.compile(r"(?:qty|quantity|available|ilość|수량|数量)\s*[:：=]?\s*(\d{1,3}(?:[,. ]\d{3})+|\d+)", re.I),
    re.compile(r"(\d{1,3}(?:[,. ]\d{3})+|\d+)\s*(?:units|pcs|pieces|szt|개|件|个)", re.I),
)
DATE_TEXT = (r"(\d{4}-\d{2}-\d{2}|\d{1,2} [A-Za-z]{3,9} \d{4}|[A-Za-z]{3,9} \d{1,2},? \d{4})"
             r"(?:(?:T| (?:at )?)(\d{2}:\d{2})(?::(\d{2}))?\s*(Z|[+-]\d{2}:?\d{2}|CEST|CET|UTC)?)?")
DATE_RE = re.compile(r"\b" + DATE_TEXT, re.I)
# Only a labelled arrival is evidence for pursuing faster freight. A quote's expiry or
# production date is useful context but does not establish where the goods will be.
ARRIVAL_RE = re.compile(
    r"(?:\b(?:ETA|delivery|arrival|handoff|hand-off|arrive|deliver|dostawa|dostawy)\b|到货|交付|도착|납품)"
    r"(?:\s+(?:date|at|to|on|in|by|for|is|will|be|expected|scheduled|planned|termin|w|do|na|"
    r"Hamburg|DC-HAM|the|packing|line|site|factory)){0,9}\s*[:：=]?\s*"
    r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?" + DATE_TEXT, re.I)
SHIPPING_DOC = re.compile(r"\b(?:AWB|air ?waybill|B/L|bill of lading|booking|tracking|packing list|"
                          r"\d{3}-\d{8}|[A-Z]{4}\d{7})\b", re.I)


@dataclass
class Quote:
    thread_id: str
    supplier_id: str
    supplier: str
    address: str
    language: str
    material: str
    needed: int
    quantity: int | None = None
    eta: datetime | None = None
    unit_price: float | None = None
    currency: str | None = None
    commitment: int = 0
    reply_hours: float | None = None      # hours from our email to their answer
    p_on_time: float | None = None
    eta_p90: datetime | None = None
    track: float | None = None            # share of past deliveries on time, if known
    facts: dict = field(default_factory=dict)  # case-file facts (supplier_facts.py)
    factors: dict = field(default_factory=dict)
    score: float = 0.0
    eligible: bool = False
    reasons: list[str] = field(default_factory=list)
    constraint: str | None = None
    reply_id: int | None = None
    deadline: datetime | None = None
    stated_arrival: datetime | None = None
    automation_blocked: bool = False

    def price_eur(self, fx):
        if self.unit_price is None or not self.currency or self.currency not in fx:
            return None
        return self.unit_price * fx[self.currency]


def fx_rates():
    rates = dict(DEFAULT_FX_EUR)
    for item in (os.getenv("CHASER_FX_EUR") or "").split(","):
        code, _, value = item.partition("=")
        try:
            rates[code.strip().upper()] = float(value)
        except ValueError:
            continue
    return rates


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def _int(text):
    digits = re.sub(r"[ ,.]", "", text)
    return int(digits) if digits.isdigit() else None


def _aware(value):
    if value is None:
        return None
    value = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _unit_context(body, start, end):
    window = body[max(0, start - 40):end + 40].lower()
    return any(word in window for word in ("unit", "/pc", "per pc", "each", "per piece", "/szt", "단가", "单价", "za szt"))


# --------------------------------------------------------------------------- reading replies

def _date(match):
    day, clock, seconds, zone = match.groups()
    offset = {"Z": "+00:00", "UTC": "+00:00", "CET": "+01:00", "CEST": "+02:00"}
    zone = (zone or "UTC").upper()
    if not day[:4].isdigit():
        for pattern in ("%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y"):
            try:
                day = datetime.strptime(day.replace(",", ""), pattern).date().isoformat()
                break
            except ValueError:
                continue
    try:
        return datetime.fromisoformat(f"{day}T{clock or '23:59'}:{seconds or '00'}{offset.get(zone, zone)}")
    except ValueError:
        return None


def is_late_offer(body, deadline, attachments=()):
    """True when a supplier offers positive quantity and a specific arrival after cutoff."""
    offer = parse_offer(body, attachments)
    return bool(offer["quantity"] and offer["stated_arrival"] and offer["stated_arrival"] > _aware(deadline))


def parse_offer(body, attachments=()):
    """Quantity, ETA, unit price and proof level from a reply body plus attachment text."""
    from .recovery import unquoted

    body = unquoted("\n".join(line for line in body.splitlines() if not line.lstrip().startswith(">")))
    text = body + "\n" + "\n".join(a.get("text", "") for a in attachments)
    out = {"quantity": None, "eta": None, "unit_price": None, "currency": None, "commitment": 0}
    quantities = {_int(hit[1]) for pattern in QTY_RES for hit in pattern.finditer(text)}
    if len(quantities) == 1:
        out["quantity"] = quantities.pop()
    arrivals = {_date(match) for match in ARRIVAL_RE.finditer(text)}
    out["stated_arrival"] = next(iter(arrivals)) if len(arrivals) == 1 else None
    if out["stated_arrival"]:
        out["eta"] = out["stated_arrival"]
    elif not arrivals and (hit := DATE_RE.search(body) or DATE_RE.search(text)):
        out["eta"] = _date(hit)
    prices = []
    for pattern in PRICE_RES:
        for hit in pattern.finditer(text):
            groups = hit.groups()
            cur, whole, cents = (groups[0], groups[1], groups[2]) if pattern is PRICE_RES[0] else (groups[2], groups[0], groups[1])
            value = _int(whole)
            if value is None:
                continue
            amount = value + (int(cents) / (10 ** len(cents)) if cents else 0)
            prices.append((not _unit_context(text, hit.start(), hit.end()), amount, SYMBOLS.get(cur.upper(), cur.upper())))
    if prices:
        prices.sort()  # prefer a price stated per unit
        _, out["unit_price"], out["currency"] = prices[0]
    if out["eta"]:
        out["commitment"] = 2 if out["quantity"] else 1
    if SHIPPING_DOC.search(body) or any(a.get("kind") for a in attachments):
        out["commitment"] = 3
    return out


def quotes_from_db(con, material=None, *, use_thread_deadlines=False, simulated=False):
    """Latest inbound reply per supplier thread, as quotes (attachments included)."""
    import sqlite3
    from .mail_plan import contexts
    from .recovery import CANCELLED, CANCEL_NEGATED, WITHDRAWN, hamburg_eta, superseded_threads, unquoted
    from .reply_plan import supply_constraint

    con.row_factory = sqlite3.Row
    # The mail planner resolves the most recent substantive reply per conversation,
    # including its parent thread, supplier-authored time and live/replay provenance.
    states = contexts(con, simulated=simulated)
    evidence = {state["replyId"]: state["root"] for state in states.values()}
    rows = con.execute("""
        SELECT c.id, c.supplier_id, c.supplier, c.address, c.language, c.material, root.qty, root.deadline,
               m.id AS reply_id, m.body, m.parsed, coalesce(json_extract(m.transport,'$.authoredAt'),m.time) AS in_time,
               (SELECT min(time) FROM messages WHERE chase_id = root.id AND side = 'out') AS out_time
        FROM json_each(?) e JOIN messages m ON m.id=cast(e.key AS integer)
        JOIN chases c ON c.id=m.chase_id JOIN chases root ON root.id=e.value
        WHERE (? IS NULL OR c.material=?)
        ORDER BY julianday(in_time), m.id
    """, (json.dumps(evidence), material, material)).fetchall()
    # One supplier can answer in several threads (request, reminder, negotiation): keep its newest reply.
    latest = {}
    for row in rows:
        window = _aware(row["deadline"]) if use_thread_deadlines else None
        latest[(row["supplier_id"], row["material"], window)] = row
    rows = list(latest.values())
    quotes = []
    superseded = superseded_threads(con)
    for row in rows:
        try:
            parsed = json.loads(row["parsed"] or "{}")
            attachments = parsed.get("attachments", [])
            constraint = (parsed.get("reply_plan") or {}).get("disposition")
        except (ValueError, AttributeError):
            attachments = []
            constraint = None
        content = unquoted(row["body"])
        constraint = constraint or supply_constraint(content).get("disposition")
        offer = parse_offer(content, attachments)
        # Do not allocate by a quote-expiry, PO issue or unrelated dispatch date.
        offer["eta"] = offer["stated_arrival"]
        cancelled = (CANCELLED.search(content) and not CANCEL_NEGATED.search(content)) or WITHDRAWN.search(content)
        if cancelled:
            constraint = "cancelled"
        if row["id"] in superseded:
            constraint = "no_launch_cover"
        if reported := hamburg_eta(row["body"]):
            offer["stated_arrival"] = offer["eta"] = reported
        reply_hours = None
        try:
            if row["out_time"] and row["in_time"]:
                reply_hours = max(0.0, (_aware(row["in_time"]) - _aware(row["out_time"])).total_seconds() / 3600)
        except ValueError:
            pass
        quotes.append(Quote(row["id"], row["supplier_id"], row["supplier"], row["address"], row["language"],
                            row["material"], int(row["qty"]), offer["quantity"], offer["eta"],
                            offer["unit_price"], offer["currency"], offer["commitment"], reply_hours,
                            constraint=constraint, reply_id=row["reply_id"], deadline=_aware(row["deadline"]),
                            stated_arrival=offer["stated_arrival"], automation_blocked=bool(states[row["id"]]["plan"])))
    return quotes


def _reliability():
    try:
        from src.decide.reliability import SupplierReliability
        return SupplierReliability.from_store()
    except Exception:  # no store or too little history: fall back to the stated ETA
        return None


# --------------------------------------------------------------------------- the model

def situation(quotes, deadline, now, fx):
    """Time pressure and price spread for one material, each 0..1, with plain reasons."""
    hours_left = (deadline - now).total_seconds() / 3600
    clock = _clamp(1 - hours_left / 96)                       # 4 days out: none; at the cut-off: full
    slacks = [(deadline - q.eta).total_seconds() / 3600 for q in quotes if q.eta]
    tight = _clamp(1 - statistics.median(slacks) / 48) if slacks else 1.0
    pressure = round(max(clock, tight), 2)
    prices = [q.price_eur(fx) for q in quotes if q.price_eur(fx)]
    spread = (max(prices) - min(prices)) / statistics.median(prices) if len(prices) > 1 else 0.0
    swing = round(_clamp(spread / 0.25), 2)                   # 25% apart or more: price matters a lot
    if pressure >= 0.6 and pressure >= swing:
        mode = "time-critical"
    elif swing >= 0.6:
        mode = "cost-critical"
    else:
        mode = "balanced"
    return {"hours_left": round(hours_left, 1), "time_pressure": pressure, "price_spread_pct": round(100 * spread, 1),
            "price_pressure": swing, "mode": mode}


def weights_for(context):
    """Shift weight toward delivery under time pressure and toward price under price spread."""
    w = dict(BASE_WEIGHTS)
    t, p = context["time_pressure"], context["price_pressure"]
    w["on_time"] += 0.30 * t
    w["buffer"] += 0.10 * t
    w["price"] += 0.35 * p
    w["speed"] += 0.04 * t
    w["logistics"] += 0.08 * t
    w["approval"] += 0.04 * t
    w["terms"] += 0.05 * p
    total = sum(w.values())
    return {key: round(value / total, 3) for key, value in w.items()}


def score_material(quotes, deadline, *, now=None, model=None, fx=None):
    """Score and order quotes for one material. Returns (ranked, context, weights)."""
    fx = fx or fx_rates()
    deadline = _aware(deadline)
    now = _aware(now) or datetime.now(timezone.utc)
    context = situation(quotes, deadline, now, fx)
    weights = weights_for(context)
    floor = round(BASE_FLOOR + 0.4 * context["time_pressure"], 2)
    context["on_time_floor"] = floor
    prices = [q.price_eur(fx) for q in quotes if q.price_eur(fx)]
    cheapest = min(prices) if prices else None
    for q in quotes:
        if not q.facts:
            try:
                from .supplier_facts import facts as load_facts
                q.facts = load_facts(q.supplier_id, q.material)
            except Exception:
                q.facts = {}
        p = None
        if q.eta is not None and model is not None:
            try:
                p = model.p_on_time(q.supplier_id, q.eta, deadline)
                found = model.discounted_eta(q.supplier_id, q.eta, deadline=deadline)
                q.eta_p90 = max(q.eta, found.eta_p90) if found.eta_p90 else None
                q.track = model.p_on_time(q.supplier_id, deadline, deadline)  # share of deliveries with no delay
            except Exception:
                p = None
        q.p_on_time = 0.0 if q.eta is None or q.eta > deadline else (p if p is not None else 1.0)
        eur = q.price_eur(fx)
        late_eta = q.eta_p90 or q.eta
        buffer_h = (deadline - late_eta).total_seconds() / 3600 if late_eta else None
        q.factors = {
            "on_time": q.p_on_time,
            "cover": _clamp((q.quantity or 0) / q.needed) if q.needed else 0.0,
            "price": (cheapest / eur) if eur and cheapest else 0.5,
            "buffer": _clamp(buffer_h / 24) if buffer_h is not None else 0.0,
            "evidence": q.commitment / 3,
            "speed": 1 / (1 + q.reply_hours / 12) if q.reply_hours is not None else 0.5,
            "track": q.track if q.track is not None else 0.5,
            **fact_factors(q),
        }
        q.score = round(100 * sum(weights[k] * v for k, v in q.factors.items()), 1)
        q.eligible = not q.constraint and bool(q.quantity) and q.p_on_time >= floor
        q.reasons = _reasons(q, eur, buffer_h, floor, p is not None)
    ranked = sorted(quotes, key=lambda q: (q.eligible, q.score), reverse=True)
    return ranked, context, weights


def fact_factors(q):
    """Scores (0..1) from the supplier's case files; 0.5 when the data is missing."""
    from .supplier_facts import INCOTERM_RISK
    f = q.facts or {}
    logistics = INCOTERM_RISK.get(f.get("incoterm"), 0.5) - (0.15 if f.get("customs") else 0)
    units = min(q.quantity or 0, q.needed)
    moq = f.get("moq")
    return {
        "logistics": _clamp(logistics),
        "approval": {"qualified": 1.0, "conditional": 0.4}.get(f.get("qualification"), 0.5),
        "moq": _clamp(units / moq) if moq and units else (1.0 if moq == 0 or (moq and units >= moq) else 0.5),
        "terms": _clamp(f["payment_days"] / 60) if f.get("payment_days") else 0.5,
        "diversity": (1 - f["critical_primary_count"] / f["critical_total"]) if f.get("critical_total") else 0.5,
    }


def _reasons(q, eur, buffer_h, floor, adjusted):
    r = []
    if q.constraint == "no_launch_cover":
        r.append("supplier explicitly ruled out covering this request by launch")
    elif q.constraint == "cancelled":
        r.append("supplier cancelled the shipment or withdrew the offer")
    elif q.constraint == "supplier_hold":
        r.append("supplier release is blocked pending the stated terms")
    f = q.facts or {}
    if q.eta is None:
        r.append("no delivery date given")
    else:
        r.append(f"{q.p_on_time:.0%} chance to arrive before the cut-off" + (" (adjusted for past delays)" if adjusted else ""))
        if buffer_h is not None:
            r.append(f"{buffer_h:.0f} h buffer before the cut-off" if buffer_h >= 0 else f"{-buffer_h:.0f} h too late")
    r.append(f"offers {q.quantity:,} of {q.needed:,} needed" if q.quantity else "no quantity given")
    r.append(f"{q.unit_price:g} {q.currency}/unit (about EUR {eur:.2f})" if eur else "no price yet")
    r.append(["no proof", "date only", "date and quantity", "shipping document"][q.commitment])
    if q.reply_hours is not None:
        r.append(f"answered in {q.reply_hours:.0f} h")
    if q.track is not None:
        r.append(f"{q.track:.0%} of past deliveries had no delay")
    if f.get("incoterm"):
        r.append(f"ships {f['incoterm_full']}" + (" from outside the EU (customs clearance)" if f.get("customs") else ""))
    if f.get("qualification") == "conditional":
        r.append("only conditionally approved (release needed under PP-07)")
    if f.get("moq") and q.quantity and min(q.quantity, q.needed) < f["moq"]:
        r.append(f"usual minimum order is {f['moq']:,}")
    if f.get("payment_terms"):
        r.append(f"pays on {f['payment_terms']}")
    if f.get("critical_primary_count"):
        r.append(f"already main source for {f['critical_primary_count']} critical part(s)")
    if q.quantity and q.p_on_time < floor:
        r.append(f"backup only: below the {floor:.0%} on-time minimum")
    return r


def split_order(ranked, need):
    """Cover the need with as few on-time suppliers as possible, best first."""
    plan, remaining = [], need
    for q in ranked:
        if remaining <= 0 or not q.eligible:
            continue
        take = min(q.quantity, remaining)
        plan.append({"supplier": q.supplier, "thread_id": q.thread_id, "units": take,
                     "expected_on_time_units": round(take * q.p_on_time)})
        remaining -= take
    return {"allocation": plan, "uncovered": max(0, remaining),
            "split": len(plan) > 1}


# --------------------------------------------------------------------------- negotiation

def negotiation_asks(q, ranked, context, deadline, fx=None, ask_pct=DEFAULT_ASK_PCT, units=None, *, now=None):
    """Which levers to pull with this supplier, with target values."""
    fx = fx or fx_rates()
    deadline = _aware(deadline)
    now = _aware(now) or datetime.now(timezone.utc)
    if now >= deadline:
        return []
    asks = []
    own = q.price_eur(fx)
    if own is not None:
        rivals = [r.price_eur(fx) for r in ranked if r is not q and r.eligible and r.price_eur(fx) is not None
                  and r.price_eur(fx) < own]
        pct = ask_pct * (1 + context["price_pressure"])          # push harder when prices swing a lot
        target_eur = min(rivals) if rivals else own * (1 - pct / 100)
        target = round(target_eur / fx[q.currency], 2)
        f = q.facts or {}
        above_list = bool(f.get("list_price") and f.get("list_currency") == q.currency and f["list_price"] < q.unit_price)
        if above_list:
            target = min(target, f["list_price"])                 # the agreed contract price is the anchor
        if target < q.unit_price and (context["mode"] != "time-critical" or rivals or above_list):
            asks.append({"lever": "price", "target": target, "from": q.unit_price, "currency": q.currency})
    if q.eta is not None:
        buffer_h = (deadline - (q.eta_p90 or q.eta)).total_seconds() / 3600
        latest = min(q.eta, deadline)
        if buffer_h < 24 and latest > now:
            wanted = latest - timedelta(hours=24)
            if wanted <= now:
                wanted = latest
            asks.append({"lever": "earlier", "target": hamburg_time(wanted)})
            if q.quantity and q.quantity > (units or q.needed) * 0.5:
                early = max(1, int((units or q.quantity) * 0.5))
                asks.append({"lever": "partial", "units": early, "target": hamburg_time(wanted)})
        if context["time_pressure"] >= 0.6 and buffer_h < 36:
            asks.append({"lever": "express"})
    moq = (q.facts or {}).get("moq")
    wanted_units = min(units or q.quantity or q.needed, q.needed)
    if moq and wanted_units < moq:
        asks.append({"lever": "moq", "units": wanted_units})
    return asks


TEMPLATES = {
    "en": {"subject": "Offer review for {material}",
           "open": "Hello,\n\nThank you for your offer for {qty:,} units of {material}. To move ahead we would like to ask:",
           "price": "- a delivered unit price of {target:g} {currency} instead of {from:g} {currency};",
           "earlier": "- dispatch so the goods reach Hamburg by {target};",
           "partial": "- if the full quantity is not possible earlier, a first partial shipment of {units:,} units by {target};",
           "express": "- a firm quote for express transport, showing the total extra freight charge, currency and quote validity;",
           "expedite": "For up to {units:,} units needed on the packing line by {target}, what is the earliest feasible "
                       "full or partial delivery by expedited transport? Please give the quantity, carrier, pickup and "
                       "packing-line handoff times with time zones, and the timing for the balance. Please quote the "
                       "incremental all-in freight charge and currency above the current terms, quote validity and "
                       "latest release time. Please await written instructions before booking.",
           "moq": "- to accept {units:,} units for this order, below your usual minimum order size;",
           "close": "Could you let us know what is possible?\n\nThis is a request for information only, not an order.\n\nSoony launch team"},
    "pl": {"subject": "Weryfikacja oferty {material}",
           "open": "Dzień dobry,\n\ndziękujemy za ofertę na {qty:,} szt. {material}. Aby przejść dalej, prosimy o:",
           "price": "- cenę {target:g} {currency} za sztukę z dostawą zamiast {from:g} {currency};",
           "earlier": "- wysyłkę tak, aby towar dotarł do Hamburga do {target};",
           "partial": "- jeśli pełna ilość nie jest możliwa wcześniej, pierwszą dostawę częściową {units:,} szt. do {target};",
           "express": "- wiążącą wycenę transportu ekspresowego z pełną dopłatą, walutą i ważnością oferty;",
           "expedite": "Potrzebujemy do {units:,} szt. na linii pakowania do {target}. Jaka jest najwcześniejsza "
                       "możliwa pełna lub częściowa dostawa ekspresowa? Prosimy o ilość, przewoźnika, godziny odbioru "
                       "i przekazania na linię ze strefą czasową oraz termin reszty. Prosimy o pełną dopłatę ponad obecne "
                       "warunki, walutę, ważność wyceny i najpóźniejszą godzinę zwolnienia. Prosimy wstrzymać "
                       "rezerwację do pisemnej dyspozycji.",
           "moq": "- akceptację {units:,} szt. w tym zamówieniu, poniżej zwykłej minimalnej ilości;",
           "close": "Prosimy o informację, co jest możliwe.\n\nTo jest wyłącznie zapytanie informacyjne, a nie zamówienie.\n\nZespół startowy Soony"},
    "ko": {"subject": "{material} 제안 재검토 요청",
           "open": "안녕하세요,\n\n{material} {qty:,}개에 대한 제안에 감사드립니다. 진행을 위해 다음 사항을 요청드립니다:",
           "price": "- 개당 {from:g} {currency} 대신 {target:g} {currency}(도착 기준) 단가;",
           "earlier": "- {target}까지 함부르크에 도착하도록 출고;",
           "partial": "- 전체 수량이 어렵다면 {target}까지 {units:,}개 1차 부분 출하;",
           "express": "- 특송 추가 운임 총액, 통화 및 견적 유효 시각;",
           "expedite": "{target}까지 포장라인에 최대 {units:,}개가 필요합니다. 긴급 운송으로 전량 또는 일부를 "
                       "가장 빨리 인도할 수 있는 시점을 알려 주십시오. 수량, 운송사, 시간대를 포함한 픽업 및 포장라인 "
                       "인도 시각, 잔량 일정을 부탁드립니다. 기존 조건 대비 모든 비용을 포함한 확정 추가 운임과 "
                       "통화, 견적 유효 시각 및 최종 출하 지시 시한을 알려 주십시오. 서면 지시 전에는 예약하지 마십시오.",
           "moq": "- 이번 주문에 한해 통상 최소 주문 수량보다 적은 {units:,}개 수락;",
           "close": "가능한 사항을 알려 주시기 바랍니다.\n\n이 메일은 정보 요청이며 발주가 아닙니다.\n\nSoony 출시 담당팀"},
    "zh": {"subject": "{material} 报价复核请求",
           "open": "您好，\n\n感谢贵司就 {material} {qty:,} 件的报价。为推进此事，我们希望：",
           "price": "- 到货单价 {target:g} {currency}，而非 {from:g} {currency}；",
           "earlier": "- 安排发运，使货物于 {target} 前到达汉堡；",
           "partial": "- 如无法提前交付全部数量，请于 {target} 前先分批发运 {units:,} 件；",
           "express": "- 加急运输的正式报价，列明全部新增运费、币种及报价有效期；",
           "expedite": "包装线需要在 {target} 前收到最多 {units:,} 件。请问采用加急运输，全部或首批最早何时能交付？"
                       "请列明数量、承运人、带时区的提货及包装线交接时间，以及余量交期。请提供比原条款新增的全包运费、"
                       "币种、报价有效期及最迟放行时间。请在收到书面指示后再订舱。",
           "moq": "- 本次订单接受 {units:,} 件，低于贵司通常的最小起订量；",
           "close": "请告知可行方案。\n\n本邮件仅为信息询问，并非订单。\n\nSoony 上市团队"},
}


def draft_counter(quote, asks, units=None, *, deadline=None):
    if not asks:
        return None
    t = TEMPLATES.get(quote.language, TEMPLATES["en"])
    head = {"material": quote.material, "qty": quote.quantity or units or quote.needed}
    lines = [t["open"].format(**head)] + [t[a["lever"]].format(**a) for a in asks] + ["", t["close"]]
    body = "\n".join(lines)
    check = Guardrails().validate_draft(body)
    if not check.ok:
        raise ValueError("negotiation draft failed guardrails: " + "; ".join(check.errors))
    key = json.dumps(asks, sort_keys=True)
    if deadline is not None:
        key += _aware(deadline).astimezone(timezone.utc).isoformat()
    ref = hashlib.sha256(f"{quote.thread_id}:negotiate:{key}".encode()).hexdigest()[:10].upper()
    return {"id": ref, "subject": f"[SOONY-{ref}] " + t["subject"].format(**head), "body": body,
            "levers": [a["lever"] for a in asks]}


def _reserve_window(con, quote, ref, deadline, planned_at):
    """One negotiation per supplier, part and requested window, including pre-upgrade drafts."""
    table_sql = """CREATE TABLE IF NOT EXISTS negotiations (
        supplier_id TEXT NOT NULL, material TEXT NOT NULL, chase_id TEXT NOT NULL, time TEXT NOT NULL,
        deadline TEXT NOT NULL, PRIMARY KEY (supplier_id, material, deadline))"""
    con.execute(table_sql)
    # Begin a write transaction before checking the old schema, so two first-run
    # workers cannot both try to migrate the table.
    con.execute("UPDATE negotiations SET time=time WHERE 0")
    if "deadline" not in {col[1] for col in con.execute("PRAGMA table_info(negotiations)")}:
        con.execute("ALTER TABLE negotiations RENAME TO negotiations_legacy")
        con.execute(table_sql)
        con.execute("""INSERT INTO negotiations
            SELECT n.supplier_id, n.material, n.chase_id, n.time, coalesce(strftime('%Y-%m-%dT%H:%M:%fZ', c.deadline),'')
            FROM negotiations_legacy n LEFT JOIN chases c ON c.id=n.chase_id""")
        con.execute("DROP TABLE negotiations_legacy")
    return con.execute("""INSERT OR IGNORE INTO negotiations (supplier_id,material,chase_id,time,deadline)
                          VALUES(?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ',?))""",
                       (quote.supplier_id, quote.material, ref, planned_at, _aware(deadline).isoformat())).rowcount


def save_draft(con, quote, draft, deadline, units=None):
    """Create at most one negotiation per supplier and part, with its inbound evidence."""
    from .followup import human_owned_thread
    from .mail_plan import blocks_automation
    from .recovery import claimed_threads

    if quote.thread_id in claimed_threads(con) or human_owned_thread(con, quote.thread_id):
        return False
    from .supplier_loop import managed

    if managed(quote.supplier_id, quote.material) or blocks_automation(con, quote.thread_id):
        return False
    with con:
        planned_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not _reserve_window(con, quote, draft["id"], deadline, planned_at):
            return False
        inserted = con.execute("""INSERT OR IGNORE INTO chases
            (id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                               (draft["id"], quote.supplier_id, quote.supplier, quote.address, quote.language,
                                draft["subject"], "draft", quote.material, units or quote.quantity or quote.needed,
                                draft["body"], _aware(deadline).isoformat())).rowcount
        if inserted:
            columns = {column[1] for column in con.execute("PRAGMA table_info(chases)")}
            if {"parent_thread_id", "based_on_reply_id"} <= columns:
                con.execute("UPDATE chases SET parent_thread_id=?, based_on_reply_id=? WHERE id=?",
                            (quote.thread_id, quote.reply_id, draft["id"]))
            con.execute("INSERT INTO activity(time,agent,action,type) VALUES(?,?,?,?)",
                        (datetime.now(timezone.utc).isoformat(timespec="seconds"), "Mail Agent",
                         f"{quote.supplier}: drafted a negotiation email ({', '.join(draft['levers'])}) for review.", "info"))
    return bool(inserted)


# --------------------------------------------------------------------------- report

def compare(con, deadline, material=None, *, save=False, model=None, now=None, use_thread_deadlines=False, simulated=False):
    """Best supplier, split plan and negotiation drafts per material, as JSON-able data."""
    now = _aware(now) or datetime.now(timezone.utc)
    fx = fx_rates()
    model = model if model is not None else _reliability()
    groups = defaultdict(list)
    for quote in quotes_from_db(con, material, use_thread_deadlines=use_thread_deadlines, simulated=simulated):
        cutoff = quote.deadline if use_thread_deadlines else _aware(deadline)
        groups[quote.material, cutoff].append(quote)
    report = {"fx_eur_assumed": fx, "materials": []}
    for (mat, cutoff), candidates in sorted(groups.items()):
        ranked, context, weights = score_material(candidates, cutoff, now=now, model=model or None, fx=fx)
        need = max(q.needed for q in ranked)
        plan = split_order(ranked, need)
        picks = {row["thread_id"]: row["units"] for row in plan["allocation"]}
        top = sorted(weights, key=weights.get, reverse=True)[:3]
        entry = {
            "material": mat, "deadline": cutoff.isoformat(), "need": need, "context": context, "weights": weights,
            "why": f"{context['mode']}: weighing " + ", ".join(FACTOR_LABELS[k] for k in top) + " most",
            "pick": ranked[0].supplier if ranked[0].eligible else None,
            "plan": plan,
            "ranking": [{"supplier": q.supplier, "score": q.score, "eligible": q.eligible,
                         "factors": {k: round(v, 2) for k, v in q.factors.items()}, "reasons": q.reasons}
                        for q in ranked],
            "negotiations": [],
        }
        for q in ranked:
            if cutoff <= now or q.constraint or q.automation_blocked:
                continue
            units = picks.get(q.thread_id)
            if units:
                asks = negotiation_asks(q, ranked, context, cutoff, fx, units=units, now=now)
            elif plan["uncovered"] and q.quantity and q.stated_arrival and q.stated_arrival > cutoff:
                units = min(plan["uncovered"], q.quantity)
                asks = [{"lever": "expedite", "units": units, "target": hamburg_time(cutoff)}]
            else:
                continue
            draft = draft_counter(q, asks, units=units, deadline=cutoff)
            if not draft:
                continue
            saved = save_draft(con, q, draft, cutoff, units) if save and not simulated else False
            entry["negotiations"].append({"supplier": q.supplier, "asks": asks, "draft_id": draft["id"],
                                          "subject": draft["subject"], "body": draft["body"], "saved": saved})
        report["materials"].append(entry)
    return report


def to_text(report):
    lines = []
    for e in report["materials"]:
        c = e["context"]
        lines.append(f"\n{e['material']} (need {e['need']:,}): {e['why']}")
        lines.append(f"  time pressure {c['time_pressure']:.0%}, price spread {c['price_spread_pct']}%, "
                     f"on-time minimum {c['on_time_floor']:.0%}")
        lines.append(f"  best supplier: {e['pick'] or 'none on time yet'}")
        for i, row in enumerate(e["ranking"], 1):
            lines.append(f"  {i}. {row['supplier']} (score {row['score']}): " + "; ".join(row["reasons"]))
        plan = e["plan"]
        if plan["split"]:
            lines.append("  split order: " + ", ".join(f"{a['supplier']} {a['units']:,}" for a in plan["allocation"]))
        if plan["uncovered"]:
            lines.append(f"  still uncovered: {plan['uncovered']:,} units")
        for n in e["negotiations"]:
            lines.append(f"  negotiate with {n['supplier']}: " + ", ".join(a["lever"] for a in n["asks"])
                         + f" (draft {n['draft_id']}, needs approval)")
    lines.append("\nCurrency conversion is an assumption: " + json.dumps(report["fx_eur_assumed"]))
    return "\n".join(lines)
