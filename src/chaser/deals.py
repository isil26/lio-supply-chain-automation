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
from .negotiate import CURRENCY, NUMBER, QTY_RES, SYMBOLS, parse_offer
from .recovery import NO_COVER, WITHDRAWN, superseded_threads, unquoted
from .reply_plan import supply_constraint

# PP-07 section 2: approval limits per PO in EUR (case-data/soony/context/approval_policy_PP-07.pdf)
PP07 = ((50_000, "Buyer"), (500_000, "Category Lead"), (2_000_000, "Head of Procurement"),
        (5_000_000, "Chief Procurement Officer"))
PROOF = ["no proof", "date only", "date and quantity", "shipping document"]
# Fields that change the terms shown to the buyer. Scoring and refresh times are independent.
TERMS = ("source_hash", "required_by", "needed", "quantity", "order_quantity", "unit_price", "currency", "total_eur",
         "offer_kind", "freight_charge", "freight_currency", "carrier",
         "eta", "expires_at", "incoterm", "payment_terms", "moq", "offer_state", "signer")

# A price elsewhere in a reply may be a truck charge, a total or a hypothetical premium.
PER_UNIT = re.compile(r"^\s*(?:each\b|(?:/|per\s+|za\s+|pro\s+)\s*(?:unit|pc|piece|szt|件|个|개|Stück)\w*|一?件|개당)", re.I)
UNIT_LABEL = re.compile(r"(?:unit price|price per (?:unit|piece)|cena jednostkowa|单价|단가)\s*[:=]?\s*$", re.I)
ISO_DATE = r"(\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)?)"
EXPIRY = re.compile(r"(?:valid until|expires(?: at| on)?|ważna do|有效期至|유효기간)\s*[:=]?\s*"+ISO_DATE,re.I)
VALIDITY_MENTIONED = re.compile(r"\b(?:valid until|valid for|expires|expiry|ważna do)|有效期|유효기간", re.I)
NO_ARRIVAL = re.compile(r"\bno (?:quantity|units?|stock)(?: [^.!?\n]{0,65}?)? can (?:reach|arrive|be delivered)\b"
                        r"[^.!?\n]{0,48}?\b(?:before|by) (\d{1,2}) ([a-z]{3,9})(?: (\d{4}))?(?: at|,)? "
                        r"(\d{1,2}:\d{2}) (CET|CEST|UTC)\b",re.I)
FREIGHT = re.compile(r"(?:(?:incremental|additional) (?:all-in )?(?:freight|transport|truck|haulage)|(?:all-in |total |expedited )(?:freight|trucking) (?:charge|fee|cost)|"
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
             "offer_kind":"TEXT", "freight_charge":"REAL", "freight_currency":"TEXT", "carrier":"TEXT"}
    for name, typ in extra.items():
        if name not in columns:
            con.execute(f"ALTER TABLE deals ADD COLUMN {name} {typ}")
    if "freight_currency" not in columns:
        con.execute("UPDATE deals SET freight_currency=currency WHERE offer_kind='freight' AND freight_charge IS NOT NULL")
    con.execute("""CREATE TABLE IF NOT EXISTS deal_decision_history (
        deal_id TEXT NOT NULL, revision TEXT NOT NULL, action TEXT NOT NULL, actor TEXT,
        decided_at TEXT, note TEXT, email_id TEXT UNIQUE, terms TEXT NOT NULL,
        PRIMARY KEY (deal_id, revision))""")
    con.execute("""CREATE TABLE IF NOT EXISTS deal_requests (
        deal_id TEXT NOT NULL, revision TEXT NOT NULL, actor TEXT NOT NULL, decided_at TEXT NOT NULL,
        purpose TEXT NOT NULL, body TEXT NOT NULL, email_id TEXT NOT NULL UNIQUE, terms TEXT NOT NULL,
        PRIMARY KEY (deal_id,revision))""")
    con.execute("""CREATE TABLE IF NOT EXISTS deal_negotiations (
        deal_id TEXT NOT NULL, revision TEXT NOT NULL, actor TEXT NOT NULL,
        decided_at TEXT NOT NULL, message TEXT NOT NULL, terms TEXT NOT NULL,
        PRIMARY KEY (deal_id, revision, actor, message))""")


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
    reaffirmed = re.search(r"\b(?:all (?:other |previous )?terms (?:remain |are )?(?:unchanged|confirmed)|other terms unchanged|we confirm (?:the |these |your )?(?:previously stated |quoted )?terms|pozostałe warunki bez zmian)\b|其他条件不变|기타 조건은 변경 없",text,re.I)
    negated = re.search(r"\b(?:not|cannot|can.t|no longer|do not|nie)\b[^.\n]{0,60}\b(?:confirm|unchanged|terms|warunk)|条件.{0,5}变更|조건.{0,8}변경됩니다",text,re.I)
    if reaffirmed and not negated and con.execute("SELECT 1 FROM sqlite_master WHERE name='quote_followup_basis'").fetchone():
        previous = con.execute("""SELECT b.source_message,b.terms FROM messages m JOIN messages o
              ON o.external_id=json_extract(m.transport,'$.inReplyTo') AND o.side='out'
              JOIN quote_followup_basis b ON b.chase_id=o.chase_id JOIN chases c ON c.id=o.chase_id
              JOIN chases inbound ON inbound.id=m.chase_id
              WHERE m.id=? AND m.side='in' AND json_extract(m.transport,'$.mode')='inbox'
              AND json_extract(o.transport,'$.status') IN ('smtp_accepted','gmail_sent')
              AND c.supplier_id=inbound.supplier_id AND c.material=inbound.material AND c.address=inbound.address
              AND julianday(c.deadline)=julianday(inbound.deadline)""",(quote.reply_id,)).fetchone()
        if previous and json.loads(previous[1]):
            evidence["confirmed_terms"] = json.loads(previous[1])
            evidence["confirmed_source"] = previous[0]
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


