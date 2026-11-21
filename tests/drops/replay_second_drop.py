"""Run the three synthetic second-drop fixtures in a disposable offline replay."""

import csv
from contextlib import closing
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).with_name("synthetic")
SHIPMENTS = "soony/erp/open_shipments.csv"
AIR_LOT = "SHP-2026-04311"


def stage(loop, folder):
    targets = {
        "pune-ppap.txt": "SUP-0018_Pune_Diecast_Works",
        "dongguan-cny.txt": "SUP-0019_Dongguan_Precision_Housings",
        "hwaseong-delay.txt": "SUP-0010_Hwaseong_Memory",
    }
    for name, supplier in targets.items():
        source = FIXTURES / name
        dest = loop.root / "suppliers" / supplier / "notices" / f"synthetic-{name}"
        loop.drop_files.append((source, dest))
    shipments = loop.root / SHIPMENTS
    with shipments.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        rows, columns = list(reader), reader.fieldnames
    [air] = [row for row in rows if row["shipment_id"] == AIR_LOT]
    air.update(eta="2026-11-23", status="delayed", updated_at="2026-11-21T22:30:00+01:00",
               note=f"SYNTHETIC REPLAY FIXTURE: see synthetic-hwaseong-delay.txt. {air['note']}")
    replacement = folder / shipments.name
    with replacement.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    loop.drop_files.append((replacement, shipments))


def view(loop):
    from src.docs import documents
    from src.ingest.store import connect, get_state

    with closing(connect(loop.database)) as con:
        truth = get_state(con, "truth")
        drop = get_state(con, "drop")
        notices = [doc for doc in documents(con) if Path(doc["source"]).name.startswith("synthetic-")]
    return {
        "editions": {key: item["p50"] for key, item in truth["editions"].items()},
        "card_gap": truth["parts"]["CMP-GAM-001"]["shortfall"],
        "statue_hold": [issue["quantity"] for issue in truth["issues"]
                        if issue["kind"] == "quality_hold" and issue["material"] == "CMP-GAM-010"],
        "sources_changed": [event["file"] for event in drop["changes"]],
        "notices": {Path(doc["source"]).name: {key: [row["value"] for row in doc["fields"][key]]
                                              for key in ("what", "downtime") if key in doc["fields"]}
                    for doc in notices},
    }


def main():
    for name in list(os.environ):
        if name.startswith(("CHASER_", "SOONY_LLM_", "SOONY_IMAP_", "SOONY_LOCAL_", "SOONY_VISION_")):
            del os.environ[name]
    os.environ.update(CHASER_REAL_SMTP="0", CHASER_NO_TEAM_MAIL="1", SOONY_LLM_PROVIDER="none", SOONY_AGENTS="0")

    from src.orchestrator.__main__ import Loop

    with TemporaryDirectory(prefix="soony-synthetic-replay-") as temp:
        folder = Path(temp)
        args = SimpleNamespace(data=ROOT / "case-data", demo=True, online=False, once=True,
                               replay_dir=folder / "replay")
        loop = Loop(args)
        loop.cycle()
        loop.promote_drop()
        loop.cycle()
        before = view(loop)
        stage(loop, folder)
        loop.promote_drop()
        loop.cycle()
        after = view(loop)
    if (after["notices"].keys() != {f"synthetic-{file.name}" for file in FIXTURES.glob("*.txt")}
            or not after["notices"]["synthetic-dongguan-cny.txt"].get("downtime")
            or after["statue_hold"] != before["statue_hold"]
            or after["card_gap"] <= before["card_gap"]):
        raise RuntimeError("Synthetic replay did not produce the expected notice, hold and card-gap outcomes")
    print(json.dumps({"synthetic": True, "after_first_drop": before, "after_second_drop": after},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
