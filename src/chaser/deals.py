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
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .guardrails import Guardrails
from .negotiate import CURRENCY, NUMBER, PRICE_RES, SYMBOLS, parse_offer
from .recovery import NO_COVER, WITHDRAWN, superseded_threads, unquoted
from .reply_plan import supply_constraint

# PP-07 section 2: approval limits per PO in EUR (case-data/soony/context/approval_policy_PP-07.pdf)
PP07 = ((50_000, "Buyer"), (500_000, "Category Lead"), (2_000_000, "Head of Procurement"),
        (5_000_000, "Chief Procurement Officer"))
PROOF = ["no proof", "date only", "date and quantity", "shipping document"]
# Fields that change the terms shown to the buyer. Scoring and refresh times are independent.
TERMS = ("source_hash", "required_by", "needed", "quantity", "order_quantity", "unit_price", "currency", "total_eur",
         "offer_kind", "freight_charge", "carrier",
         "eta", "expires_at", "incoterm", "payment_terms", "moq", "offer_state", "signer")

# A price elsewhere in a reply may be a truck charge, a total or a hypothetical premium.
PER_UNIT = re.compile(r"^\s*(?:each\b|(?:/|per\s+|za\s+|pro\s+)\s*(?:unit|pc|piece|szt|件|个|개|Stück)\w*|一?件|개당)", re.I)
UNIT_LABEL = re.compile(r"(?:unit price|price per (?:unit|piece)|cena jednostkowa|单价|단가)\s*[:=]?\s*$", re.I)
ISO_DATE = r"(\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?)"
EXPIRY = re.compile(r"(?:valid until|expires(?: at| on)?|ważna do|有效期至|유효기간)\s*[:=]?\s*"+ISO_DATE,re.I)
VALIDITY_MENTIONED = re.compile(r"\b(?:valid until|valid for|expires|expiry|ważna do)|有效期|유효기간", re.I)
FREIGHT = re.compile(r"(?:incremental (?:all-in )?(?:freight|transport|truck|haulage)|(?:all-in |total |expedited )(?:freight|trucking) (?:charge|fee|cost)|"
                     r"dopłata (?:transportowa|za transport)|dodatkowy koszt transportu|额外运费|运输附加费|추가 운임)"
                     r"(?:\s+(?:charge|fee|cost|surcharge))?\s*[:=]?\s*" + CURRENCY + r"\s*" + NUMBER, re.I)
CARRIER = re.compile(r"(?:\bcarrier|\bforwarder|\bhaulier|przewoźnik|承运商|운송사)\s*[:：=]\s*([^\n;,]{2,90})", re.I)
INCOTERM = re.compile(r"\b(?:EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DPU|DAP|DDP)\b",re.I)
MOQ = re.compile(r"(?:\bMOQ|\bminimum order(?: quantity)?)\s*[:=]?\s*(\d+(?:[ ,]\d{3})*)",re.I)
PAYMENT = re.compile(r"\bNET\s*[- ]?\d+\b",re.I)
PENDING = re.compile(r"\b(?:unable to confirm|cannot (?:yet )?(?:confirm|commit)|subject to (?:availability|carrier confirmation)|awaiting (?:confirmation|carrier|release)|(?:quote|quotation|price|ETA|arrival|handover|freight|release) (?:is |still )?(?:pending|unconfirmed|to follow)|(?:price|delivery|arrival|quantity) (?:is )?(?:indicative|estimated only)|(?:no|without a) (?:firm|confirmed) (?:ETA|quote|quantity)|(?:(?:binding|formal) (?:order|PO)|payment) (?:is )?required (?:first|to confirm))\b",re.I)

