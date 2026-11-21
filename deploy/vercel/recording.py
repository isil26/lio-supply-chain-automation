"""Project the approved art-book provenance manifest into the encrypted hosted replay."""

from datetime import datetime
from hashlib import sha256
import json
import math
from pathlib import Path, PurePosixPath
import re

REPO = Path(__file__).resolve().parents[2]
DEFAULT_RECORDING = REPO / "docs/agent_runs/provenance/art-book-live.json"
SUMMARY_SOURCES = {"published_summary", "published_summary_notes"}
EVENT_SOURCES = {"original_trace", "redacted_trace_export"}
SECRET = re.compile(r"\b(?:sk-[\w-]{16,}|gh[pousr]_[\w]{16,}|bearer\s+[\w.\-]{16,})\b", re.I)


def text(value, limit=280):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > limit or SECRET.search(value):
        raise ValueError("Invalid or unredacted recording text")
    return value


def required(value, limit=280):
    result = text(value, limit)
    if result is None:
        raise ValueError("Missing required recording text")
    return result


def repo_path(value):
    path = PurePosixPath(required(value))
    if path.is_absolute() or not path.parts or ".." in path.parts or ":" in str(path) or "\\" in str(path):
        raise ValueError("Recording references must be repository-relative paths")
    return path.as_posix()


def number(value, *, integer=False):
    if value is None:
        return None
    if type(value) not in ({int} if integer else {float, int}) or not math.isfinite(value) or value < 0:
        raise ValueError("Invalid recording metric")
    return value


def flag(value):
    if value is not None and type(value) is not bool:
        raise ValueError("Invalid recorded approval or send flag")
    return value


def timestamp(value):
    if value is not None and datetime.fromisoformat(required(value, 64)).tzinfo is None:
        raise ValueError("Recorded timestamps require a timezone")
    return value


def usage(data):
    return {"cost_usd": number(data.get("cost_usd")), "input_tokens": number(data.get("input_tokens"), integer=True),
            "output_tokens": number(data.get("output_tokens"), integer=True)}


def source(item):
    path, revision, digest = repo_path(item["path"]), item["revision"], item["sha256"]
    if not re.fullmatch(r"[a-f0-9]{40}", revision) or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Recording sources must pin a revision and content hash")
    if item["kind"] in SUMMARY_SOURCES and sha256((REPO / path).read_bytes()).hexdigest() != digest:
        raise ValueError("Published recording source differs from its pinned digest")
    return {"path": path, "revision": revision, "sha256": digest}


def event(item, kind):
    sequence = number(item["sequence"], integer=True)
    tool = required(item.get("tool"), 80) if kind == "tool" else None
    status = required(item.get("status"), 40)
    if not sequence or status in {"proposed", "planned"} or tool == "recorded_run":
        raise ValueError("Only ordered operational events may enter the replay")
    citations = [{"file": repo_path(cite["file"]), "page": number(cite.get("page"), integer=True),
                  "row": number(cite.get("row"), integer=True), "quote": text(cite.get("quote"), 450)}
                 for cite in item.get("citations", [])]
    return {"sequence": sequence, "kind": kind, "agent": required(item.get("agent"), 80), "tool": tool,
            "target": required(item.get("target"), 80) if kind == "handoff" else None, "status": status,
            "summary": text(item.get("summary")), "recorded_at": timestamp(item.get("recorded_at")),
            "latency_ms": number(item.get("latency_ms")), "cost_usd": number(item.get("cost_usd")),
            "citations": citations}


def load_recording(path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    coverage = raw.get("coverage")
    if raw.get("schema_version") != 1 or raw.get("scenario") != "art_book" or coverage not in {"summary_only", "verified_events"}:
        raise ValueError("Unsupported art-book recording manifest")
    verified = coverage == "verified_events"
    summary = raw["reported_summary"]
    if summary.get("source") != "published_summary" or summary.get("mode") != "live":
        raise ValueError("The recording requires the published live-run summary")
    sources = [source(item) for item in raw["sources"] if item["kind"] in SUMMARY_SOURCES | EVENT_SOURCES]
    kinds = {item["kind"] for item in raw["sources"]}
    if "published_summary" not in kinds or (verified and not kinds.intersection(EVENT_SOURCES)):
        raise ValueError("Required recording provenance is missing")

    events = []
    approvals = None
    run_id = None
    timing = {}
    verified_usage = None
    if verified:
        run_id = required(raw.get("run_id"), 80)
        timing = raw.get("timing", {})
        events = [event(item, "tool") for item in raw["steps"]]
        events += [event(item, "handoff") for item in raw["verified_handoffs"]]
        if not events or len({item["sequence"] for item in events}) != len(events) or raw["verified_event_count"] != len(events):
            raise ValueError("Verified recording event sequence is incomplete or ambiguous")
        events.sort(key=lambda item: item["sequence"])
        if raw.get("approvals_verified") is True:
            approvals = [{"id": required(item.get("id"), 80), "title": required(item.get("title")),
                          "detail": text(item.get("detail"))} for item in raw["approvals_pending"]]
        if raw.get("verified_usage") is not None:
            verified_usage = usage(raw["verified_usage"])
    elif raw.get("verified_event_count") != 0 or raw.get("steps") or raw.get("verified_handoffs"):
        raise ValueError("A summary-only manifest cannot include verified events")

    return {
        "coverage": coverage, "scenario": "art_book", "run_id": run_id,
        "timing": {"started_at": timestamp(timing.get("started_at")), "finished_at": timestamp(timing.get("finished_at")),
                   "duration_ms": number(timing.get("duration_ms"))},
        "reported_summary": {
            "model": text(summary.get("model"), 80), "aggregate_usage": usage(summary.get("aggregate_usage", {})),
            "roles": [{"role": required(item.get("role"), 80), "reported_status": required(item.get("reported_status"), 80)}
                      for item in summary.get("roles", [])],
            "delegation_targets": [required(target, 80) for target in summary.get("delegation_targets", [])],
            "pending_approvals_reported": flag(summary.get("pending_approvals_reported")),
            "supplier_email_sent_reported": flag(summary.get("supplier_email_sent_reported")),
        },
        "verified_usage": verified_usage, "events": events, "approvals_pending": approvals, "sources": sources,
    }
