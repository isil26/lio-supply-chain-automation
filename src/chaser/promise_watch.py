"""Follow a supplier's outstanding quote or proposal while the shortage is actionable."""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parseaddr

from . import deadlines, mail_plan, recovery
from .supplier_loop import MESSAGE_ID


def checkpoint(text, received, cutoff):
    """Respect identifiable supplier timing. Ambiguous dated promises stay with Procurement."""
    from .followup import wait_hours

    fallback = received + timedelta(hours=wait_hours(received, cutoff))
    dates = []
    for sentence in re.split(r"[.!?。\n]", text):
        if not mail_plan.PROMISE.search(sentence):
            continue
        duration = re.search(r"\bwithin (\d{1,3}) (hours?|minutes?|days?)\b", sentence, re.I)
        if duration:
            unit = duration[2].lower().rstrip("s") + "s"
            dates.append(received + timedelta(**{unit: int(duration[1])}))
            continue
        # Interpret the supplier's stated timezone; the receiving site's clock
        # alone cannot tell us what a supplier meant by "tomorrow morning".
        window = re.search(r"\b(?:(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{4}-\d{2}-\d{2})[ T]+)?"
                           r"(?:at\s+|by\s+)?(morning|afternoon|evening|[0-2]?\d:[0-5]\d)\s+"
                           r"(UTC|GMT|CET|CEST|KST|JST)\b", sentence, re.I)
        if window:
            day, period, zone = (value.lower() if value else "" for value in window.groups())
            offset = {"utc": 0, "gmt": 0, "cet": 1, "cest": 2, "kst": 9, "jst": 9}[zone]
            local = received.astimezone(timezone(timedelta(hours=offset)))
            weekdays = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
            days = (weekdays.index(day) - local.weekday()) % 7 if day in weekdays else int(day == "tomorrow")
            end = {"morning": "12:00", "afternoon": "18:00", "evening": "22:00"}.get(period, period)
            hour, minute = map(int, end.split(":"))
            if hour > 23:
                return min(cutoff, fallback), False
            try:
                target = date.fromisoformat(day) if day[:1].isdigit() else local.date() + timedelta(days=days)
            except ValueError:
                return min(cutoff, fallback), False
            if not day and re.search(r"\b(?:on|next)\s+\w+|\b\d{4}-\d{2}-\d{2}\b", sentence, re.I):
                return min(cutoff, fallback), False
            when = datetime.combine(target, time(hour, minute), local.tzinfo)
            if when < local and not day:
                when += timedelta(days=1)
            dates.append(when)
        elif re.search(r"tomorrow|today|morning|afternoon|evening|next (?:week|business day)|\bby\b|within|at \d|"
                       r"\d:\d|\b\d{4}-\d{2}-\d{2}|\bon \d|in \d+ (?:hours?|days?)|\b(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day|jutro|dzisiaj|明天|내일", sentence, re.I):
            return min(cutoff, fallback), False
    return min(cutoff, max(dates) if dates else fallback), True


# Each question seeks an update on the supplier's own proposal. The worker can
# discuss the cost of an option without requesting a booking or a quality release.
QUESTIONS = {
    "en": {
        "inspection": "Is the inspection proposal for {part} available? What is the earliest inspection slot, how many units could be screened by each handover, and what is the quoted cost? Please include the reference for Quality to review.",
        "freight": "Is the carrier quote for {part} available? Please give the quantity that can reach the receiving site, the timed handover, the additional freight charge and the quote expiry. Could a partial load arrive earlier?",
        "quote": "Do you have the update you offered for {part}? Please share the quantity, delivered price and earliest handover at the receiving site. If only a partial quantity is possible, what quantity and time can you quote?",
    },
    "pl": {
        "inspection": "Czy mają już Państwo propozycję kontroli dla {part}? Prosimy o najwcześniejszy termin, liczbę sztuk możliwych do sprawdzenia w kolejnych partiach oraz wycenę i numer referencyjny dla działu jakości.",
        "freight": "Czy jest już wycena przewoźnika dla {part}? Prosimy o liczbę sztuk, które mogą dotrzeć do miejsca odbioru, godzinę przekazania, dopłatę oraz termin ważności wyceny. Czy część ładunku może dotrzeć wcześniej?",
        "quote": "Czy mają już Państwo zapowiedzianą informację dla {part}? Prosimy o dostępną ilość, cenę z dostawą i najwcześniejszą godzinę przekazania w miejscu odbioru, także dla dostawy częściowej.",
    },
}
GENERIC = {
    "ko": "{part} 관련하여 말씀하신 검토 결과가 나왔나요? 가능한 수량, 운송비 포함 가격, 수령지 인계 시각을 알려 주세요. 일부 수량을 더 일찍 인계할 수 있다면 그 조건도 부탁드립니다.",
    "zh": "请问贵方提到的 {part} 方案有更新吗？请告知可供数量、含运费价格和最早在收货地交接的时间。如可提前交接部分货物，也请说明数量和条件。",
}
WRAP = {
    "en": ("Hello,", "This is an information request only.\n\nProcurement team"),
    "pl": ("Dzień dobry,", "To wyłącznie zapytanie informacyjne.\n\nZespół zakupów"),
    "zh": ("您好，", "本邮件仅为信息询问。\n\n采购团队"),
    "ko": ("안녕하세요.", "정보 확인을 위한 문의입니다.\n\n구매팀"),
}