def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def signer(total_eur):
    if total_eur is None:
        return "Awaiting a priced quantity"
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
    columns = {r[1] for r in con.execute("PRAGMA table_info(deals)")}
    extra = {"awaiting_send":"INTEGER DEFAULT 0","required_by":"TEXT", "source_hash":"TEXT", "revision":"TEXT", "offer_state":"TEXT", "review_reason":"TEXT",
             "source_message":"TEXT","expires_at":"TEXT", "order_quantity":"INTEGER",
             "offer_kind":"TEXT", "freight_charge":"REAL", "carrier":"TEXT"}
    for name, typ in extra.items():
        if name not in columns:
            con.execute(f"ALTER TABLE deals ADD COLUMN {name} {typ}")
    con.execute("""CREATE TABLE IF NOT EXISTS deal_decision_history (
        deal_id TEXT NOT NULL, revision TEXT NOT NULL, action TEXT NOT NULL, actor TEXT,
        decided_at TEXT, note TEXT, email_id TEXT UNIQUE, terms TEXT NOT NULL,
        PRIMARY KEY (deal_id, revision))""")


def _digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _source(con, quote):
    row = con.execute("SELECT external_id,body,parsed FROM messages WHERE id=? AND chase_id=?",
                      (quote.reply_id, quote.thread_id)).fetchone()
    message_id, body, parsed = row
    text = "\n".join(line for line in unquoted(body).strip().splitlines() if not line.lstrip().startswith(">"))
    attachments = json.loads(parsed or "{}").get("attachments", [])
    evidence = {"thread": quote.thread_id, "body": text, "attachments": attachments,
                "constraint": quote.constraint}
    return {**evidence, "source_hash": _digest(evidence), "source_message": message_id}


def _date(match, end_of_day=False):
    if match is None:
        return None
    v = match[1]
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    if len(v) == 10 and end_of_day:
        dt = dt.replace(hour=23,minute=59,second=59)
    return dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo("Europe/Berlin"))


def _terms(q, source):
    text = "\n".join([source["body"], *(a.get("text","") for a in source["attachments"])])
    parsed = parse_offer(source["body"],source["attachments"])
    q.quantity = parsed["quantity"]
    q.commitment = parsed["commitment"]
    q.eta = q.stated_arrival
    prices=set()
    for i, pattern in enumerate(PRICE_RES):
        for hit in pattern.finditer(text):
            if not (PER_UNIT.search(text[hit.end():]) or UNIT_LABEL.search(text[max(0,hit.start()-38):hit.start()])):
                continue
            cur,whole,cents = hit.groups() if i==0 else (hit[3],hit[1],hit[2])
            amount=int(re.sub(r"[ ,.]","",whole)) + (float("0."+cents) if cents else 0)
            prices.add((amount,SYMBOLS.get(cur.upper(),cur.upper())))
    q.unit_price,q.currency = prices.pop() if len(prices)==1 else (None,None)
    q.constraint = q.constraint or supply_constraint(text).get("disposition")
    return text


def _review(q, text, total, cutoff, now, expired, superseded, moq, kind, carrier):
    from .mail_plan import classify
    if superseded or WITHDRAWN.search(text):
        return "superseded","The supplier replaced or withdrew this offer."
    if q.quantity == 0 or q.constraint == "no_launch_cover" or NO_COVER.search(text):
        return "unavailable","The supplier cannot supply these units for launch."
    if q.eta and q.eta > cutoff:
        return "late","The quoted arrival is after the launch cutoff."
    if cutoff <= now or (expired and expired <= now):
        return "expired","The offer or launch window has expired."
    if expired is None and VALIDITY_MENTIONED.search(text):
        return "incomplete", "Confirm when the quoted terms expire."
    routed = classify(text)
    if routed:
        state = {"approval": "approval_required", "waiting": "incomplete", "unavailable": "unavailable"}
        return state.get(routed["state"], "incomplete"), f'{routed["owner"]} · {routed["nextAction"]}'
    if q.constraint or PENDING.search(text):
        return "incomplete","The supplier still needs to confirm the terms or release."
    if moq and q.quantity and min(q.needed,q.quantity)<moq and MOQ.search(text):
        return "incomplete","The proposed reservation falls below the supplier’s quoted minimum."
    missing = []
    if not q.quantity: missing.append("available quantity")
    if not total or total <= 0: missing.append("quoted charge and currency" if kind == "freight" else "unit price and currency")
    if not q.eta: missing.append("delivery time")
    if kind == "freight" and not carrier: missing.append("named carrier")
    if kind == "freight" and not expired: missing.append("quote validity")
    if missing:
        return "incomplete","Request " + ", ".join(missing) + " from the supplier."
    if not q.eligible:
        return "unavailable","The offer falls below the required on-time probability."
    return "quoted","Review the quantity, delivered terms and signer before requesting a reservation."


