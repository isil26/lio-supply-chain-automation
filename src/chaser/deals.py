"""T90 (mail-agent, for Gülşah): supplier offers table with Approve / Decline.

Every supplier reply that contains an offer becomes one row per supplier and part in the
`deals` table: quantity, unit price, EUR total, arrival, on-time chance, proof, incoterm,
payment terms, minimum order, conditions and a short quote of the reply. The best offer per
part (from the adaptive model in negotiate.py) is flagged.

Approve:  records who approved, names the PP-07 signer for the EUR total, and drafts a
          non-binding email asking the supplier to reserve the quantity at the offered terms
          while the purchase order is signed. Autosend sends it in live mode.
Decline:  records the decision and drafts a polite "not proceeding for now" email.
If the supplier changes the offer after a decision, the row goes back to "changed".

The table lives in the operational SQLite store only (never in git): it holds prices.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from .guardrails import Guardrails

# PP-07 section 2: approval limits per PO in EUR (case-data/soony/context/approval_policy_PP-07.pdf)
PP07 = ((50_000, "Buyer"), (500_000, "Category Lead"), (2_000_000, "Head of Procurement"),
        (5_000_000, "Chief Procurement Officer"))
PROOF = ["no proof", "date only", "date and quantity", "shipping document"]
FIELDS = ("quantity", "unit_price", "currency", "eta")


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def signer(total_eur):
    if total_eur is None:
        return "Buyer (value unknown until a price is quoted)"
    for limit, role in PP07:
        if total_eur < limit:
            return role
    return "CPO and CFO jointly"


def schema(con):
    con.execute("""CREATE TABLE IF NOT EXISTS deals (
        id TEXT PRIMARY KEY, supplier_id TEXT NOT NULL, supplier TEXT NOT NULL, material TEXT NOT NULL,
        thread_id TEXT, address TEXT, language TEXT, needed INTEGER,
        quantity INTEGER, unit_price REAL, currency TEXT, price_eur REAL, total_eur REAL,
        eta TEXT, p_on_time REAL, score REAL, best INTEGER DEFAULT 0, eligible INTEGER DEFAULT 0,
        proof TEXT, incoterm TEXT, payment_terms TEXT, moq INTEGER, list_price REAL, conditions TEXT,
        excerpt TEXT, signer TEXT, status TEXT NOT NULL DEFAULT 'pending',
        decided_by TEXT, decided_at TEXT, note TEXT, email_id TEXT, updated_at TEXT NOT NULL)""")


def sync(con, deadline, *, now=None, model=None):
    """Write the latest offer per supplier and part. Returns the number of rows touched."""
    from .negotiate import fx_rates, quotes_from_db, score_material, _reliability

    schema(con)
    fx = fx_rates()
    model = model if model is not None else _reliability()
    quotes = quotes_from_db(con)
    excerpts = {row[0]: row[1] for row in con.execute("""
        SELECT c.id, m.body FROM chases c JOIN messages m ON m.chase_id = c.id AND m.side = 'in'
        WHERE m.id = (SELECT max(id) FROM messages WHERE chase_id = c.id AND side = 'in')""")}
    touched = 0
    for material in sorted({q.material for q in quotes}):
        ranked, _, _ = score_material([q for q in quotes if q.material == material], deadline,
                                      now=now, model=model or None, fx=fx)
        for rank, q in enumerate(ranked):
            f = q.facts or {}
            eur = q.price_eur(fx)
            units = min(q.quantity or 0, q.needed) or None
            total = round(eur * units, 2) if eur and units else None
            deal_id = hashlib.sha256(f"{q.supplier_id}:{q.material}".encode()).hexdigest()[:12]
            row = {
                "id": deal_id, "supplier_id": q.supplier_id, "supplier": q.supplier, "material": q.material,
                "thread_id": q.thread_id, "address": q.address, "language": q.language, "needed": q.needed,
                "quantity": q.quantity, "unit_price": q.unit_price, "currency": q.currency,
                "price_eur": round(eur, 4) if eur else None, "total_eur": total,
                "eta": q.eta.isoformat() if q.eta else None, "p_on_time": q.p_on_time, "score": q.score,
                "best": int(rank == 0 and q.eligible), "eligible": int(q.eligible),
                "proof": PROOF[q.commitment], "incoterm": f.get("incoterm_full"),
                "payment_terms": f.get("payment_terms"), "moq": f.get("moq"), "list_price": f.get("list_price"),
                "conditions": "; ".join(r for r in q.reasons if "backup" in r or "only" in r or "cannot" in r
                                        or "hold" in r or "minimum" in r) or None,
                "excerpt": " ".join((excerpts.get(q.thread_id) or "").split())[:280],
                "signer": signer(total), "updated_at": _now(),
            }
            old = con.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
            with con:
                if old is None:
                    cols = ",".join(row)
                    con.execute(f"INSERT INTO deals({cols}) VALUES({','.join('?' * len(row))})", tuple(row.values()))
                else:
                    old = dict(zip([d[0] for d in con.execute("SELECT * FROM deals LIMIT 0").description], old))
                    changed = any(old[k] != row[k] for k in FIELDS)
                    if changed and old["status"] in ("approved", "declined"):
                        row["status"] = "changed"
                    con.execute(f"UPDATE deals SET {','.join(k + '=?' for k in row)} WHERE id=?",
                                (*row.values(), deal_id))
            touched += 1
    return touched


def list_deals(con):
    schema(con)
    cols = [d[0] for d in con.execute("SELECT * FROM deals LIMIT 0").description]
    rows = [dict(zip(cols, r)) for r in con.execute(
        "SELECT * FROM deals ORDER BY material, best DESC, eligible DESC, score DESC")]
    best = {r["material"]: r for r in rows if r["best"]}
    return {"deals": rows, "best": list(best.values())}


EMAIL = {
    "approve": {
        "en": ("Reservation request: {material}", "Hello,\n\nThank you for your offer for {qty} units of {material} at {price} per unit, arriving {eta}. "
               "We would like to go ahead. Please reserve this quantity on these terms; the purchase order follows from our {signer}.\n\n"
               "Until the purchase order is issued this is not an order.\n\nSoony launch team"),
        "pl": ("Prośba o rezerwację: {material}", "Dzień dobry,\n\ndziękujemy za ofertę na {qty} szt. {material} w cenie {price} za sztukę, dostawa {eta}. "
               "Chcemy kontynuować. Prosimy o rezerwację tej ilości na tych warunkach; zamówienie prześle nasz {signer}.\n\n"
               "Do czasu wystawienia zamówienia nie jest to zamówienie.\n\nZespół startowy Soony"),
        "ko": ("예약 요청: {material}", "안녕하세요,\n\n{material} {qty}개, 개당 {price}, {eta} 도착 조건의 제안에 감사드립니다. "
               "진행하고자 합니다. 이 조건으로 수량을 확보해 주시기 바랍니다. 발주서는 당사 {signer}가 발행합니다.\n\n"
               "발주서 발행 전까지는 발주가 아닙니다.\n\nSoony 출시 담당팀"),
        "zh": ("预留请求：{material}", "您好，\n\n感谢贵司就 {material} {qty} 件、单价 {price}、{eta} 到货的报价。我们希望推进。"
               "请按此条件预留数量；采购订单将由我方 {signer} 发出。\n\n在采购订单发出前，本邮件并非订单。\n\nSoony 上市团队"),
    },
    "decline": {
        "en": ("Your offer for {material}", "Hello,\n\nThank you for your offer for {material}. We will not proceed with it for now. "
               "We appreciate your quick answer and will contact you again if our needs change.\n\nSoony launch team"),
        "pl": ("Państwa oferta na {material}", "Dzień dobry,\n\ndziękujemy za ofertę na {material}. Na razie nie będziemy jej realizować. "
               "Dziękujemy za szybką odpowiedź i odezwiemy się, jeśli nasze potrzeby się zmienią.\n\nZespół startowy Soony"),
        "ko": ("{material} 제안 관련", "안녕하세요,\n\n{material} 제안에 감사드립니다. 현재로서는 진행하지 않기로 했습니다. "
               "신속한 회신에 감사드리며 필요가 바뀌면 다시 연락드리겠습니다.\n\nSoony 출시 담당팀"),
        "zh": ("关于贵司 {material} 的报价", "您好，\n\n感谢贵司就 {material} 的报价。我们目前暂不推进。感谢贵司的快速回复，如需求变化我们会再联系。\n\nSoony 上市团队"),
    },
}
ROLE_LOCAL = {"pl": {"Buyer": "kupiec", "Category Lead": "kierownik kategorii", "Head of Procurement": "dyrektor zakupów"}}


def decide(con, deal_id, action, by="team member", note=None):
    """Approve or decline an offer. Returns the updated row plus the drafted email id."""
    from zoneinfo import ZoneInfo

    if action not in ("approve", "decline"):
        raise ValueError("action must be approve or decline")
    schema(con)
    cols = [d[0] for d in con.execute("SELECT * FROM deals LIMIT 0").description]
    raw = con.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
    if not raw:
        raise KeyError(deal_id)
    deal = dict(zip(cols, raw))
    lang = deal["language"] if deal["language"] in EMAIL[action] else "en"
    subject, body = EMAIL[action][lang]
    eta = datetime.fromisoformat(deal["eta"]).astimezone(ZoneInfo("Europe/Berlin")).strftime("%d %b %H:%M %Z") \
        if deal["eta"] else "as stated"
    who = ROLE_LOCAL.get(lang, {}).get(deal["signer"], deal["signer"])
    values = {"material": deal["material"], "qty": f"{min(deal['quantity'] or deal['needed'], deal['needed']):,}",
              "price": f"{deal['unit_price']:g} {deal['currency']}" if deal["unit_price"] else "the quoted price",
              "eta": eta, "signer": who}
    text = body.format(**values)
    check = Guardrails().validate_draft(text)
    if not check.ok:
        raise ValueError("email failed guardrails: " + "; ".join(check.errors))
    email_id = hashlib.sha256(f"deal:{deal_id}:{action}:{deal['updated_at']}".encode()).hexdigest()[:10].upper()
    subj = f"[SOONY-{email_id}] " + subject.format(**values)
    status = "approved" if action == "approve" else "declined"
    with con:
        con.execute("""INSERT OR IGNORE INTO chases
            (id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline)
            VALUES(?,?,?,?,?,?,?,?,?,?,(SELECT deadline FROM chases WHERE id=?))""",
                    (email_id, deal["supplier_id"], deal["supplier"], deal["address"], lang, subj, "draft",
                     deal["material"], deal["quantity"] or deal["needed"], text, deal["thread_id"]))
        con.execute("UPDATE deals SET status=?, decided_by=?, decided_at=?, note=?, email_id=? WHERE id=?",
                    (status, by, _now(), note, email_id, deal_id))
        con.execute("INSERT INTO activity(time,agent,action,type) VALUES(?,?,?,?)",
                    (_now(), "Mail Agent", f"{deal['supplier']} offer for {deal['material']} {status} by {by}. "
                     + (f"PO needs the {deal['signer']}." if action == "approve" else "Polite decline drafted."),
                     "sent" if action == "approve" else "info"))
    deal.update(status=status, decided_by=by, email_id=email_id)
    return deal
