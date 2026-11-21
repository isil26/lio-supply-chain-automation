"""Evaluate the two states of a supplier drop in an isolated local replay."""
import argparse
import json
import os
import sys
from contextlib import closing, redirect_stdout
from pathlib import Path

from recording import DEFAULT_RECORDING, load_recording
from src.orchestrator.__main__ import Loop, connect, dashboard


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
    for phase in (before, after):
        phase["recordedAgentRun"] = recording
    baseline = {risk["id"]: risk["gap"] for risk in before["risks"]}
    updated = {risk["id"]: risk["gap"] for risk in after["risks"]}
    if baseline == updated:
        raise RuntimeError("The supplier drop did not change any component shortfalls")
    json.dump({"before": before, "after": after}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
