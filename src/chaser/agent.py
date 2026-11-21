import os
import uuid
from datetime import datetime, timezone

from .guardrails import Guardrails
from .llm import DeterministicFakeLLM, LLMClient
from .models import Issue, ReplyParse, Supplier
from .outbox import DryRunOutbox, MockOutbox, Outbox, SMTPOutbox
from .store import ChaserStore
from .supplier import load_supplier
from .inbox import MockSupplierInbox


TONE_ORDER = ("reminder", "firm_request", "phone_call", "plan_b")


TEMPLATES = {
    "en": {
        "subject": "Launch deadline confirmation: {component} / PO {po}",
        "reminder": "Dear {contact_name},\n\nPlease confirm the latest status and ETA for {component} under PO {po}. We need {what_we_need} before {deadline}. Please reply with the confirmed quantity and ETA.\n\nIf a call is needed, our team can schedule one promptly.\n\nRegards,\nSoony Launch Team",
        "firm_request": "Dear {contact_name},\n\nThis is a firm request for an immediate written update on {component} under PO {po}. We need {what_we_need} before {deadline}. Please confirm the quantity you can deliver and the earliest realistic ETA by the next working hour.\n\nRegards,\nSoony Launch Team",
        "phone_call": "Dear {contact_name},\n\nPlease arrange an immediate phone call with the Soony launch team to resolve {component} under PO {po}. We need {what_we_need} before {deadline}. Please confirm the available quantity and ETA during the call.\n\nRegards,\nSoony Launch Team",
        "plan_b": "Dear {contact_name},\n\nWe are escalating {component} under PO {po} to Plan B because the deadline of {deadline} cannot be met without a confirmed recovery. Please provide a final quantity and ETA immediately.\n\nRegards,\nSoony Launch Team",
    },
    "ko": {
        "subject": "출하 마감 확인 요청: {component} / PO {po}",
        "reminder": "{contact_name}님께,\n\nPO {po}의 {component}에 대한 최신 상태와 ETA를 확인해 주시기 바랍니다. {what_we_need}을(를) {deadline} 이전에 확보해야 합니다. 확인된 수량과 ETA를 회신해 주세요.\n\n긴급 통화가 필요하면 즉시 일정 조율하겠습니다.\n\nSoony Launch Team",
        "firm_request": "{contact_name}님께,\n\nPO {po}의 {component}에 대해 즉시 서면 답변을 요청드립니다. {what_we_need}을(를) {deadline} 이전에 확보해야 합니다. 가능한 수량과 가장 빠른 현실적 ETA를 다음 업무 시간 내 회신해 주세요.\n\nSoony Launch Team",
        "phone_call": "{contact_name}님께,\n\nPO {po}의 {component} 관련 문제를 해결하기 위해 즉시 전화 통화를 요청드립니다. {what_we_need}을(를) {deadline} 이전에 확보해야 합니다.\n\nSoony Launch Team",
        "plan_b": "{contact_name}님께,\n\n확정된 회복 계획이 없어 PO {po}의 {component}를 Plan B로 이관합니다. 마감은 {deadline}입니다. 최종 수량과 ETA를 즉시 알려 주세요.\n\nSoony Launch Team",
    },
    "zh": {
        "subject": "发货截止确认：{component} / PO {po}",
        "reminder": "{contact_name}，\n\n请确认 PO {po} 下 {component} 的最新状态和预计到货时间。我们需要在 {deadline} 前完成：{what_we_need}。请回复确认数量和 ETA。\n\n如需电话沟通，我们可以立即安排。\n\nSoony Launch Team",
        "firm_request": "{contact_name}，\n\n现紧急书面要求更新 PO {po} 下 {component} 的状态。我们需要在 {deadline} 前完成：{what_we_need}。请在下一个工作小时内确认可供数量及最早可行 ETA。\n\nSoony Launch Team",
        "phone_call": "{contact_name}，\n\n请立即安排电话，与 Soony launch team 共同处理 PO {po} 下的 {component}。截止时间为 {deadline}。通话中请确认可供数量和 ETA。\n\nSoony Launch Team",
        "plan_b": "{contact_name}，\n\n由于无法在 {deadline} 前获得确认的恢复方案，PO {po} 下的 {component} 已升级到 Plan B。请立即提供最终数量和 ETA。\n\nSoony Launch Team",
    },
    "pl": {
        "subject": "Potwierdzenie terminu wysyłki: {component} / PO {po}",
        "reminder": "Dzień dobry, {contact_name},\n\nProszę o potwierdzenie aktualnego statusu i ETA dla {component} w ramach PO {po}. Potrzebujemy {what_we_need} przed {deadline}. Proszę o ilość i potwierdzony termin.\n\nJeśli potrzebna będzie rozmowa, możemy ją natychmiast umówić.\n\nPozdrawiam,\nSoony Launch Team",
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
        return "firm_request"
    if sent_count == 2:
        return "phone_call"
    return "plan_b"


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
        self.llm = llm or DeterministicFakeLLM()
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
            "created_at": at,
        })
        self.store.log(thread_id, "reply_parsed", {
            "status": parsed.status,
            "new_eta": parsed.new_eta,
            "quantity": parsed.quantity,
            "confidence": parsed.confidence,
            "needs_human": parsed.needs_human,
        }, at)
        if parsed.needs_human:
            self.store.log(thread_id, "escalation_recommended", {
                "tone": "plan_b",
                "reason": "supplier reply requires human review",
            }, at)
        return {
            "status": parsed.status,
            "new_eta": parsed.new_eta,
            "quantity": parsed.quantity,
            "confidence": parsed.confidence,
            "needs_human": parsed.needs_human,
        }
