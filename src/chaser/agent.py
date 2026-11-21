import os
import uuid
from datetime import datetime, timezone

from .guardrails import Guardrails
from .llm import DeterministicFakeLLM, LLMClient, LLMReplyParser
from src.llm.client import LLMClient as SharedLLMClient
from .models import Issue, ReplyParse, Supplier
from .outbox import DryRunOutbox, MockOutbox, Outbox, SMTPOutbox
from .store import ChaserStore
from .supplier import load_supplier
from .inbox import MockSupplierInbox


TONE_ORDER = ("reminder", "r1_document", "firm_request", "phone_call", "plan_b")


TEMPLATES = {
    "en": {
        "subject": "Launch deadline confirmation: {component} / PO {po}",
        "reminder": "Dear {contact_name},\n\nPlease confirm the latest status and ETA for {component} under PO {po}. We need {what_we_need} before {deadline}. Please reply with the confirmed quantity and ETA.\n\nIf a call is needed, our team can schedule one promptly.\n\nRegards,\nSoony Launch Team",
        "r1_document": "Dear {contact_name},\n\nPlease provide a firm written confirmation for {component} under PO {po} by the next working hour. State the quantity that is physically complete for each lot and provide the packing list or booking reference, with carrier and booking number where available. Contractual delivery date: {deadline}. Please do not send an ETA-only update.\n\nRegards,\nSoony Launch Team",
        "firm_request": "Dear {contact_name},\n\nThis is a firm request for an immediate written update on {component} under PO {po}. We need {what_we_need} before {deadline}. Please confirm the quantity you can deliver and the earliest realistic ETA by the next working hour.\n\nRegards,\nSoony Launch Team",
        "phone_call": "Dear {contact_name},\n\nPlease arrange an immediate phone call with the Soony launch team to resolve {component} under PO {po}. We need {what_we_need} before {deadline}. Please confirm the available quantity and ETA during the call.\n\nRegards,\nSoony Launch Team",
        "plan_b": "Dear {contact_name},\n\nWe are escalating {component} under PO {po} to Plan B because the deadline of {deadline} cannot be met without a confirmed recovery. Please provide a final quantity and ETA immediately.\n\nRegards,\nSoony Launch Team",
    },
    "ko": {
        "subject": "출하 마감 확인 요청: {component} / PO {po}",
        "reminder": "{contact_name}님께,\n\nPO {po}의 {component}에 대한 최신 상태와 ETA를 확인해 주시기 바랍니다. {what_we_need}을(를) {deadline} 이전에 확보해야 합니다. 확인된 수량과 ETA를 회신해 주세요.\n\n긴급 통화가 필요하면 즉시 일정 조율하겠습니다.\n\nSoony Launch Team",
        "r1_document": "{contact_name}님께,\n\n다음 업무 시간까지 PO {po}의 {component}에 대해 서면 확정 회신을 요청드립니다. 각 로트별로 실제 완성 수량을 명시하고 가능하면 운송업체와 예약 번호가 포함된 패킹리스트 또는 예약번호를 제공해 주세요. 계약 낙품일: {deadline}. ETA만 회신하지 말고 위 증빙을 함께 보내 주십시오.\n\nSoony Launch Team",
        "firm_request": "{contact_name}님께,\n\nPO {po}의 {component}에 대해 즉시 서면 답변을 요청드립니다. {what_we_need}을(를) {deadline} 이전에 확보해야 합니다. 가능한 수량과 가장 빠른 현실적 ETA를 다음 업무 시간 내 회신해 주세요.\n\nSoony Launch Team",
        "phone_call": "{contact_name}님께,\n\nPO {po}의 {component} 관련 문제를 해결하기 위해 즉시 전화 통화를 요청드립니다. {what_we_need}을(를) {deadline} 이전에 확보해야 합니다.\n\nSoony Launch Team",
        "plan_b": "{contact_name}님께,\n\n확정된 회복 계획이 없어 PO {po}의 {component}를 Plan B로 이관합니다. 마감은 {deadline}입니다. 최종 수량과 ETA를 즉시 알려 주세요.\n\nSoony Launch Team",
    },
    "zh": {
        "subject": "发货截止确认：{component} / PO {po}",
        "reminder": "{contact_name}，\n\n请确认 PO {po} 下 {component} 的最新状态和预计到货时间。我们需要在 {deadline} 前完成：{what_we_need}。请回复确认数量和 ETA。\n\n如需电话沟通，我们可以立即安排。\n\nSoony Launch Team",
        "r1_document": "{contact_name}，\n\n请在下一个工作小时内提供 PO {po} 下 {component} 的书面确认。请逐批说明实际完成数量，并提供装箱单或订舱编号；如有，请同时提供承运人与订舱号。合同交付日期：{deadline}。请勿仅回复 ETA，请附上可核验的文件或订舱信息。\n\nSoony Launch Team",
        "firm_request": "{contact_name}，\n\n现紧急书面要求更新 PO {po} 下 {component} 的状态。我们需要在 {deadline} 前完成：{what_we_need}。请在下一个工作小时内确认可供数量及最早可行 ETA。\n\nSoony Launch Team",
        "phone_call": "{contact_name}，\n\n请立即安排电话，与 Soony launch team 共同处理 PO {po} 下的 {component}。截止时间为 {deadline}。通话中请确认可供数量和 ETA。\n\nSoony Launch Team",
        "plan_b": "{contact_name}，\n\n由于无法在 {deadline} 前获得确认的恢复方案，PO {po} 下的 {component} 已升级到 Plan B。请立即提供最终数量和 ETA。\n\nSoony Launch Team",
    },
    "pl": {
        "subject": "Potwierdzenie terminu wysyłki: {component} / PO {po}",
        "reminder": "Dzień dobry, {contact_name},\n\nProszę o potwierdzenie aktualnego statusu i ETA dla {component} w ramach PO {po}. Potrzebujemy {what_we_need} przed {deadline}. Proszę o ilość i potwierdzony termin.\n\nJeśli potrzebna będzie rozmowa, możemy ją natychmiast umówić.\n\nPozdrawiam,\nSoony Launch Team",
        "r1_document": "Dzień dobry, {contact_name},\n\nProszę do najbliższej godziny roboczej o pisemne potwierdzenie dla {component} z PO {po}. Proszę podać ilość fizycznie ukończoną dla każdej partii oraz dostarczyć packing list lub numer rezerwacji, wraz z przewoźnikiem i numerem rezerwacji, jeśli są dostępne. Data dostawy wynikająca z umowy: {deadline}. Proszę nie wysyłać samego ETA, lecz załącz dokument lub referencję rezerwacji.\n\nPozdrawiam,\nSoony Launch Team",
        "firm_request": "Dzień dobry, {contact_name},\n\nTo pilna prośba o natychmiastową pisemną aktualizację {component} w ramach PO {po}. Potrzebujemy {what_we_need} przed {deadline}. Proszę potwierdzić ilość i najwcześniejszy realistyczny ETA w ciągu najbliższej godziny roboczej.\n\nPozdrawiam,\nSoony Launch Team",
        "phone_call": "Dzień dobry, {contact_name},\n\nProszę o natychmiastową rozmowę telefoniczną z zespołem launch Soony w sprawie {component} w ramach PO {po}. Potrzebujemy {what_we_need} przed {deadline}. Podczas rozmowy proszę potwierdzić ilość i ETA.\n\nPozdrawiam,\nSoony Launch Team",
        "plan_b": "Dzień dobry, {contact_name},\n\nEskaluje {component} z PO {po} do Plan B, ponieważ bez potwierdzonego planu odzyskania termin {deadline} nie może zostać spełniony. Proszę natychmiast podać ilość i ETA.\n\nPozdrawiam,\nSoony Launch Team",
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def tone_for_state(sent_count: int = 0, human_requested: bool = False) -> str:
    if human_requested:
        return "plan_b"
    if sent_count <= 0:
        return "reminder"
    if sent_count == 1:
        return "r1_document"
    if sent_count == 2:
        return "phone_call"
    return "plan_b"


def next_step(thread: dict) -> dict:
    """Choose the next escalation rung and preserve the decision in the store."""
    status = str(thread.get("status") or "").lower()
    score = int(thread.get("commitment_score") or 0)
    needs_human = bool(thread.get("needs_human"))
    sent_count = int(thread.get("sent_count") or 0)
    current = str(thread.get("escalation_rung") or "R0").upper()
    rung_rank = {"R0": 0, "R1": 1, "R2": 2, "R3": 3, "R4": 4}
    rank = rung_rank.get(current, 0)

    if current == "R0" and not status and score == 0 and sent_count == 0:
        action = "R0 probe: collect a quantity and ETA baseline."
    elif status in {"blocked", "cancelled"}:
        rank = 4
        action = "Activate Plan B and route PP-07 approval."
    elif score >= 3:
        action = "Stop the ladder; verify the document or booking reference."
        rank = max(rank, 1)
    elif needs_human:
        rank = max(rank, 3)
        action = "Prepare call facts and route to a human for R3 voice escalation."
    elif score == 2:
        rank = max(rank, 1)
        action = "Ask R1 for a packing list or booking reference."
    elif score == 1:
        rank = max(rank, 1)
        action = "Request a per-lot quantity and verifiable reference."
    elif sent_count >= 3:
        rank = max(rank, 3)
        action = "Silence requires R3 human voice escalation."
    else:
        rank = max(rank, 1)
        action = "Send R1 document request."

    return {"rung": f"R{rank}", "action": action}


class SupplierChaser:
    def __init__(
        self,
        store: ChaserStore,
        data_root=None,
        llm: LLMClient | None = None,
        guardrails: Guardrails | None = None,
        outbox: Outbox | None = None,
    ):
        self.store = store
        self.data_root = data_root
        if llm is not None:
            self.llm = llm
        else:
            shared = SharedLLMClient()
            self.llm = LLMReplyParser(shared) if shared.configured() else DeterministicFakeLLM()
        self.guardrails = guardrails or Guardrails()
        self.inbox = MockSupplierInbox(store)
        self.outbox = outbox

    def draft(self, issue: Issue, tone: str | None = None) -> dict:
        issue_result = self.guardrails.validate_issue(issue)
        if not issue_result.ok:
            raise ValueError("; ".join(issue_result.errors))
        supplier = load_supplier(issue.supplier_id, self.data_root)
        chosen_tone = tone or tone_for_state()
        if chosen_tone not in TONE_ORDER:
            raise ValueError(f"unknown tone: {chosen_tone}")
        templates = TEMPLATES[supplier.preferred_language]
        deadline = issue.deadline.isoformat()
        values = {
            "contact_name": supplier.contact_name or supplier.name,
            "component": issue.component,
            "po": issue.po,
            "what_we_need": issue.what_we_need,
            "deadline": deadline,
        }
        subject = templates["subject"].format(**values)
        body = templates[chosen_tone].format(**values)
        draft_result = self.guardrails.validate_draft(body)
        if not draft_result.ok:
            raise ValueError("; ".join(draft_result.errors))

        thread_id = str(uuid.uuid4())
        at = now_iso()
        payload = {
            "thread_id": thread_id,
            "supplier_id": supplier.supplier_id,
            "supplier_name": supplier.name,
            "supplier_email": supplier.contact_email,
            "component": issue.component,
            "po": issue.po,
            "what_we_need": issue.what_we_need,
            "deadline": deadline,
            "language": supplier.preferred_language,
            "tone": chosen_tone,
            "subject": subject,
            "body": body,
            "state": "pending",
            "created_at": at,
            "updated_at": at,
        }
        self.store.create_thread(payload)
        initial_step = next_step({
            "escalation_rung": "R0",
            "sent_count": 0,
            "status": None,
            "commitment_score": 0,
            "needs_human": False,
        })
        self.store.set_escalation(thread_id, initial_step["rung"], initial_step["action"], at)
        self.store.add_message({
            "message_id": str(uuid.uuid4()),
            "thread_id": thread_id,
            "direction": "outbound_draft",
            "sender": "",
            "recipient": supplier.contact_email,
            "subject": subject,
            "body": body,
            "created_at": at,
        })
        self.store.log(thread_id, "draft_created", {
            "supplier_id": supplier.supplier_id,
            "language": supplier.preferred_language,
            "tone": chosen_tone,
            "state": "pending",
        }, at)
        return payload

    def approve(self, thread_id: str) -> dict:
        thread = self.store.get_thread(thread_id)
        if not thread:
            raise ValueError(f"unknown thread: {thread_id}")
        at = now_iso()
        self.store.set_thread_state(thread_id, "approved", at)
        self.store.log(thread_id, "approved", {"state": "approved"}, at)
        thread["state"] = "approved"
        thread["updated_at"] = at
        return thread

    def send(self, thread_id: str, mode: str = "dry-run") -> dict:
        thread = self.store.get_thread(thread_id)
        if not thread:
            raise ValueError(f"unknown thread: {thread_id}")
        if thread["state"] != "approved":
            raise PermissionError("thread must be approved before sending")
        draft_result = self.guardrails.validate_draft(thread["body"])
        if not draft_result.ok:
            raise ValueError("draft failed send guardrail: " + "; ".join(draft_result.errors))

        sender = os.environ.get("CHASER_SENDER")
        if not sender:
            raise RuntimeError("CHASER_SENDER is required")

        if mode == "dry-run":
            outbox = DryRunOutbox()
        elif mode == "mock":
            outbox = MockOutbox(self.inbox)
        elif mode == "smtp":
            if os.environ.get("CHASER_REAL_SMTP") != "1":
                raise PermissionError("real SMTP requires CHASER_REAL_SMTP=1")
            outbox = SMTPOutbox()
        else:
            raise ValueError("mode must be dry-run, mock, or smtp")

        result = outbox.send(
            thread_id=thread_id,
            sender=sender,
            recipient=thread["supplier_email"],
            subject=thread["subject"],
            body=thread["body"],
        )
        at = now_iso()
        self.store.add_message({
            "message_id": str(uuid.uuid4()),
            "thread_id": thread_id,
            "direction": "outbound",
            "sender": sender,
            "recipient": thread["supplier_email"],
            "subject": thread["subject"],
            "body": thread["body"],
            "created_at": at,
        })
        self.store.log(thread_id, "send_attempt", result, at)
        if result["sent"]:
            self.store.set_thread_state(thread_id, "sent", at)
            result["state"] = "sent"
        else:
            result["state"] = "approved"
        return result

    def parse_reply(self, thread_id: str, text: str) -> dict:
        thread = self.store.get_thread(thread_id)
        if not thread:
            raise ValueError(f"unknown thread: {thread_id}")
        parsed = self.llm.parse_reply(text)
        at = now_iso()
        reply_id = str(uuid.uuid4())
        self.store.add_reply({
            "reply_id": reply_id,
            "thread_id": thread_id,
            "raw_text": text,
            "status": parsed.status,
            "new_eta": parsed.new_eta,
            "quantity": parsed.quantity,
            "confidence": parsed.confidence,
            "needs_human": int(parsed.needs_human),
            "commitment_strength": parsed.commitment_strength,
            "commitment_score": parsed.commitment_score,
            "what_to_ask_next": parsed.what_to_ask_next,
            "created_at": at,
        })
        self.store.log(thread_id, "reply_parsed", {
            "status": parsed.status,
            "new_eta": parsed.new_eta,
            "quantity": parsed.quantity,
            "confidence": parsed.confidence,
            "needs_human": parsed.needs_human,
            "commitment_strength": parsed.commitment_strength,
            "commitment_score": parsed.commitment_score,
            "what_to_ask_next": parsed.what_to_ask_next,
        }, at)
        thread["status"] = parsed.status
        thread["commitment_score"] = parsed.commitment_score
        thread["needs_human"] = parsed.needs_human
        escalation = self.store.get_escalation(thread_id)
        if escalation:
            thread["escalation_rung"] = escalation["rung"]
        step = next_step(thread)
        self.store.set_escalation(thread_id, step["rung"], step["action"], at)
        self.store.log(thread_id, "escalation_state", step, at)
        if parsed.needs_human:
            self.store.log(thread_id, "escalation_recommended", {
                "tone": "plan_b",
                "reason": "supplier reply requires human review",
                "next_step": step,
            }, at)
        return {
            "status": parsed.status,
            "new_eta": parsed.new_eta,
            "quantity": parsed.quantity,
            "confidence": parsed.confidence,
            "needs_human": parsed.needs_human,
            "commitment_strength": parsed.commitment_strength,
            "commitment_score": parsed.commitment_score,
            "what_to_ask_next": parsed.what_to_ask_next,
            "next_step": step,
        }