def _archive(con, old, *, capture_options=False):
    if old["status"] not in ("approved","declined"):
        return
    revision = old["revision"] or "legacy"
    terms = {k:old.get(k) for k in (*TERMS,"source_message","excerpt")}
    if capture_options:
        cursor = con.execute("""SELECT id,supplier,thread_id,quantity,order_quantity,price_eur,total_eur,
                                       eta,offer_state,best FROM deals
                                WHERE material=? AND required_by=? AND offer_state!='superseded'
                                ORDER BY best DESC,supplier""", (old["material"], old["required_by"]))
        names = [column[0] for column in cursor.description]
        terms["alternatives"] = [dict(zip(names, row)) for row in cursor]
    con.execute("""INSERT OR IGNORE INTO deal_decision_history
        (deal_id,revision,action,actor,decided_at,note,email_id,terms) VALUES(?,?,?,?,?,?,?,?)""",
        (old["id"],revision,old["status"],old["decided_by"],old["decided_at"],old["note"],old["email_id"],
         json.dumps(terms, ensure_ascii=False)))


def _offer_row(quote, text, source, cutoff, now, fx, superseded):
    facts = quote.facts or {}
    units = min(quote.quantity or 0, quote.needed) or None
    price_eur = quote.price_eur(fx)
    total = round(price_eur * units, 2) if price_eur and units else None
    currency = quote.currency
    expiry = _date(EXPIRY.search(text), end_of_day=True)
    incoterms = INCOTERM.findall(text)
    payment = PAYMENT.search(text)
    minimum = MOQ.search(text)
    moq = int(re.sub(r"\D", "", minimum[1])) if minimum else facts.get("moq")

    freight = FREIGHT.search(text)
    carrier_match = CARRIER.search(text)
    carrier = carrier_match[1].strip().rstrip(".") if carrier_match else None
    kind = "freight" if freight else "goods"
    fee = None
    if freight:
        units = quote.quantity  # Freight covers the quoted lot, even if the buyer needs fewer units.
        fee = float(re.sub(r"\D", "", freight[2]) + "." + (freight[3] or "0"))
        currency = SYMBOLS.get(freight[1].upper(), freight[1].upper())
        total = round(fee * fx[currency], 2) if currency in fx else None
    approver = signer(total)
    if freight and re.search(r"\bair\b", text, re.I):
        approver = "Category Lead (check monthly air-freight spend); CPO above €200,000"

    state, reason = _review(quote, text, total, cutoff, now, expiry, superseded, moq, kind, carrier)
    if freight and (PER_UNIT.search(text[freight.end():]) or quote.unit_price is not None):
        if state == "quoted":
            state, reason = "incomplete", "Confirm the freight total separately from the unit price before requesting a reservation."
        # The amount cannot serve as the all-in charge or the basis for signing authority.
        total, fee, approver = None, None, signer(None)
    return {
        "required_by": cutoff.astimezone(timezone.utc).isoformat(),
        "supplier_id": quote.supplier_id, "supplier": quote.supplier, "material": quote.material,
        "thread_id": quote.thread_id, "address": quote.address, "language": quote.language,
        "needed": quote.needed, "quantity": quote.quantity, "order_quantity": units,
        "offer_kind": kind, "freight_charge": fee, "carrier": carrier,
        "unit_price": None if freight else quote.unit_price, "currency": currency,
        "price_eur": round(price_eur, 4) if price_eur and not freight else None, "total_eur": total,
        "eta": quote.eta.isoformat() if quote.eta else None, "p_on_time": quote.p_on_time,
        "score": quote.score, "eligible": int(state == "quoted"), "proof": PROOF[quote.commitment],
        "incoterm": incoterms[-1].upper() if incoterms else facts.get("incoterm_full"),
        "payment_terms": payment[0] if payment else facts.get("payment_terms"),
        "moq": moq, "list_price": facts.get("list_price"),
        "conditions": "; ".join(r for r in quote.reasons if "minimum" in r or "only conditionally" in r) or None,
        "excerpt": source["body"][:1600], "source_message": source["source_message"], "source_hash": source["source_hash"],
        "expires_at": expiry.isoformat() if expiry else None, "signer": approver,
        "offer_state": state, "review_reason": reason,
    }


