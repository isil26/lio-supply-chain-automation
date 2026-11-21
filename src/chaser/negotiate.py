"""Compare supplier replies, pick the best supplier, and draft price negotiation emails.

Deterministic: numbers come from the replies and the reliability model, never from an LLM.
Negotiation emails are stored as normal `draft` chases, so a person must still review
and press Send. Drafts pass the same guardrails as every other supplier email: no
binding commitments, no maximum price, no deadline slack, no mention of other suppliers.

    python3 -m src.chaser.mail_agent compare [--material CMP-GAM-001] [--db store/soony.db]
    python3 -m src.chaser.mail_agent compare --save-drafts      # store counter-offers for review
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .guardrails import Guardrails

# Assumed EUR conversion, overridable with CHASER_FX_EUR="USD=0.92,CNY=0.13". Shown in every ranking.
DEFAULT_FX_EUR = {"EUR": 1.0, "USD": 0.92, "CNY": 0.13, "INR": 0.011, "PLN": 0.23, "KRW": 0.00068}
DEFAULT_ASK_PCT = 5.0  # first ask when there is no cheaper on-time quote to anchor on
MIN_ON_TIME = 0.5      # below this a quote is a backup, not a pick

CURRENCY = r"(EUR|USD|CNY|RMB|INR|PLN|KRW|€|\$|¥|zł|₩)"
SYMBOLS = {"€": "EUR", "$": "USD", "¥": "CNY", "RMB": "CNY", "ZŁ": "PLN", "₩": "KRW"}
NUMBER = r"(\d{1,3}(?:[ ,.]\d{3})+|\d+)(?:[.,](\d{1,2}))?"
PRICE_RES = (
    re.compile(CURRENCY + r"\s*" + NUMBER, re.I),
    re.compile(NUMBER + r"\s*" + CURRENCY, re.I),
)
QTY_RES = (
    re.compile(r"(?:qty|quantity|available|ilość|수량|数量)\s*[:：=]?\s*(\d{1,3}(?:[,. ]\d{3})+|\d+)", re.I),
    re.compile(r"(\d{1,3}(?:[,. ]\d{3})+|\d+)\s*(?:units|pcs|pieces|szt|개|件|个)", re.I),
)
DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}))?\b")


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
    p_on_time: float | None = None
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

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


def _int(text):
    digits = re.sub(r"[ ,.]", "", text)
    return int(digits) if digits.isdigit() else None


def _unit_context(body, start, end):
    window = body[max(0, start - 40):end + 40].lower()
    return any(word in window for word in ("unit", "/pc", "per pc", "each", "per piece", "/szt", "단가", "单价", "za szt"))


def parse_offer(body):
    """Pull quantity, ETA, unit price and commitment strength out of a reply."""
    out = {"quantity": None, "eta": None, "unit_price": None, "currency": None, "commitment": 0}
    for pattern in QTY_RES:
        if hit := pattern.search(body):
            out["quantity"] = _int(hit[1])
            break
    if hit := DATE_RE.search(body):
        stamp = hit[1] + "T" + (hit[2] or "23:59")
        out["eta"] = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
    prices = []
    for pattern in PRICE_RES:
        for hit in pattern.finditer(body):
            groups = hit.groups()
            cur, whole, cents = (groups[0], groups[1], groups[2]) if pattern is PRICE_RES[0] else (groups[2], groups[0], groups[1])
            value = _int(whole)
            if value is None:
                continue
            amount = value + (int(cents) / (10 ** len(cents)) if cents else 0)
            code = SYMBOLS.get(cur.upper(), cur.upper())
            prices.append((not _unit_context(body, hit.start(), hit.end()), amount, code))
    if prices:
        prices.sort()  # prefer a price that is stated per unit
        _, out["unit_price"], out["currency"] = prices[0]
    score = 0
    if out["eta"]:
        score = 1
    if out["eta"] and out["quantity"]:
        score = 2
    if re.search(r"\b(?:AWB|B/L|BL|booking|tracking|packing list|\d{3}-\d{8}|[A-Z]{4}\d{7})\b", body, re.I):
        score = 3
    out["commitment"] = score
    return out


def quotes_from_db(con, material=None):
    """Latest inbound reply per supplier thread, as quotes."""
    con.row_factory = __import__("sqlite3").Row
    rows = con.execute("""
        SELECT c.id, c.supplier_id, c.supplier, c.address, c.language, c.material, c.qty, m.body
        FROM chases c JOIN messages m ON m.chase_id = c.id AND m.side = 'in'
        WHERE m.id = (SELECT max(id) FROM messages WHERE chase_id = c.id AND side = 'in')
    """).fetchall()
    quotes = []
    for row in rows:
        if material and row["material"] != material:
            continue
        offer = parse_offer(row["body"])
        quotes.append(Quote(row["id"], row["supplier_id"], row["supplier"], row["address"], row["language"],
                            row["material"], int(row["qty"]), offer["quantity"], offer["eta"],
                            offer["unit_price"], offer["currency"], offer["commitment"]))
    return quotes


def _reliability():
    try:
        from src.decide.reliability import SupplierReliability
        return SupplierReliability.from_store()
    except Exception:  # no store or too little history: fall back to the stated ETA
        return None


def rank(quotes, deadline, *, model=None, fx=None):
    """Score quotes for one material. Best first. Each quote gets plain-language reasons."""
    fx = fx or fx_rates()
    deadline = deadline if isinstance(deadline, datetime) else datetime.fromisoformat(deadline)
    prices = [q.price_eur(fx) for q in quotes if q.price_eur(fx) is not None]
    cheapest = min(prices) if prices else None
    for q in quotes:
        q.reasons = []
        if q.eta is None:
            q.p_on_time = 0.0
            q.reasons.append("no delivery date given")
        else:
            p = None
            if model is not None:
                try:
                    p = model.p_on_time(q.supplier_id, q.eta, deadline)
                except Exception:
                    p = None
            q.p_on_time = p if p is not None else (1.0 if q.eta <= deadline else 0.0)
            q.reasons.append(f"{q.p_on_time:.0%} chance to arrive before the cut-off"
                             + (" (history-adjusted)" if p is not None else ""))
        cover = min(1.0, (q.quantity or 0) / q.needed) if q.needed else 0.0
        q.reasons.append(f"covers {cover:.0%} of the {q.needed:,} needed" if q.quantity else "no quantity given")
        eur = q.price_eur(fx)
        price_score = (cheapest / eur) if eur and cheapest else 0.5  # unknown price: neutral
        if eur:
            q.reasons.append(f"{q.unit_price:g} {q.currency}/unit (≈ EUR {eur:.2f})")
        else:
            q.reasons.append("no price yet")
        q.reasons.append(["no evidence", "date only", "date and quantity", "shipping document"][q.commitment])
        # Being on time with enough units matters most; price and evidence break ties.
        q.score = round(100 * (0.55 * q.p_on_time * cover + 0.25 * price_score + 0.20 * q.commitment / 3), 1)
    return sorted(quotes, key=lambda q: (q.p_on_time >= MIN_ON_TIME and bool(q.quantity), q.score), reverse=True)


def negotiation_target(best, ranked, fx=None, ask_pct=DEFAULT_ASK_PCT):
    """Target unit price for the pick, in its own currency, or None if nothing to negotiate."""
    fx = fx or fx_rates()
    own = best.price_eur(fx)
    if own is None:
        return None
    rivals = [q.price_eur(fx) for q in ranked if q is not best and q.p_on_time and q.p_on_time >= MIN_ON_TIME
              and q.price_eur(fx) is not None and q.price_eur(fx) < own]
    target_eur = min(rivals) if rivals else own * (1 - ask_pct / 100)
    target = round(target_eur / fx[best.currency], 2)
    return target if target < best.unit_price else None


TEMPLATES = {
    "en": ("Price review for {material}",
           "Hello,\n\nThank you for your offer of {qty:,} units of {material} at {price:g} {cur} per unit. "
           "To move ahead with this order we would need a delivered unit price of {target:g} {cur} "
           "while keeping the delivery date you stated. Could you let us know if you can review the price?\n\n"
           "This is a request for information only, not an order.\n\nSoony launch team"),
    "pl": ("Weryfikacja ceny {material}",
           "Dzień dobry,\n\ndziękujemy za ofertę na {qty:,} szt. {material} w cenie {price:g} {cur} za sztukę. "
           "Aby przejść dalej, potrzebowalibyśmy ceny {target:g} {cur} za sztukę z dostawą, "
           "przy zachowaniu podanego terminu dostawy. Czy mogą Państwo zweryfikować cenę?\n\n"
           "To jest wyłącznie zapytanie informacyjne, a nie zamówienie.\n\nZespół startowy Soony"),
    "ko": ("{material} 단가 재검토 요청",
           "안녕하세요,\n\n{material} {qty:,}개를 개당 {price:g} {cur}에 제안해 주셔서 감사합니다. "
           "진행을 위해서는 제시하신 납기를 유지하면서 개당 {target:g} {cur}(도착 기준)의 단가가 필요합니다. "
           "단가를 재검토해 주실 수 있는지 알려 주시기 바랍니다.\n\n"
           "이 메일은 정보 요청이며 발주가 아닙니다.\n\nSoony 출시 담당팀"),
    "zh": ("{material} 价格复核请求",
           "您好，\n\n感谢贵司就 {material} {qty:,} 件、单价 {price:g} {cur} 的报价。"
           "为推进此事，我们需要在保持贵司所述交期的前提下，到货单价为 {target:g} {cur}。"
           "请告知贵司能否复核价格。\n\n本邮件仅为信息询问，并非订单。\n\nSoony 上市团队"),
}


def draft_counter(quote, target):
    subject, body = TEMPLATES.get(quote.language, TEMPLATES["en"])
    fields = {"material": quote.material, "qty": quote.quantity or quote.needed, "price": quote.unit_price,
              "cur": quote.currency, "target": target}
    body = body.format(**fields)
    check = Guardrails().validate_draft(body)
    if not check.ok:
        raise ValueError("negotiation draft failed guardrails: " + "; ".join(check.errors))
    ref = hashlib.sha256(f"{quote.thread_id}:negotiate:{target}".encode()).hexdigest()[:10].upper()
    return {"id": ref, "subject": f"[SOONY-{ref}] " + subject.format(**fields), "body": body}


def save_draft(con, quote, draft, deadline):
    """Store as a normal draft chase: it shows up for review and only a person can send it."""
    with con:
        con.execute("""INSERT OR IGNORE INTO chases
            (id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (draft["id"], quote.supplier_id, quote.supplier, quote.address, quote.language,
                     draft["subject"], "draft", quote.material, quote.quantity or quote.needed, draft["body"],
                     deadline if isinstance(deadline, str) else deadline.isoformat()))
        con.execute("INSERT INTO activity(time,agent,action,type) VALUES(?,?,?,?)",
                    (datetime.now(timezone.utc).isoformat(timespec="seconds"), "Mail Agent",
                     f"{quote.supplier}: drafted a price review request ({draft['id']}) for approval.", "info"))