# Unit prices routinely use fractions of a cent. A zero before a single
# separator distinguishes 0,081 EUR from a grouped value such as INR 1,037.
UNIT_AMOUNT = r"(?<![\d.,])(\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)*)(?!\d|[.,]\d)"
UNIT_PRICES = (re.compile(CURRENCY + r"[^\S\r\n]*" + UNIT_AMOUNT, re.I),
               re.compile(UNIT_AMOUNT + r"[^\S\r\n]*" + CURRENCY, re.I))


def _unit_amount(value):
    value = value.replace(" ", "").replace("\u00a0", "")
    parts = re.split("[.,]", value)
    if len(parts) == 1:
        return float(value)
    if parts[0] != "0" and all(len(p) == 3 for p in parts[1:]) and len(set(re.findall("[.,]", value))) == 1:
        return float("".join(parts))
    return float("".join(parts[:-1]) + "." + parts[-1])


def _unit_quote(text):
    prices = set()
    for i, pattern in enumerate(UNIT_PRICES):
        for hit in pattern.finditer(text):
            if not (PER_UNIT.search(text[hit.end():]) or UNIT_LABEL.search(text[max(0,hit.start()-38):hit.start()])):
                continue
            cur, raw = hit.groups() if i == 0 else (hit[2], hit[1])
            prices.add((_unit_amount(raw), SYMBOLS.get(cur.upper(),cur.upper())))
    return prices.pop() if len(prices) == 1 else (None, None)


def _terms(q, source):
    text = "\n".join([source["body"], *(a.get("text","") for a in source["attachments"])])
    parsed = parse_offer(source["body"],source["attachments"])
    q.quantity = parsed["quantity"]
    q.commitment = parsed["commitment"]
    q.eta = q.stated_arrival
    q.unit_price, q.currency = _unit_quote(text)
    if basis := source.get("confirmed_terms"):
        if q.quantity is None and not any(p.search(text) for p in QTY_RES) and not re.search(r"\bquantity\b|数量|수량|ilość",text,re.I):
            q.quantity = basis.get("quantity")
        if q.unit_price is None and not re.search(CURRENCY,text,re.I) and not re.search("price|cena|单价|단가",text,re.I):
            q.unit_price, q.currency = basis.get("unit_price"), basis.get("currency")
        if not q.eta and basis.get("eta") and not re.search("delivery|arrival|ETA|dostaw|到货|도착",text,re.I):
            q.eta = q.stated_arrival = datetime.fromisoformat(basis["eta"])
        if q.quantity and q.eta:
            q.commitment = max(2,q.commitment)
    q.constraint = q.constraint or supply_constraint(text).get("disposition")
    return text