def _replace_decision(con, old):
    _archive(con, old)
    con.execute("UPDATE chases SET status='superseded' WHERE id=? AND status='draft'", (old["email_id"],))
    return {"awaiting_send": 0, "decided_by": None, "decided_at": None, "note": None, "email_id": None}


def _store(con, row):
    old = con.execute("SELECT * FROM deals WHERE id=?", (row["id"],)).fetchone()
    terms = [row[k] for k in TERMS]
    if old is None:
        row.update(updated_at=_now(), revision=_digest([row["id"], terms]))
        con.execute(f"INSERT INTO deals({','.join(row)}) VALUES({','.join('?' * len(row))})", tuple(row.values()))
        return
    old = dict(old)
    if not old["revision"] or any(old[k] != row[k] for k in TERMS):
        row.update(_replace_decision(con, old))
        status = "changed" if old["status"] in ("approved", "declined", "changed") else "pending"
        row.update(status=status, revision=_digest([old["revision"], terms]), updated_at=_now())
    assignments = ",".join(k + "=?" for k in row)
    con.execute(f"UPDATE deals SET {assignments} WHERE id=?", (*row.values(), row["id"]))


def sync(con, deadline, *, now=None, model=None):
    from .negotiate import fx_rates, quotes_from_db, score_material, _reliability

    cutoff = datetime.fromisoformat(deadline) if isinstance(deadline, str) else deadline
    now = now or datetime.now(timezone.utc)
    fx = fx_rates()
    model = model if model is not None else _reliability()
    with con:
        # Reserve the writer before reading evidence so a simultaneous buyer cannot approve an obsolete revision.
        if not con.in_transaction:
            con.execute("BEGIN IMMEDIATE")
        schema(con)
        con.execute("UPDATE deals SET id=id WHERE 0")
        superseded = superseded_threads(con)
        # Preserve IDs that buyers may already have opened before deadline-scoped offers.
        from .followup import _aware
        previous_ids = {(supplier, material, _aware(due)): deal for deal, supplier, material, due in con.execute("""
            SELECT d.id,d.supplier_id,d.material,coalesce(d.required_by,c.deadline)
            FROM deals d LEFT JOIN chases c ON c.id=d.thread_id""") if due}
        quotes = quotes_from_db(con, use_thread_deadlines=True)
        sources = {q.reply_id: _source(con, q) for q in quotes}
        texts = {q.reply_id: _terms(q, sources[q.reply_id]) for q in quotes}
        seen = set()
        groups = {}
        for quote in quotes:
            groups.setdefault((quote.material, quote.deadline or cutoff), []).append(quote)
        for (material, window), group in groups.items():
            ranked, _, _ = score_material(group, window, now=now, model=model or None, fx=fx)
            have_best = False
            for q in ranked:
                row = _offer_row(q, texts[q.reply_id], sources[q.reply_id], window, now, fx, q.thread_id in superseded)
                row["id"] = previous_ids.get((q.supplier_id, material, window)) or _digest(
                    [q.supplier_id, material, row["required_by"]])[:16]
                row["best"] = int(not have_best and row["eligible"])
                have_best = have_best or bool(row["best"])
                seen.add(row["id"])
                _store(con, row)
        for record in con.execute("SELECT * FROM deals WHERE coalesce(offer_state,'') != 'superseded'").fetchall():
            old = dict(record)
            if old["id"] not in seen:
                _replace_decision(con, old)
                con.execute("""UPDATE deals SET status='superseded', offer_state='superseded', eligible=0, best=0,
                               review_reason='No current supplier reply supports this offer.', revision=?,
                               decided_by=NULL, decided_at=NULL, note=NULL, email_id=NULL WHERE id=?""",
                            (_digest([old["revision"], "retired"]), old["id"]))
    return len(quotes)