def compare(con, deadline, material=None, *, save=False, model=None):
    """Rank every material's replies; return a JSON-able report."""
    fx = fx_rates()
    model = model if model is not None else _reliability()
    quotes = quotes_from_db(con, material)
    report = {"fx_eur_assumed": fx, "materials": []}
    for mat in sorted({q.material for q in quotes}):
        ranked = rank([q for q in quotes if q.material == mat], deadline, model=model, fx=fx)
        best = ranked[0]
        entry = {"material": mat, "pick": best.supplier if best.p_on_time >= MIN_ON_TIME and best.quantity else None,
                 "ranking": [{"supplier": q.supplier, "score": q.score, "reasons": q.reasons} for q in ranked],
                 "negotiation": None}
        target = negotiation_target(best, ranked, fx) if entry["pick"] else None
        if target is not None:
            draft = draft_counter(best, target)
            entry["negotiation"] = {"supplier": best.supplier, "from": best.unit_price, "to": target,
                                    "currency": best.currency, "draft_id": draft["id"], "body": draft["body"]}
            if save:
                save_draft(con, best, draft, deadline)
        report["materials"].append(entry)
    return report


def to_text(report):
    lines = []
    for entry in report["materials"]:
        lines.append(f"\n{entry['material']}: best supplier = {entry['pick'] or 'none on time yet'}")
        for i, row in enumerate(entry["ranking"], 1):
            lines.append(f"  {i}. {row['supplier']} (score {row['score']}): " + "; ".join(row["reasons"]))
        if n := entry["negotiation"]:
            lines.append(f"  Negotiate: ask {n['supplier']} for {n['to']:g} {n['currency']} instead of {n['from']:g} "
                         f"(draft {n['draft_id']}, needs approval before sending)")
    lines.append("\nCurrency conversion is an assumption: " + json.dumps(report["fx_eur_assumed"]))
    return "\n".join(lines)