def _review(q, text, total, cutoff, now, expired, superseded, moq, kind, carrier):
    from .mail_plan import classify
    if superseded or WITHDRAWN.search(text):
        return "superseded","The supplier replaced or withdrew this offer."
    if q.quantity == 0 or q.constraint == "no_launch_cover" or NO_COVER.search(text):
        return "unavailable","The supplier cannot supply these units for launch."
    if not q.eta and (refusal := NO_ARRIVAL.search(text)):
        day, month, year, hour, zone = refusal.groups()
        local = cutoff.astimezone(timezone.utc if zone.upper()=="UTC" else ZoneInfo("Europe/Berlin"))
        if (local.day == int(day) and month.casefold() in (local.strftime("%b").casefold(),local.strftime("%B").casefold())
                and (not year or int(year) == local.year) and hour.zfill(5) == local.strftime("%H:%M")
                and local.tzname() == zone.upper()):
            return "unavailable","The supplier ruled out delivery of this lot by the launch cutoff."
    if q.eta and q.eta > cutoff:
        return "late","The quoted arrival is after the launch cutoff."
    if cutoff <= now or (expired and expired <= now):
        return "expired","The offer or launch window has expired."
    if expired is None and VALIDITY_MENTIONED.search(text):
        return "incomplete", "Confirm when the quoted terms expire."
    routed = classify(text)
    # A supplier can quote firm terms while requiring a PO before dispatch.
    # A requirement before quoting, or an outstanding freight or quality decision, still blocks approval.
    if (routed and routed["owner"] == "Procurement" and routed["state"] == "approval"
            and q.quantity and q.eta and total and re.search(
                r"(?:before (?:dispatch|shipment)|(?:dispatch|shipping|wysyłka) (?:requires|wymaga)|prior to dispatch)",text,re.I)
            and not re.search(r"(?:before|prior to) (?:quoting|confirming)|(?:quote|price|quantity|ETA) (?:requires|depends on)",text,re.I)):
        routed = None
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


def _decision_terms(con, old, capture_options):
    terms = {k:old.get(k) for k in (*TERMS,"source_message","excerpt")}
    for key in ("previous_price", "prior_free_hold"):
        if old.get(key):
            terms[key] = old[key]
    if capture_options:
        cursor = con.execute("""SELECT id,supplier,thread_id,quantity,order_quantity,price_eur,total_eur,
                                       eta,offer_state,best FROM deals
                                WHERE material=? AND required_by=? AND offer_state!='superseded'
                                ORDER BY best DESC,supplier""", (old["material"], old["required_by"]))
        names = [column[0] for column in cursor.description]
        terms["alternatives"] = [dict(zip(names, row)) for row in cursor]
    return json.dumps(terms, ensure_ascii=False)


def _archive(con, old, *, capture_options=False):
    if old["status"] not in ("approved","declined"):
        return
    revision = old["revision"] or "legacy"
    con.execute("""INSERT OR IGNORE INTO deal_decision_history
        (deal_id,revision,action,actor,decided_at,note,email_id,terms) VALUES(?,?,?,?,?,?,?,?)""",
        (old["id"],revision,old["status"],old["decided_by"],old["decided_at"],old["note"],old["email_id"],
         _decision_terms(con, old, capture_options)))


