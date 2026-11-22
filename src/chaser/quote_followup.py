"""Collect an actionable supplier quote using only verified correspondence and nonbinding questions."""
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from hashlib import sha256
import re
import json

from . import deadlines, mail_plan, recovery
from .followup import wait_hours
from .supplier_loop import MESSAGE_ID

STATUS = "quote draft"
FIELDS = {
    "en": ("available quantity", "unit price and currency", "delivery date and time at the receiving site"),
    "pl": ("dostępna ilość", "cena jednostkowa i waluta", "data i godzina dostawy do miejsca odbioru"),
    "zh": ("可供数量", "单价和币种", "收货地的交付日期和时间"),
    "ko": ("공급 가능 수량", "단가와 통화", "수령지 도착 날짜 및 시각"),
}
TEMPLATES = {
    "en": ("Hello,", "Could you provide a firm written quote for {part}? We still need {missing}.",
           "Please restate the complete offer for the same lot in one reply: Quantity (units), Unit price (currency per unit), Delivery (YYYY-MM-DD, time and zone), and quote expiry. Itemize any freight charge separately. If the requested window is unavailable, quote the earliest feasible partial delivery.",
           "This is a request for information only.", "Following up on our outstanding quote request."),
    "pl": ("Dzień dobry,", "Prosimy o wiążącą wycenę dla {part}. Brakujące dane: {missing}.",
           "Prosimy podać komplet warunków tej samej partii w jednej odpowiedzi: ilość (szt.), cena jednostkowa (waluta za sztukę), dostawa (RRRR-MM-DD, godzina i strefa czasowa) oraz termin ważności oferty. Prosimy osobno podać koszt transportu. Jeśli termin jest nieosiągalny, prosimy wskazać najwcześniejszy termin dostawy częściowej.",
           "To wyłącznie zapytanie ofertowe.", "Przypominamy o naszym zapytaniu ofertowym."),
    "zh": ("您好，", "请提供 {part} 的正式书面报价。请补充：{missing}。",
           "请在同一封回复中列出同一批货物的全部条件：数量（件）、单价（每件及币种）、收货地交付日期（年-月-日、时间及时区）和报价有效期。请另列运费。如无法按期交付，请报出最早可行的部分交货日期。",
           "本邮件仅为询价。", "请问上一封询价邮件是否有更新？"),
    "ko": ("안녕하세요.", "{part}의 정식 서면 견적을 부탁드립니다. 필요한 정보는 {missing}입니다.",
           "같은 물량에 대해 수량(개), 단가(개당 가격과 통화), 수령지 도착일(연-월-일, 시각 및 시간대), 견적 유효기한을 한 번의 회신에 모두 기재해 주십시오. 운임은 별도로 표시해 주십시오. 요청 기한을 맞추기 어려운 경우 가장 빠른 분할 납품일을 알려 주십시오.",
           "견적 요청만을 위한 문의입니다.", "앞서 요청한 견적의 진행 상황을 알려 주십시오."),
}
SERVICE = re.compile(r"inspection slot|screening|sorting|inspector|PPAP", re.I)


def missing_fields(deal):
    return [i for i,k in enumerate(("quantity","unit_price","eta")) if not deal[k]]


def recap(d):
    # Only carry firm fields from an otherwise plain, incomplete goods quote.
    if (d["offer_kind"] != "goods" or not (d["review_reason"] or "").startswith("Request ")
            or d["expires_at"] or re.search(r"\b(?:indicative|subject to|pending|estimate|if|different lot)\b",d["excerpt"],re.I)):
        return {}
    return {k:d[k] for k in ("quantity","unit_price","currency","eta") if d.get(k) is not None}


def question(d, reminder):
    from .promise_watch import question as promised_question
    lang = d["language"] if d["language"] in FIELDS else "en"
    hello, ask, details, close, follow = TEMPLATES[lang]
    if SERVICE.search(d["excerpt"] or "") or d["offer_kind"] == "freight":
        text = promised_question({**d, "reply_body": d["excerpt"]})
        return (follow + "\n\n" if reminder else "") + text
    fields = [FIELDS[lang][i] for i in missing_fields(d)] or list(FIELDS[lang])
    basis=recap(d)
    known=[str(basis.get("quantity") or ""), (f"{basis['unit_price']:g} {basis['currency']}" if basis.get("unit_price") and basis.get("currency") else ""), str(basis.get("eta") or "")]
    labels=FIELDS[lang]
    restate=" · ".join(f"{label}: {value}" for label,value in zip(labels,known) if value)
    confirm={"en":"Please confirm these previously stated terms for the same lot:",
             "pl":"Prosimy potwierdzić podane wcześniej warunki dla tej samej partii:",
             "zh":"请确认同一批货物此前所述条件：","ko":"같은 물량에 대해 앞서 제시한 조건을 확인해 주십시오:"}
    return "\n\n".join(filter(None,(hello,follow if reminder else None,
                        ask.format(part=d["material"],missing=", ".join(fields)),confirm[lang]+" "+restate if restate else None,details,close)))