def question(row):
    language = row["language"] if row["language"] in WRAP else "en"
    evidence = recovery.unquoted(row["reply_body"])
    kind = "quote"
    if re.search(r"inspect|screening|\bsort(?:ing)?\b|kontrol", evidence, re.I):
        kind = "inspection"
    elif re.search(r"carrier|freight|transport|przewoźni|przewoź|trucking", evidence, re.I):
        kind = "freight"
    ask = GENERIC[language] if language in GENERIC else QUESTIONS[language][kind]
    hello, signature = WRAP[language]
    return "\n\n".join((hello, ask.format(part=row["material"]), signature))


def opportunities(con, clock, *, claim=None):
    cutoff, fallbacks, parts = deadlines.current_plan(con)
    if not cutoff or clock >= cutoff:
        return {}
    states = mail_plan.contexts(con)
    owned = recovery.claimed_threads(con)
    rows = con.execute("""SELECT c.*, m.id AS reply_id,m.external_id,m.sender,m.body AS reply_body,
               coalesce(json_extract(m.transport,'$.authoredAt'),m.time) AS authored
        FROM messages m JOIN chases c ON c.id=m.chase_id
        WHERE m.side='in' AND json_extract(m.transport,'$.mode')='inbox'
        ORDER BY julianday(authored) DESC,m.id DESC""")
    seen = set()
    due = {}
    for row in rows:
        pair = row["supplier_id"], row["material"]
        state = states.get(row["id"], {})
        if state.get("replyId") != row["reply_id"] or pair in seen:
            continue
        seen.add(pair)
        plan = state.get("plan") or {}
        part = parts.get(row["material"], {})
        gap = part.get("shortfall", 0)
        sources = part.get("suppliers", [])
        if not any(source.get("supplier_id") == pair[0] and (source.get("supplier") or {}).get("status")
                   not in ("inactive", "blocked") for source in sources):
            continue
        deadline = deadlines.timestamp(row["deadline"])
        if (not gap or not deadline or clock >= min(deadline, fallbacks.get(pair[1], cutoff), cutoff)
                or state.get("buyerDecided") or row["id"] in owned or plan.get("state") != "waiting"
                or not plan.get("autoCheckpoint") or not plan.get("checkAt")
                or clock < deadlines.timestamp(plan["checkAt"])
                or parseaddr(row["sender"])[1].casefold() != row["address"].casefold()
                or not MESSAGE_ID.fullmatch(row["external_id"] or "")):
            continue
        # Require an accepted request and yield to subsequent correspondence, including
        # uncertain deliveries and questions sent by a teammate in a different thread.
        receipts = con.execute("""SELECT max(julianday(m.time)),
                     max(CASE WHEN c.id=? AND json_extract(m.transport,'$.status') IN ('smtp_accepted','gmail_sent')
                              THEN 1 ELSE 0 END), julianday(?)
            FROM messages m JOIN chases c ON c.id=m.chase_id
            WHERE c.supplier_id=? AND c.material=? AND m.side='out' AND m.external_id IS NOT ?
              AND json_extract(m.transport,'$.status') IN ('smtp_accepted','gmail_sent','attempting','delivery_uncertain')""",
                               (row["id"], row["authored"], *pair, claim)).fetchone()
        if not receipts[1] or receipts[2] is None or receipts[0] > receipts[2]:
            continue
        body = question(row)
        ref = hashlib.sha256(f"promise:{row['external_id']}:{row['material']}".encode()).hexdigest()[:10].upper()
        due[ref] = (row, gap, body)
    return due


def prepare(con, clock):
    with con:
        for ref, (row, gap, body) in opportunities(con, clock).items():
            subject = row["subject"] if row["subject"].lower().startswith("re:") else "Re: " + row["subject"]
            inserted = con.execute("""INSERT OR IGNORE INTO chases
                (id,supplier_id,supplier,address,language,subject,status,material,qty,body,deadline,parent_thread_id,based_on_reply_id)
                VALUES(?,?,?,?,?,?,'promise draft',?,?,?,?,?,?)""",
                (ref,row["supplier_id"],row["supplier"],row["address"],row["language"],subject,
                 row["material"],gap,body,row["deadline"],row["id"],row["reply_id"])).rowcount
            if inserted:
                from . import activity
                activity(con, "Mail Agent", f"{row['supplier']}: queued a follow-up on the promised proposal for {row['material']}.")


def current(con, chase, clock, *, claim=None):
    candidate = opportunities(con, clock, claim=claim).get(chase["id"])
    if not candidate:
        return False
    source, _, body = candidate
    return (source["reply_id"] == chase["based_on_reply_id"] and source["id"] == chase["parent_thread_id"]
            and source["address"] == chase["address"] and body == chase["body"])