def list_deals(con):
    schema(con)
    cols = [d[0] for d in con.execute("SELECT * FROM deals LIMIT 0").description]
    rows = [dict(zip(cols,r)) for r in con.execute("SELECT * FROM deals ORDER BY material,best DESC,eligible DESC,score DESC")]
    history = {}
    for deal,rev,action,actor,when,note,mail,terms in con.execute(
            "SELECT deal_id,revision,action,actor,decided_at,note,email_id,terms FROM deal_decision_history ORDER BY rowid DESC"):
        history.setdefault(deal,[]).append(dict(revision=rev,action=action,by=actor,at=when,note=note,email_id=mail,terms=json.loads(terms)))
    superseded = superseded_threads(con)
    for row in rows:
        row["history"] = history.get(row["id"],[])
        if row["offer_state"]=="superseded" or row["thread_id"] in superseded:
            row.update(status="superseded", eligible=0, best=0)
        if row["eligible"] and (row["status"] in ("pending", "changed") or (row["status"] == "approved" and row["awaiting_send"])):
            row["drafts"] = {action: _decision_email(row, action) for action in EMAIL}
    return {"deals":rows,"best":[r for r in rows if r["best"]]}


EMAIL = {
    "approve": {
        "en": ("Reservation request: {material}", "Hello,\n\nThank you for your offer for {qty} units of {material} at {price} per unit, arriving {eta}. "
               "Can you reserve this quantity without charge and confirm the hold expiry? Our {signer} must authorize a separate purchase order before dispatch or any cost.\n\nSoony launch team"),
        "pl": ("Prośba o rezerwację: {material}", "Dzień dobry,\n\ndziękujemy za ofertę na {qty} szt. {material} w cenie {price} za sztukę, dostawa {eta}. "
               "Czy mogą Państwo bezpłatnie zarezerwować tę ilość i potwierdzić termin ważności rezerwacji? Wysyłka i koszty wymagają odrębnego zamówienia zatwierdzonego przez: {signer}.\n\nZespół startowy Soony"),
        "ko": ("예약 요청: {material}", "안녕하세요,\n\n{material} {qty}개, 개당 {price}, {eta} 도착 조건의 제안에 감사드립니다. "
               "비용 없이 해당 수량을 확보할 수 있는지와 확보 기한을 알려 주십시오. 출하 및 비용 발생에는 당사 {signer}의 별도 발주서가 필요합니다.\n\nSoony 출시 담당팀"),
        "zh": ("预留请求：{material}", "您好，\n\n感谢贵司就 {material} {qty} 件、单价 {price}、{eta} 到货的报价。"
               "能否免费预留并确认预留期限？请在收到我方 {signer} 批准的正式订单后再发货或产生费用。\n\nSoony 上市团队"),
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
FREIGHT_RESERVATION = {
    "en": ("Provisional freight slot for {material}", "Can you hold the {carrier} slot for {qty} units of {material}, arriving {eta}, without charge? We recorded your incremental freight quote of {price}. Please confirm when the free hold expires. Freight booking and any cost require separate written authorization from Soony."),
    "pl": ("Wstępna rezerwacja transportu {material}", "Czy mogą Państwo bezpłatnie zarezerwować termin przewoźnika {carrier} dla {qty} szt. {material}, z dostawą {eta}? Odnotowaliśmy dodatkową opłatę {price}. Prosimy potwierdzić czas ważności rezerwacji. Zlecenie transportu i wszelkie koszty wymagają odrębnej pisemnej zgody Soony."),
    "ko": ("{material} 운송편 임시 확보 문의", "{material} {qty}개, {eta} 도착 기준으로 {carrier} 운송편을 무료로 임시 확보할 수 있나요? 추가 운임 견적 {price}를 확인했습니다. 무료 확보 기한을 알려 주십시오. 운송 예약 및 비용 발생에는 Soony의 별도 서면 승인이 필요합니다."),
    "zh": ("{material} 临时预留运输时段", "贵司报价额外运费为 {price}。能否免费临时预留 {carrier} 的时段，以便 {qty} 件 {material} 于 {eta} 到达？请确认免费预留期限，订舱或产生任何费用需 Soony 另行书面批准。"),
}


def _stored(con, deal_id):
    cursor = con.execute("SELECT * FROM deals WHERE id=?", (deal_id,))
    record = cursor.fetchone()
    if not record:
        raise KeyError(deal_id)
    return dict(zip((column[0] for column in cursor.description), record))


def _current(con, deal):
    from .negotiate import quotes_from_db
    quote = next((q for q in quotes_from_db(con, deal["material"], use_thread_deadlines=True)
                  if q.supplier_id == deal["supplier_id"] and q.thread_id == deal["thread_id"]), None)
    source = _source(con, quote) if quote else None
    if not source or source["source_hash"] != deal["source_hash"] or deal["thread_id"] in superseded_threads(con):
        raise ValueError("The supplier evidence has changed. Refresh to review the latest terms.")
    if deal["offer_state"] != "quoted" or not deal["eligible"]:
        raise ValueError(deal["review_reason"] or "This offer needs more evidence.")
    deadline = con.execute("SELECT deadline FROM chases WHERE id=?", (deal["thread_id"],)).fetchone()
    expires = [deal.get("expires_at"), deadline[0] if deadline else None]
    if any(datetime.fromisoformat(ts) <= datetime.fromisoformat(_now()) for ts in expires if ts):
        raise ValueError("The offer or launch window has expired.")


def is_decision_draft(con, chase_id):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='deals'").fetchone():
        return False
    return bool(con.execute("""SELECT 1 FROM deals WHERE email_id=? AND eligible=1
                               AND status IN ('approved','declined')""", (chase_id,)).fetchone())


def check_draft(con, chase_id):
    """Revalidate decision correspondence in the sender's claim transaction."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='deals'").fetchone():
        return None
    current = con.execute("SELECT id FROM deals WHERE email_id=?", (chase_id,)).fetchone()
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='deal_decision_history'").fetchone():
        if current:
            raise ValueError("Refresh this legacy offer and review its terms before sending.")
        return None
    archived = con.execute("SELECT deal_id,revision FROM deal_decision_history WHERE email_id=?", (chase_id,)).fetchone()
    if not archived:
        if current:
            raise ValueError("Refresh this legacy offer and review its terms before sending.")
        return None
    deal = _stored(con, archived[0])
    if (deal["revision"] != archived[1] or deal["email_id"] != chase_id
            or deal["status"] not in ("approved","declined")):
        raise ValueError("This response belongs to a superseded offer.")
    _current(con,deal)
    return True


def _decision_email(deal, action):
    lang = deal["language"] if deal["language"] in EMAIL[action] else "en"
    freight = deal["offer_kind"] == "freight"
    subject, body = FREIGHT_RESERVATION[lang] if freight and action == "approve" else EMAIL[action][lang]
    eta = datetime.fromisoformat(deal["eta"]).astimezone(ZoneInfo("Europe/Berlin")).strftime("%d %b %H:%M %Z")
    role = ROLE_LOCAL.get(lang, {}).get(deal["signer"],deal["signer"])
    price = deal["freight_charge"] if freight else deal["unit_price"]
    values = {"material":deal["material"],"qty":f"{deal['order_quantity']:,}",
              "price":f"{price:g} {deal['currency']}","eta":eta,"signer":role,"carrier":deal["carrier"]}
    email_id = hashlib.sha256(f"deal:{deal['id']}:{deal['revision']}:{action}".encode()).hexdigest()[:10].upper()
    return {"id": email_id, "subject": f"[SOONY-{email_id}] " + subject.format(**values), "body": body.format(**values)}


def _queue_email(con, deal, draft, lang):
    email_id, subj = draft["id"], draft["subject"]
    con.execute("""INSERT INTO chases
        (id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline,parent_thread_id,based_on_reply_id)
        VALUES(?,?,?,?,?,?,?,?,?,?,(SELECT deadline FROM chases WHERE id=?),?,(SELECT id FROM messages WHERE external_id=?))""",
                (email_id, deal["supplier_id"],deal["supplier"],deal["address"],lang,subj,"draft",
                 deal["material"],deal["order_quantity"],draft["body"],deal["thread_id"],deal["thread_id"],deal["source_message"]))
    return email_id


def decide(con, deal_id, action, by=None, note=None, *, revision=None, defer_send=False, confirm_held=False):
    """Record one immutable buyer decision and enqueue one nonbinding response per revision."""
    if action not in EMAIL:
        raise ValueError("Action must be approve or decline.")
    with con:
        if not con.in_transaction:
            con.execute("BEGIN IMMEDIATE")
        schema(con)
        con.execute("UPDATE deals SET id=id WHERE 0")
        deal = _stored(con,deal_id)
        if not revision or deal["revision"] != revision:
            raise ValueError("The offer has changed. Refresh before deciding.")
        _current(con,deal)
        status = "approved" if action=="approve" else "declined"
        release_held = bool(confirm_held and action == "approve" and deal["status"] == "approved" and deal["awaiting_send"])
        if confirm_held and not release_held and deal["status"] != "approved":
            raise ValueError("This reservation changed. Review the current offer.")
        if deal["status"] == status and not release_held:
            return deal
        if not release_held and deal["status"] not in ("pending","changed"):
            raise ValueError("A decision is already recorded for this offer revision.")
        if not isinstance(by, str) or not by.strip():
            raise ValueError("Enter the name of the person reviewing this offer.")
        by = by.strip()
        draft = _decision_email(deal, action)
        text = draft["body"]
        lang = deal["language"] if deal["language"] in EMAIL[action] else "en"
        check = Guardrails().validate_draft(text)
        if not check.ok:
            raise ValueError("Email failed guardrails: "+"; ".join(check.errors))
        email_id = None if defer_send else _queue_email(con, deal, draft, lang)
        if release_held:
            con.execute("UPDATE deals SET email_id=?,awaiting_send=0 WHERE id=?", (email_id,deal_id))
            con.execute("UPDATE deal_decision_history SET email_id=? WHERE deal_id=? AND revision=?",
                        (email_id,deal_id,revision))
            con.execute("INSERT INTO activity(time,agent,action,type) VALUES(?,?,?,?)",
                        (_now(), by, f"Queued reviewed reservation request to {deal['supplier']} for {deal['material']}.", "info"))
            return _stored(con,deal_id)
        when = _now()
        con.execute("UPDATE deals SET status=?,decided_by=?,decided_at=?,note=?,email_id=?,awaiting_send=? WHERE id=?",
                    (status,by,when,note,email_id,int(defer_send),deal_id))
        detail = f"Reservation request queued. PO signer: {deal['signer']}." if action=="approve" else "Decline response queued."
        if defer_send:
            detail = "Automatically approved. Supplier email awaits human review."
        con.execute("INSERT INTO activity(time,agent,action,type) VALUES(?,?,?,?)",
                    (when,"Mail Agent",f"{deal['supplier']} offer for {deal['material']} {status} by {by}. {detail}","info"))
        updated = _stored(con,deal_id)
        _archive(con,updated,capture_options=True)
        return updated