def _id(d, reminder=False):
    return sha256(f"quote-completion:{d['id']}:{d['source_message']}:{int(reminder)}".encode()).hexdigest()[:10].upper()


def plans(con, clock=None, *, claim=None):
    """Read-only projection shared between the desk, queue builder and SMTP claim."""
    from . import autosend
    from .negotiate import quotes_from_db
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='deals'").fetchone():
        return {}
    clock = clock or datetime.now(timezone.utc)
    cutoff, fallbacks, parts = deadlines.current_plan(con)
    states = mail_plan.contexts(con)
    latest = {(q.thread_id,q.reply_id) for q in quotes_from_db(con,use_thread_deadlines=True)}
    owned = recovery.claimed_threads(con)
    result = {}
    for deal in con.execute("""SELECT d.*,m.id AS reply_id,m.sender,m.transport FROM deals d JOIN messages m
                ON m.external_id=d.source_message AND m.chase_id=d.thread_id
                WHERE d.status IN ('pending','changed') AND d.eligible=0"""):
        d = dict(deal)
        follow = {"state":"waiting", "missing":[FIELDS["en"][i] for i in missing_fields(d)]}
        if SERVICE.search(d["excerpt"] or ""):
            follow["missing"] = ["inspection capacity", "inspection price", "timed handover"]
        elif d["offer_kind"] == "freight":
            follow["missing"] = [name for key,name in (("quantity","shipment quantity"),("freight_charge","freight charge"),
                                 ("eta","delivery time"),("carrier","carrier"),("expires_at","quote expiry")) if not d[key]]
        result[d["id"]] = follow
        def note(state, detail):
            follow.update(state=state, detail=detail)
        if d["offer_state"] in ("unavailable","late","superseded","expired"):
            note("closed", d["review_reason"])
            continue
        part = parts.get(d["material"],{})
        deadline = deadlines.timestamp(d["required_by"])
        if not deadline or not cutoff or clock >= min(deadline,cutoff,fallbacks.get(d["material"],cutoff)):
            note("closed","The decision window has closed.")
            continue
        if not part.get("shortfall"):
            note("covered","Current supply covers demand. Quote collection is paused.")
            continue
        state = states.get(d["thread_id"],{})
        if state.get("buyerDecided") or d["thread_id"] in owned:
            note("managed","The existing buyer or recovery workflow owns this reply.")
            continue
        if not any(s.get("supplier_id")==d["supplier_id"] and (s.get("supplier") or {}).get("status") not in ("inactive","blocked")
                   for s in part.get("suppliers",[])):
            note("blocked","Supplier qualification needs review.")
            continue
        envelope=json.loads(d["transport"] or "{}")
        if ((d["thread_id"],d["reply_id"]) not in latest or envelope.get("mode")!="inbox"
                or parseaddr(d["sender"])[1].casefold()!=d["address"].casefold() or not MESSAGE_ID.fullmatch(d["source_message"] or "")):
            note("blocked","Waiting for verified supplier correspondence.")
            continue
        if not con.execute("""SELECT 1 FROM messages WHERE chase_id=? AND side='out'
                AND json_extract(transport,'$.status') IN ('smtp_accepted','gmail_sent')""",(d["thread_id"],)).fetchone():
            note("blocked","Waiting for a matched outbound supplier thread.")
            continue
        plan = state.get("plan") or {}
        if plan.get("state") == "waiting":
            if not plan.get("autoCheckpoint") or not plan.get("checkAt"):
                note("waiting","Supplier promised an update. Its timing needs clarification.")
                continue
            when = deadlines.timestamp(plan["checkAt"])
            if clock < when:
                note("scheduled","Supplier promised an update.")
                follow["nextAt"] = when.isoformat()
                continue
        if plan.get("state") == "approval" and plan.get("owner") == "Supplier Quality":
            note("blocked",plan["nextAction"])
            continue
        first, reminder = _id(d), _id(d,True)
        out = con.execute("""SELECT c.id,m.time,json_extract(m.transport,'$.status') FROM messages m JOIN chases c ON c.id=m.chase_id
               WHERE c.supplier_id=? AND c.material=? AND m.side='out' AND m.external_id IS NOT ?
               AND json_extract(m.transport,'$.status') IN ('smtp_accepted','gmail_sent','attempting','delivery_uncertain')
               ORDER BY julianday(m.time) DESC,m.id DESC LIMIT 1""",(d["supplier_id"],d["material"],claim)).fetchone()
        authored=deadlines.timestamp(envelope.get("authoredAt")) or deadlines.timestamp(con.execute(
            "SELECT time FROM messages WHERE id=?",(d["reply_id"],)).fetchone()[0])
        if not out or not authored:
            note("blocked","Waiting for a verified mail timestamp.")
            continue
        sent=deadlines.timestamp(out[1])
        repeat=False
        if sent >= authored:
            follow.update(lastAt=out[1],thread=out[0])
            if out[2] not in ("smtp_accepted","gmail_sent"):
                note("checking","Mail agent is checking delivery.")
                continue
            if out[0]!=first:
                note("sent","Awaiting the supplier’s reply to the latest email.")
                continue
            when=sent+timedelta(hours=wait_hours(sent,deadline))
            if clock < when:
                note("sent","Quote request sent. Awaiting supplier terms.")
                follow["nextAt"]=when.isoformat()
                continue
            repeat=True
        when=sent+timedelta(minutes=autosend.cooldown_minutes())
        if clock < when:
            note("scheduled","Next supplier contact is scheduled.")
            follow["nextAt"]=when.isoformat()
            continue
        if not repeat and sent < authored:
            previous=con.execute("""SELECT m.time FROM messages m JOIN chases c ON c.id=m.chase_id
                WHERE c.address=? AND c.material=? AND m.side='out' AND m.body=?
                AND json_extract(m.transport,'$.status') IN ('smtp_accepted','gmail_sent')
                ORDER BY julianday(m.time) DESC LIMIT 1""",(d["address"],d["material"],question(d,False))).fetchone()
            if previous:
                when=authored+timedelta(hours=wait_hours(authored,deadline))
                if clock < when:
                    note("scheduled","Supplier replied with terms still outstanding. The agent will check again.")
                    follow["nextAt"]=when.isoformat()
                    continue
                repeat=True
        ref=reminder if repeat else first
        queued=con.execute("SELECT status FROM chases WHERE id=?",(ref,)).fetchone()
        if queued and queued[0] not in (STATUS,"sending","superseded draft"):
            note("waiting","The agent has processed this request. Awaiting new supplier evidence.")
            continue
        if con.execute("""SELECT 1 FROM chases WHERE supplier_id=? AND material=? AND status='recovery draft'""",
                       (d["supplier_id"],d["material"])).fetchone():
            note("managed","A recovery request is already queued.")
            continue
        body=question(d,repeat)
        if not claim and autosend.duplicate_body(con,d["address"].lower(),body):
            note("sent","These terms were already requested. Awaiting a revised supplier quote.")
            continue
        note("queued" if queued else "due","Quote reminder queued." if queued and repeat else
             "Quote request queued." if queued else "Mail agent will request the missing terms.")
        follow.update(candidate=(ref,d,part["shortfall"],body))
    return result