def record_negotiation(con, deal_id, revision, actor, message):
    if not isinstance(actor, str) or not actor.strip():
        raise ValueError("Enter the name of the person reviewing this offer.")
    if not isinstance(message, str) or not message.strip() or len(message) > 1000:
        raise ValueError("Enter a negotiation message of up to 1,000 characters.")
    with con:
        if not con.in_transaction:
            con.execute("BEGIN IMMEDIATE")
        schema(con)
        deal = _stored(con, deal_id)
        if not revision or deal["revision"] != revision or deal["offer_state"] == "superseded":
            raise ValueError("The offer has changed. Refresh before starting a negotiation.")
        when = _now()
        inserted = con.execute("""INSERT INTO deal_negotiations
            (deal_id,revision,actor,decided_at,message,terms) VALUES(?,?,?,?,?,?)
            ON CONFLICT(deal_id,revision,actor,message) DO NOTHING""",
            (deal_id, revision, actor.strip(), when, message.strip(), _decision_terms(con, deal, True)))
        if inserted.rowcount:
            con.execute("INSERT INTO activity(time,agent,action,type) VALUES(?,?,?,?)",
                        (when, actor.strip(), f"Started negotiation with {deal['supplier']} for {deal['material']}.", "info"))


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

    charges = list(FREIGHT.finditer(text))
    freight = charges[0] if charges else None
    carrier_match = CARRIER.search(text)
    carrier = carrier_match[1].strip().rstrip(".") if carrier_match else None
    fee = fee_currency = None
    kind = "goods"
    ambiguous_fee = False
    if freight:
        fee = float(re.sub(r"\D", "", freight[2]) + "." + (freight[3] or "0"))
        fee_currency = SYMBOLS.get(freight[1].upper(),freight[1].upper())
        ambiguous_fee = (len(charges)!=1 or bool(PER_UNIT.search(text[freight.end():])))
        if quote.unit_price is None:
            kind, units, currency = "freight", quote.quantity, fee_currency
            total = round(fee * fx[fee_currency],2) if fee_currency in fx else None
        elif (not ambiguous_fee and units==quote.quantity and total is not None and fee_currency in fx
              and re.match(r"(?:incremental|additional|dodatkowy|dopłata|额外|追加|추가)", freight[0], re.I)):
            total = round(total + fee * fx[fee_currency],2)
        else:
            ambiguous_fee = True
    approver = signer(total)
    if freight and re.search(r"\bair\b", text, re.I):
        approver = "Category Lead (check monthly air-freight spend); CPO above €200,000"

    state, reason = _review(quote, text, total, cutoff, now, expiry, superseded, moq, kind, carrier)
    if ambiguous_fee:
        if state == "quoted":
            state, reason = "incomplete", "Confirm the additional freight total for this quantity separately from the unit price."
        total, fee, fee_currency, approver = None, None, None, signer(None)
    return {
        "required_by": cutoff.astimezone(timezone.utc).isoformat(),
        "supplier_id": quote.supplier_id, "supplier": quote.supplier, "material": quote.material,
        "thread_id": quote.thread_id, "address": quote.address, "language": quote.language,
        "needed": quote.needed, "quantity": quote.quantity, "order_quantity": units,
        "offer_kind": kind, "freight_charge": fee, "freight_currency": fee_currency, "carrier": carrier,
        "unit_price": None if kind=="freight" else quote.unit_price, "currency": currency,
        "price_eur": round(price_eur, 4) if price_eur and kind!="freight" else None, "total_eur": total,
        "eta": quote.eta.isoformat() if quote.eta else None, "p_on_time": quote.p_on_time,
        "score": quote.score, "eligible": int(state == "quoted"), "proof": PROOF[quote.commitment],
        "incoterm": incoterms[-1].upper() if incoterms else facts.get("incoterm_full"),
        "payment_terms": payment[0] if payment else facts.get("payment_terms"),
        "moq": moq, "list_price": facts.get("list_price"),
        "conditions": "; ".join(r for r in quote.reasons if "minimum" in r or "only conditionally" in r) or None,
        "excerpt": source["body"], "source_message": source["source_message"], "source_hash": source["source_hash"],
        "expires_at": expiry.isoformat() if expiry else None, "signer": approver,
        "offer_state": state, "review_reason": reason,
    }


def _replace_decision(con, old):
    _archive(con, old)
    _retire_request(con, old)
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
    if old["status"] in ("approved","declined") and all(old[k] == row[k] for k in TERMS if k not in ("total_eur","signer")):
        # Freeze the recorded decision valuation on an unchanged commercial offer.
        for key in ("total_eur","price_eur","signer"):
            row[key] = old[key]
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
    fx = fx_rates(con)
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


FREE_HOLD = re.compile(r"(?:we can|we will|we are able to|we are holding)[^.\n]{0,90}(?:hold|reserv)[^.\n]{0,60}(?:free of charge|at no (?:charge|cost))"
                       r"|(?:możemy bezpłatnie[^.\n]{0,45}(?:odłożyć|zarezerwować)|utrzymujemy bezpłatną rezerwację)",re.I)


