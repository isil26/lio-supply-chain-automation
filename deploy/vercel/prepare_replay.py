"""Evaluate the two states of a supplier drop in an isolated local replay."""
import argparse
import json
import os
import sys
from contextlib import closing, redirect_stdout
from pathlib import Path

from recording import DEFAULT_RECORDING, load_recording
from src.orchestrator.__main__ import Loop, connect, dashboard


MAIL_ARCHIVE = Path(__file__).resolve().parents[2] / "docs" / "supplier-email-archive"
MAIL_ARCHIVE_TIME = "2026-11-21T20:44:02+01:00"  # Gmail snapshot time in docs/supplier-email-archive/README.md


def mail_archive():
    """Read-only copy of the team Gmail supplier threads, shown as the Verified team mailbox."""
    threads = []
    for path in sorted(MAIL_ARCHIVE.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        messages = []
        for index, item in enumerate(raw.get("messages", []), 1):
            outbound = item.get("direction") == "outbound"
            messages.append({
                "id": index, "side": "out" if outbound else "in",
                "sender": "Soony procurement" if outbound else raw.get("supplier", "Supplier"),
                "text": item.get("body") or "", "time": item.get("date"), "timestamp": item.get("date"),
                "transport": {"from": item.get("from"), "to": item.get("to"), "subject": item.get("subject"),
                              "messageId": item.get("message_id"), "inReplyTo": item.get("in_reply_to"),
                              "mode": "gmail", "status": "gmail_sent" if outbound else "received"},
            })
        if not messages:
            continue
        supplier = raw.get("supplier") or "Supplier"
        threads.append({
            "id": raw.get("thread_id") or path.stem, "supplier": supplier, "material": raw.get("material"),
            "subject": messages[0]["transport"]["subject"] or "",
            "status": "replied" if any(m["side"] == "in" for m in messages) else "sent",
            "initials": "".join(word[0] for word in supplier.split()[:2]), "messages": messages,
        })
    threads.sort(key=lambda thread: thread["messages"][-1]["timestamp"] or "", reverse=True)
    return {"status": "ready", "checkedAt": MAIL_ARCHIVE_TIME, "threads": threads, "actions": []} if threads else None


def view(loop):
    with closing(connect(loop.database)) as con:
        result = dashboard(con)
    if result is None:
        raise RuntimeError("The pipeline did not produce a dashboard")
    result["sync"] = {
        "mode": "hosted-replay",
        "pendingDrop": len(loop.drop_files),
        "lastSync": result["sync"]["time"],
    }
    if loop.drop_files:
        result["drop"] = {
            "title": "Supplier drop ready",
            "detail": f"{len(loop.drop_files)} staged supplier documents are ready to replay.",
            "time": result["sync"]["lastSync"],
        }
    else:
        result["drop"].pop("changes", None)
    # Keep the feed useful and the hosted payload small. The React UI shows only eight rows.
    result["activity"] = result["activity"][:8]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    args = parser.parse_args()
    args.data = args.data.resolve(strict=True)
    args.demo, args.online, args.once = True, False, True
    recording_path = os.environ.get("SOONY_AGENT_RECORDING_FILE")
    recording = load_recording(Path(recording_path)) if recording_path else (
        load_recording(DEFAULT_RECORDING) if DEFAULT_RECORDING.is_file() else None
    )
    with redirect_stdout(sys.stderr):
        loop = Loop(args)
        if not loop.drop_files:
            raise RuntimeError("The snapshot contains no staged supplier documents")
        loop.cycle(sync=False)
        before = view(loop)
        loop.promote_drop()
        loop.cycle(sync=False)
        after = view(loop)
    archive = mail_archive()
    for phase in (before, after):
        phase["recordedAgentRun"] = recording
        if archive:
            phase["mailHistory"] = archive
    baseline = {risk["id"]: risk["gap"] for risk in before["risks"]}
    updated = {risk["id"]: risk["gap"] for risk in after["risks"]}
    if baseline == updated:
        raise RuntimeError("The supplier drop did not change any component shortfalls")
    json.dump({"before": before, "after": after}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