def prepare(con,clock):
    from . import activity
    with con:
        if not con.in_transaction:
            con.execute("BEGIN IMMEDIATE")
        for plan in plans(con,clock).values():
            if not plan.get("candidate"):
                continue
            ref,d,gap,body=plan["candidate"]
            subject=con.execute("SELECT subject FROM chases WHERE id=?",(d["thread_id"],)).fetchone()[0]
            added=con.execute("""INSERT INTO chases
                (id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline,parent_thread_id,based_on_reply_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,qty=excluded.qty,body=excluded.body
                WHERE chases.status='superseded draft' AND NOT EXISTS(SELECT 1 FROM messages WHERE chase_id=excluded.id AND side='out')""",(ref,d["supplier_id"],d["supplier"],d["address"],d["language"],
                subject if subject.lower().startswith("re:") else "Re: "+subject,STATUS,d["material"],gap,body,
                d["required_by"],d["thread_id"],d["reply_id"])).rowcount
            if added:
                con.execute("""CREATE TABLE IF NOT EXISTS quote_followup_basis (
                    chase_id TEXT PRIMARY KEY,source_message TEXT NOT NULL,terms TEXT NOT NULL)""")
                con.execute("INSERT OR REPLACE INTO quote_followup_basis VALUES(?,?,?)",(ref,d["source_message"],json.dumps(recap(d))))
                activity(con,"Mail Agent",f"Queued a request for firm supplier terms from {d['supplier']} for {d['material']}.")


def current(con,chase,clock,*,claim=None):
    for plan in plans(con,clock,claim=claim).values():
        if entry:=plan.get("candidate"):
            ref,d,_,body=entry
            if ref==chase["id"]:
                return (body==chase["body"] and d["reply_id"]==chase["based_on_reply_id"]
                        and d["thread_id"]==chase["parent_thread_id"] and d["address"]==chase["address"])
    return False