def _past_prices(con, rows):
    from .mail_plan import contexts, VERIFIED_SIMULATION
    threads = contexts(con)
    by_root = {}
    for thread, external, when, body, parsed in con.execute(f"""
        SELECT m.chase_id,m.external_id,coalesce(json_extract(m.transport,'$.authoredAt'),m.time),m.body,m.parsed
        FROM messages m WHERE m.side='in' AND NOT {VERIFIED_SIMULATION}
        ORDER BY julianday(coalesce(json_extract(m.transport,'$.authoredAt'),m.time)),m.id"""):
        if thread not in threads:
            continue
        root = threads[thread]["root"]
        clean = "\n".join(line for line in unquoted(body).splitlines() if not line.lstrip().startswith(">"))
        attachments = json.loads(parsed or "{}").get("attachments", [])
        price, currency = _unit_quote("\n".join([clean, *(a.get("text","") for a in attachments)]))
        items = by_root.setdefault(root, [])
        items.append((external, dict(amount=price,currency=currency,at=when,thread_id=thread,message_id=external), bool(FREE_HOLD.search(clean))))
    for row in rows:
        evidence = by_root.get(threads.get(row["thread_id"], {}).get("root"), [])
        previous = None
        prior_hold = False
        for external, price, hold in evidence:
            if external == row["source_message"]:
                row["previous_price"] = previous
                row["prior_free_hold"] = prior_hold
                break
            prior_hold = prior_hold or hold
            if price["amount"] and price["currency"]:
                previous = price


def _request_draft(d):
    text = d["excerpt"] or ""
    if re.search(r"PPAP|inspection|sorting|inspector", text, re.I) and d["offer_state"] != "unavailable":
        label, ask = "inspection proposal", "Please confirm the first inspection slot, throughput, lot acceptance criteria, responsible quality contact and any additional cost for our review."
    elif d["offer_state"] == "approval_required" and d["offer_kind"] == "goods":
        label, ask = "free hold enquiry", "Can you reconfirm the quantity you can hold without charge, the unit price and hold expiry? Please quote the earliest partial delivery, carrier handover and any freight surcharge separately."
    elif re.search(r"deconsolidation|partial.release and collection", text, re.I) and d["offer_state"] != "unavailable":
        label, ask = "carrier handoff request", "Could you provide the carrier contact and handover reference for this shipment so our logistics team can verify partial release and collection directly with the carrier?"
    elif re.search(r"nominat.{0,12}forwarder|EXW.{0,35}in writing", text, re.I) and d["offer_state"] != "unavailable":
        label, ask = "pickup terms request", "Please send the collection address, pickup window, packed dimensions and earliest onward delivery for the available lot. We will review the terms before nominating a forwarder."
    elif re.search(r"change notice|change notification", text, re.I):
        label, ask = "revision review request", "Please identify the outstanding revision documents, the contact who should receive them and the earliest production and delivery dates once they are accepted."
    elif d["offer_state"] in ("unavailable", "late"):
        label, ask = "recovery enquiry", "We have recorded the launch limitation. Please confirm the earliest feasible delivery after the cutoff, available quantity, unit price and any local alternative you can substantiate."
    elif d["offer_kind"] == "freight":
        label, ask = "freight quote request", "Please confirm the carrier, available quantity, pickup and delivery slots, separate all-in freight charge and quotation expiry."
    else:
        label, ask = "firm quote request", "Please confirm the available quantity, unit price and currency, earliest delivery and quote expiry. Please quote any additional transport separately."
    email_id = hashlib.sha256(f"deal:{d['id']}:{d['revision']}:request".encode()).hexdigest()[:10].upper()
    if previous := d.get("previous_price"):
        amount = f"{previous['amount']:g} {previous['currency']} per unit"
        if d["offer_state"] in ("incomplete","approval_required") and d.get("prior_free_hold") and d["needed"] and d["offer_kind"] == "goods":
            label = "conditional hold"
            ask = (f"If your earlier price of {amount} and free hold are still available, please reserve up to "
                   f"{d['needed']:,} units without charge. Please confirm the quantity held, hold expiry and unit price in writing. "
                   "Please quote partial delivery, freight surcharge and handover time separately for review.")
        else:
            ask = f"Your earlier correspondence mentioned {amount}. " + ask
    body = f"Hello {d['supplier']} team,\n\nRegarding {d['material']}:\n{ask}\n\nAny dispatch, booking or cost requires separate written authorization.\n\nSoony launch team"
    return {"id":email_id, "label":label, "subject":f"[SOONY-{email_id}] {label.capitalize()} for {d['material']}", "body":body}


