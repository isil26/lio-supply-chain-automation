"""Route supplier replies to the next responsible party and anchor drafts to their evidence."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .recovery import CANCELLED, CANCEL_NEGATED, RESTORED, WITHDRAWN, unquoted

# Match instructions in the supplier's own reply. A PO number or a price by
# itself does not request authority to change the order or incur the charge.
QUALITY = re.compile(
    r"(?:please (?:send|provide)|we (?:need|require)|subject to|pending|requires?)"
    r"[^.\n]{0,90}?(?:acceptance (?:standard|criteria)|reference (?:photos?|photographs?)|quality (?:release|disposition)|signed concession)"
    r"|(?:wymaga|prosimy o)[^.\n]{0,50}(?:kryteri|zwolnieni.{0,8}jakości)|(?:需|请提供).{0,16}(?:质量放行|验收标准)"
    r"|(?:검사 기준|품질 승인).{0,16}(?:필요|요청)", re.I)
PURCHASE = re.compile(
    r"(?:requires?|subject to|pending|until|upon receipt of|only (?:upon|after)|without|please (?:send|issue|provide))"
    r"[^.\n]{0,65}?(?:written (?:buyer |purchasing |procurement )?(?:release|instruction|authori[sz]ation)|"
    r"(?:formal|signed|amended|revised) (?:purchase order|PO\b)|(?:an? |the |your )purchase order\b)"
    r"|(?:potrzebujemy|wymaga|dopiero po|do czasu|bez)[^.\n]{0,80}(?:pisemn|formaln.{0,6} zamówien)"
    r"|(?:正式采购订单|正式书面订单|采购书面指示)|(?:정식 발주서|구매팀의 서면 승인)", re.I)
FREIGHT = re.compile(
    r"(?:please (?:approve|accept|authori[sz]e|confirm)|subject to (?:your|buyer)|requires? (?:your|written))"
    r"[^.\n]{0,65}(?:freight (?:charge|fee|booking)|surcharge|transport booking|airfreight (?:fee|booking))"
    r"|(?:运费|附加费).{0,12}(?:须经批准|需确认)|(?:추가 운임|운송비).{0,12}(?:승인|확인 요청)"
    r"|(?:prosimy o|wymaga).{0,30}(?:akceptacj|zatwierdz).{0,25}(?:dopłat|fracht)", re.I)
NO_SUPPLY = re.compile(
    r"(?:cannot|can.t|unable to) (?:offer|deliver|supply|commit to delivering) (?:any (?:quantity|units|stock)|anything)\b"
    r"|\b(?:zero|0) (?:units?|pieces|cards|copies|statues|pcs)\b(?:[^.\n]{0,45}(?:available|before|by |for (?:the|this)))?"
    r"|(?:żadnej ilości|无法承诺任何数量|추가 공급 가능 수량은 0)", re.I)
EXPRESS_UNAVAILABLE = re.compile(
    r"\b(?:cannot expedite|cannot (?:offer|arrange) (?:an? )?(?:earlier|expedited) (?:shipment|service)|"
    r"no (?:earlier|expedited|premium) (?:shipment|service|option) (?:is )?(?:possible|available|can))\b"
    r"|brak możliwości (?:przyspieszenia|wcześniejszej dostawy)|无法(?:加急|提前交付)|긴급 운송이 불가능", re.I)
ACKNOWLEDGEMENT = re.compile(
    r"(?:thank(?:s| you)(?: for (?:your|the) (?:message|update|email))?|noted|acknowledged|"
    r"received|dziękuję|谢谢|감사합니다)[.!。\s]*", re.I)

PROMISE = re.compile(
    r"(?:\b(?:I|we|the carrier)(?: will|[’']ll) (?:check|revert|come back|update|confirm|forward|reply|respond|return|provide|send(?= (?:you |over )?(?:the |a |our )?(?:quot(?:e|ation)|proposal|documents?|confirmation|paperwork|details|an update|tracking)))|"
    r"\b(?:I am|we are|we.re|we’re) (?:still )?(?:checking|awaiting|waiting for)|"
    r"still being checked|przekaż[ęe]|potwierdz[ęe] osobno|sprawdz[ęa]|po otrzymaniu odpowiedzi|(?:核实后|确认后).{0,15}(?:回复|通知)|"
    r"확인되는 대로|확인 후.{0,12}(?:회신|전달))", re.I)
ROOT_REF = re.compile(r"[\[(]SOONY-([a-f0-9]+)[\])]", re.I)

# These are responsibilities, not authorizations. The offer review records
# the named reviewer and a separate PO, booking or disposition is still due.
ROUTES = (
    (QUALITY, "approval", "Supplier Quality", "Review the acceptance criteria or written disposition before releasing the lot."),
    (FREIGHT, "approval", "Logistics and Procurement", "Review the quoted freight charge and timed handoff before authorizing a booking."),
    (PURCHASE, "approval", "Procurement", "Review the supplier’s terms and obtain the authorized PO or written release before dispatch."),
    (NO_SUPPLY, "unavailable", "Procurement", "Leave this quantity uncovered and pursue an alternative source or lot."),
    (EXPRESS_UNAVAILABLE, "unavailable", "Procurement", "The supplier ruled out expedited delivery. Check a different route or supplier."),
    (PROMISE, "waiting", "Supplier", "Wait for the promised update. Keep the quantity and transport outside confirmed supply."),
)


def classify(body):
    clean = unquoted("\n".join(line for line in body.splitlines() if not line.lstrip().startswith(">")))
    # A withdrawn quote must not be reopened by a courteous promise to reply.
    routes = ROUTES
    if not RESTORED.search(clean) and not CANCEL_NEGATED.search(clean):
        routes = ((WITHDRAWN, "unavailable", "Procurement", "The supplier withdrew the offer. Recheck alternative supply."),
                  (CANCELLED, "review", "Procurement", "Verify which lot was cancelled and review replacement supply."), *routes)
    for pattern, state, owner, action in routes:
        match = pattern.search(clean)
        if match:
            # Keep the sentence which drove the handoff for the reviewer.
            start = max(clean.rfind(".", 0, match.start()), clean.rfind("\n", 0, match.start())) + 1
            end = re.search(r"[.!?。\n]", clean[match.end():])
            stop = match.end() + end.start() + 1 if end else len(clean)
            return dict(state=state, owner=owner, nextAction=action,
                        evidence=clean[start:stop].strip()[:500])
    return None


def _roots(chases):
    parents = {}
    for item in chases:
        key = item["id"]
        try:
            cutoff = datetime.fromisoformat(item["deadline"].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            cutoff = item["deadline"]
        scope = item["supplier_id"], item["material"], item["address"].casefold(), cutoff
        refs = [item["parent_thread_id"], *reversed(ROOT_REF.findall(item["subject"]))]
        parents[key] = (scope, [ref for ref in refs if ref and ref != key])
    roots = {}
    for key, (scope, _) in parents.items():
        seen = set()
        root = key
        while root not in seen:
            seen.add(root)
            parent = next((ref for ref in parents[root][1] if ref in parents and parents[ref][0] == scope), None)
            if not parent:
                break
            root = parent
        roots[key] = root
    return roots


VERIFIED_SIMULATION = """(coalesce(json_extract(m.transport,'$.mode'),'') IN ('simulated','dry_run')
        OR (m.transport IS NULL AND EXISTS (
            SELECT 1 FROM messages o WHERE o.chase_id=m.chase_id AND o.side='out'
              AND (o.sender LIKE '%(demo)' OR json_extract(o.transport,'$.mode')='dry_run'))))"""


def contexts(con, thread_id=None, *, simulated=False):
    """Resolve the latest supplier evidence across retries of the same conversation."""
    where = ""
    args = ()
    if thread_id:
        where = """ WHERE (supplier_id,material) IN
                    (SELECT supplier_id,material FROM chases WHERE id=?)"""
        args = (thread_id,)
    rows = con.execute("SELECT id,subject,supplier_id,material,address,deadline,parent_thread_id FROM chases" + where, args)
    columns = [d[0] for d in rows.description]
    roots = _roots(dict(zip(columns, row)) for row in rows)
    if not roots:
        return {}
    # Old demo rows can predate transport metadata; their outbound mail still
    # carries the demo sender or dry-run envelope written by the original worker.
    scope = VERIFIED_SIMULATION if simulated else f"NOT {VERIFIED_SIMULATION}"
    replies = con.execute(f"""
        SELECT m.chase_id,m.id,m.external_id,m.body,coalesce(json_extract(m.transport,'$.authoredAt'),m.time),c.deadline
        FROM messages m JOIN chases c ON c.id=m.chase_id
        WHERE m.side='in' AND {scope}
          AND m.chase_id IN (SELECT id FROM chases {where})
        ORDER BY julianday(coalesce(json_extract(m.transport,'$.authoredAt'),m.time)),m.id""", args)
    # A buyer response owns this revision. Routine counters and generic answers for
    # the same evidence must yield to it, even if they were queued earlier.
    decided = set()
    if not simulated and con.execute("SELECT 1 FROM sqlite_master WHERE name='deal_decision_history'").fetchone():
        decided = {row[0] for row in con.execute("""SELECT m.id FROM deals d JOIN messages m
                    ON m.external_id=d.source_message AND m.chase_id=d.thread_id
                    WHERE d.status IN ('approved','declined')""")}
    if not simulated and con.execute("SELECT 1 FROM sqlite_master WHERE name='deal_requests'").fetchone():
        decided.update(r[0] for r in con.execute("""SELECT c.based_on_reply_id FROM deal_requests r JOIN chases c ON c.id=r.email_id
                    JOIN deals d ON d.id=r.deal_id AND d.revision=r.revision WHERE c.based_on_reply_id IS NOT NULL"""))
    states = {}
    for thread, mid, external, body, at, deadline in replies:
        root = roots[thread]
        if root in states and ACKNOWLEDGEMENT.fullmatch(unquoted(body).strip()):
            continue
        plan = classify(body)
        if plan and plan["state"] == "waiting":
            try:
                from .followup import _aware
                from .promise_watch import checkpoint
                received, due = _aware(at), _aware(deadline)
                # Internal checkpoint; the quoted supplier text is the actual promise.
                check, automatic = checkpoint(unquoted(body), received, due)
                plan.update(checkAt=check.isoformat(), autoCheckpoint=automatic)
            except (ValueError, TypeError):
                pass
        states[root] = dict(replyId=mid, messageId=external, plan=plan, root=root, sourceThread=thread, buyerDecided=mid in decided)
    return {key: states[root] for key, root in roots.items() if root in states}


def blocks_automation(con, thread_id):
    return bool(contexts(con, thread_id).get(thread_id, {}).get("plan"))


def check_draft(con, chase, *, simulated=False):
    """Recheck a generated question inside the dispatch claim transaction."""
    state = contexts(con, chase["id"], simulated=simulated).get(chase["id"])
    if not state:
        return
    if chase["based_on_reply_id"] is None and (chase["parent_thread_id"] or "(SOONY-" in chase["subject"]):
        raise ValueError("The supplier has already answered this reminder.")
    if chase["based_on_reply_id"] is not None and chase["based_on_reply_id"] != state["replyId"]:
        raise ValueError("A newer supplier reply replaced this draft.")
    if state["buyerDecided"]:
        raise ValueError("The buyer already decided this offer. Use the recorded response.")
    if state["plan"]:
        raise ValueError(state["plan"]["nextAction"])


def record_checkpoints(con, states, now=None):
    now = now or datetime.now(timezone.utc)
    for item in {v["root"]: v for v in states.values()}.values():
        plan = item["plan"]
        if not plan:
            continue
        action = plan["nextAction"]
        if plan["state"] == "waiting":
            if not plan.get("checkAt") or datetime.fromisoformat(plan["checkAt"]) > now:
                continue
            action = "A promised supplier update is due for review. Check the thread before following up."
        detail = f"{plan['owner'] if plan['state'] != 'waiting' else 'Procurement'} · SOONY-{item['root']} · reply {item['replyId']}: {action}"
        con.execute("""INSERT INTO activity(time,agent,action,type) SELECT ?, 'Mail Agent', ?, 'warning'
                       WHERE NOT EXISTS (SELECT 1 FROM activity WHERE agent='Mail Agent' AND action=?)""",
                    (now.isoformat(timespec="seconds"), detail, detail))
