"""CLI for the Supplier Chaser agent."""

import argparse
import json
from datetime import datetime
from pathlib import Path

from .agent import SupplierChaser
from .models import Issue
from .store import ChaserStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python3 -m src.chaser.run")
    parser.add_argument("--store", default=None, help="SQLite path; defaults to store/chaser.sqlite")
    parser.add_argument("--data-root", default=None, help="Data root; defaults to data/")
    sub = parser.add_subparsers(dest="command", required=True)

    draft = sub.add_parser("draft", help="Create a supplier thread in pending state")
    draft.add_argument("--supplier-id", required=True)
    draft.add_argument("--component", required=True)
    draft.add_argument("--po", required=True)
    draft.add_argument("--need", required=True, dest="what_we_need")
    draft.add_argument("--deadline", default="2026-11-22T20:00:00+01:00")
    draft.add_argument("--tone", choices=["reminder", "r1_document", "firm_request", "phone_call", "plan_b"])
    draft.add_argument("--max-price-premium-pct", type=float, default=0.0)
    draft.add_argument("--proposed-price-premium-pct", type=float, default=0.0)

    approve = sub.add_parser("approve", help="Approve a pending thread")
    approve.add_argument("thread_id")

    send = sub.add_parser("send", help="Send an approved thread")
    send.add_argument("thread_id")
    send.add_argument("--mode", choices=["dry-run", "mock", "smtp"], default="dry-run")

    reply = sub.add_parser("reply", help="Parse and persist an inbound supplier reply")
    reply.add_argument("thread_id")
    reply.add_argument("text")

    mock = sub.add_parser("mock-reply", help="Add a supplier reply to the mock inbox")
    mock.add_argument("thread_id")
    mock.add_argument("text")

    sub.add_parser("list", help="List supplier threads")
    log = sub.add_parser("log", help="Show action log")
    log.add_argument("--thread-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = ChaserStore(args.store) if args.store else ChaserStore()
    data_root = Path(args.data_root) if args.data_root else None
    chaser = SupplierChaser(store=store, data_root=data_root)

    if args.command == "draft":
        issue = Issue.from_dict({
            "supplier_id": args.supplier_id,
            "component": args.component,
            "PO": args.po,
            "what_we_need": args.what_we_need,
            "deadline": datetime.fromisoformat(args.deadline),
            "max_price_premium_pct": args.max_price_premium_pct,
            "proposed_price_premium_pct": args.proposed_price_premium_pct,
        })
        print(json.dumps(chaser.draft(issue, args.tone), ensure_ascii=False, indent=2))
    elif args.command == "approve":
        print(json.dumps(chaser.approve(args.thread_id), ensure_ascii=False, indent=2))
    elif args.command == "send":
        print(json.dumps(chaser.send(args.thread_id, args.mode), ensure_ascii=False, indent=2))
    elif args.command == "reply":
        print(json.dumps(chaser.parse_reply(args.thread_id, args.text), ensure_ascii=False, indent=2))
    elif args.command == "mock-reply":
        thread = store.get_thread(args.thread_id)
        if not thread:
            raise ValueError(f"unknown thread: {args.thread_id}")
        inbox_id = chaser.inbox.add_reply(
            thread_id=args.thread_id,
            supplier_email=thread["supplier_email"],
            text=args.text,
        )
        parsed = chaser.parse_reply(args.thread_id, args.text)
        print(json.dumps({"inbox_id": inbox_id, "parsed": parsed}, ensure_ascii=False, indent=2))
    elif args.command == "list":
        print(json.dumps(store.list_threads(), ensure_ascii=False, indent=2))
    elif args.command == "log":
        print(json.dumps(store.action_log(args.thread_id), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