def list_deals(con):
    schema(con)
    cols = [d[0] for d in con.execute("SELECT * FROM deals LIMIT 0").description]
    rows = [dict(zip(cols,r)) for r in con.execute("SELECT * FROM deals ORDER BY material,best DESC,eligible DESC,score DESC")]
    _past_prices(con, rows)
    history = {}
    for deal,rev,action,actor,when,note,mail,terms in con.execute(
            """SELECT deal_id,revision,action,actor,decided_at,note,email_id,terms FROM deal_decision_history
               UNION ALL
               SELECT deal_id,revision,'negotiation started',actor,decided_at,message,NULL,terms FROM deal_negotiations
               UNION ALL
               SELECT deal_id,revision,purpose || ' approved',actor,decided_at,body,email_id,terms FROM deal_requests
               ORDER BY decided_at DESC"""):
        history.setdefault(deal,[]).append(dict(revision=rev,action=action,by=actor,at=when,note=note,email_id=mail,terms=json.loads(terms)))
    superseded = superseded_threads(con)
    for row in rows:
        row["history"] = history.get(row["id"],[])
        if row["offer_state"]=="superseded" or row["thread_id"] in superseded:
            row.update(status="superseded", eligible=0, best=0)
        open_offer = row["status"] in ("pending", "changed") and row["offer_state"] not in ("superseded", "expired")
        row["drafts"] = {}
        request = con.execute("""SELECT c.status,r.purpose FROM deal_requests r JOIN chases c ON c.id=r.email_id
                                 WHERE r.deal_id=? AND r.revision=?""",(row["id"],row["revision"])).fetchone()
        if request:
            row["request"] = {"status":request[0],"purpose":request[1]}
        elif open_offer and not row["eligible"]:
            row["request_draft"] = _request_draft(row)
        if open_offer:
            row["drafts"]["decline"] = _decision_email(row, "decline")
        if row["eligible"] and (open_offer or (row["status"] == "approved" and row["awaiting_send"])):
            row["drafts"]["approve"] = _decision_email(row, "approve")
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


def _current(con, deal, action):
    from .negotiate import quotes_from_db
    quote = next((q for q in quotes_from_db(con, deal["material"], use_thread_deadlines=True)
                  if q.supplier_id == deal["supplier_id"] and q.thread_id == deal["thread_id"]), None)
    source = _source(con, quote) if quote else None
    if not source or source["source_hash"] != deal["source_hash"] or deal["thread_id"] in superseded_threads(con):
        raise ValueError("The supplier evidence has changed. Refresh to review the latest terms.")
    if deal["offer_state"] in ("superseded", "expired"):
        raise ValueError(deal["review_reason"] or "This offer is closed.")
    if action == "approve" and (deal["offer_state"] != "quoted" or not deal["eligible"]):
        raise ValueError(deal["review_reason"] or "This offer needs more evidence.")
    deadline = con.execute("SELECT deadline FROM chases WHERE id=?", (deal["thread_id"],)).fetchone()
    expires = [deal.get("expires_at"), deadline[0] if deadline else None]
    if any(datetime.fromisoformat(ts) <= datetime.fromisoformat(_now()) for ts in expires if ts):
        raise ValueError("The offer or launch window has expired.")


def _retire_request(con, deal):
    con.execute("""UPDATE chases SET status='superseded' WHERE status='draft' AND id IN
                   (SELECT email_id FROM deal_requests WHERE deal_id=? AND revision=?)""",
                (deal["id"], deal["revision"]))


def _approved_request(con, chase_id):
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='deal_requests'").fetchone():
        return con.execute("SELECT deal_id,revision FROM deal_requests WHERE email_id=?", (chase_id,)).fetchone()
    return None


def is_decision_draft(con, chase_id):
    if _approved_request(con, chase_id):
        return True
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='deals'").fetchone():
        return False
    return bool(con.execute("""SELECT 1 FROM deals WHERE email_id=?
                               AND ((eligible=1 AND status='approved') OR status='declined')""", (chase_id,)).fetchone())


def check_draft(con, chase_id):
    """Revalidate decision correspondence in the sender's claim transaction."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='deals'").fetchone():
        return None
    if request := _approved_request(con, chase_id):
        deal = _stored(con, request[0])
        if deal["revision"] != request[1] or deal["status"] not in ("pending","changed"):
            raise ValueError("The supplier request has been superseded.")
        _current(con, deal, "request")
        return True
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
    _current(con, deal, "decline" if deal["status"] == "declined" else "approve")
    return True


def _decision_email(deal, action):
    lang = deal["language"] if deal["language"] in EMAIL[action] else "en"
    freight = deal["offer_kind"] == "freight"
    subject, body = FREIGHT_RESERVATION[lang] if freight and action == "approve" else EMAIL[action][lang]
    values = {"material": deal["material"]}
    if action == "approve":
        eta = datetime.fromisoformat(deal["eta"]).astimezone(ZoneInfo("Europe/Berlin"))
        role = ROLE_LOCAL.get(lang, {}).get(deal["signer"], deal["signer"])
        price = deal["freight_charge"] if freight else deal["unit_price"]
        values.update(qty=f"{deal['order_quantity']:,}", price=f"{price:g} {deal['currency']}",
                      eta=eta.strftime("%d %b %H:%M %Z"), signer=role, carrier=deal["carrier"])
    email_id = hashlib.sha256(f"deal:{deal['id']}:{deal['revision']}:{action}".encode()).hexdigest()[:10].upper()
    return {"id": email_id, "subject": f"[SOONY-{email_id}] " + subject.format(**values), "body": body.format(**values)}


def _queue_email(con, deal, draft, lang):
    email_id, subj = draft["id"], draft["subject"]
    con.execute("""INSERT INTO chases
        (id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline,parent_thread_id,based_on_reply_id)
        VALUES(?,?,?,?,?,?,?,?,?,?,(SELECT deadline FROM chases WHERE id=?),?,(SELECT id FROM messages WHERE external_id=?))""",
                (email_id, deal["supplier_id"],deal["supplier"],deal["address"],lang,subj,"draft",
                 deal["material"],deal["order_quantity"] or 0,draft["body"],deal["thread_id"],deal["thread_id"],deal["source_message"]))
    return email_id


def approve_request(con, deal_id, revision, by, message):
    if not isinstance(by, str) or not by.strip():
        raise ValueError("A named reviewer is required.")
    if not isinstance(message, str) or not message.strip() or len(message) > 1000:
        raise ValueError("Enter an email message of 1 to 1,000 characters.")
    with con:
        if not con.in_transaction:
            con.execute("BEGIN IMMEDIATE")
        schema(con)
        deal = _stored(con,deal_id)
        if not revision or deal["revision"] != revision or deal["status"] not in ("pending","changed") or deal["eligible"]:
            raise ValueError("Refresh and review the current supplier offer.")
        _current(con, deal, "request")
        existing = con.execute("SELECT email_id FROM deal_requests WHERE deal_id=? AND revision=?", (deal_id,revision)).fetchone()
        if existing:
            return existing[0]
        check = Guardrails().validate_draft(message)
        if not check.ok:
            raise ValueError("Email failed guardrails: " + "; ".join(check.errors))
        _past_prices(con, [deal])
        draft = _request_draft(deal)
        draft["body"] = message
        email_id = _queue_email(con, deal, draft, "en")
        when = _now()
        con.execute("INSERT INTO deal_requests VALUES(?,?,?,?,?,?,?,?)",
                    (deal_id,revision,by.strip(),when,draft["label"],message,email_id,_decision_terms(con,deal,True)))
        con.execute("INSERT INTO activity(time,agent,action,type) VALUES(?,?,?,?)",
                    (when,by.strip(),f"Approved {draft['label']} for {deal['material']} from {deal['supplier']}.","info"))
        return email_id


def decide(con, deal_id, action, by=None, note=None, *, revision=None, defer_send=False, confirm_held=False, message=None):
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
        _current(con, deal, action)
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
        if message is not None:
            if not isinstance(message, str) or not message.strip() or len(message) > 1000:
                raise ValueError("Enter an email message of 1 to 1,000 characters.")
            draft["body"] = message
        text = draft["body"]
        lang = deal["language"] if deal["language"] in EMAIL[action] else "en"
        check = Guardrails().validate_draft(text)
        if not check.ok:
            raise ValueError("Email failed guardrails: "+"; ".join(check.errors))
        _retire_request(con, deal)
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
