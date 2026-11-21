"""Check the published default forecast against the offline dashboard."""

from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
QUANTILES = ("p10", "p50", "p90")
# After the 19:25 drop: packed counts from launch_status.xlsx (Saturday 13:00).
PACKED = {"STD": 554_000, "CE": 53_100}
# part -> (need, usable stock, inbound counted, gap). Usable stock is net of the copies packed since
# the stock snapshot; the sleeve is net of the 64,000 rev B lot (ECN-2026-118).
PARTS = {
    "CMP-GAM-001": (104_900, 70_100, 28_000, 6_800),
    "CMP-GAM-008": (18_900, 13_000, 0, 5_900),
    "CMP-GAM-010": (18_900, 15_500, 0, 3_400),
    "CMP-GAM-004": (86_000, 80_000, 20_000, 0),
    "CMP-GAM-003": (86_000, 54_000, 350_000, 0),
}


def snapshot_fingerprint(root):
    manifest = sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_file() and not any(part.startswith(".") for part in relative.parts):
            digest = sha256(path.read_bytes()).hexdigest()
            manifest.update(f"{relative.as_posix()}\t{digest}\n".encode("utf-8"))
    return manifest.hexdigest()


def forecast_rows(report):
    _, heading, section = report.partition("\n## Forecast (default model,")
    if not heading:
        raise ValueError("NUMBERS.md is missing the default forecast section")

    def count(value):
        return int(value.replace(",", ""))

    for line in section.split("\n## ", 1)[0].splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells[0] not in {"STD", "CE"}:
            continue
        edition, target, packed_range, probability = cells[:4]
        yield edition, {
            "target": count(target),
            **dict(zip(QUANTILES, map(count, packed_range.split("/")), strict=True)),
            "probability": Decimal(probability.removesuffix("%")) / 100,
        }


class PublishedDefaultForecastTest(unittest.TestCase):
    def test_published_forecast_matches_dashboard(self):
        source = Path(os.environ.get("DEMO_DATA_DIR", ROOT / "data")).resolve()
        if "DEMO_DATA_DIR" not in os.environ and not source.is_dir():
            self.skipTest("Set DEMO_DATA_DIR to the private snapshot named in docs/NUMBERS.md")
        self.assertTrue(source.is_dir(), f"Snapshot directory does not exist: {source}")

        report = (ROOT / "docs/NUMBERS.md").read_text(encoding="utf-8")
        fingerprint = re.search(r"^- Forecast input SHA-256: `([0-9a-f]{64})`", report, re.M)
        cutoff = re.search(r"^- Launch cutoff: `([^`]+)`", report, re.M)
        runs = re.search(r"^## Forecast \(default model, ([0-9]+) runs,", report, re.M)
        self.assertIsNotNone(fingerprint, "NUMBERS.md is missing the forecast input fingerprint")
        self.assertIsNotNone(cutoff, "NUMBERS.md is missing the launch cutoff")
        self.assertIsNotNone(runs, "NUMBERS.md is missing the default model trial count")
        rows = list(forecast_rows(report))
        self.assertCountEqual([edition for edition, _ in rows], ["STD", "CE"])

        env = {key: value for key, value in os.environ.items() if not key.startswith("SOONY_IMAP_")}
        env.update(CHASER_REAL_SMTP="0", SOONY_LLM_PROVIDER="none")
        with TemporaryDirectory(prefix="soony-numbers-") as folder:
            work = Path(folder)
            data = work / "data"
            shutil.copytree(source, data)
            self.assertEqual(
                snapshot_fingerprint(data), fingerprint[1],
                "Replay inputs differ from the published forecast snapshot in NUMBERS.md",
            )
            result = subprocess.run(
                [sys.executable, "-m", "src.orchestrator", "--once",
                 "--data", str(data), "--db", str(work / "forecast.db")],
                cwd=ROOT, env=env, capture_output=True, text=True, check=True, timeout=240,
            )

        dashboard = json.loads(result.stdout, parse_float=Decimal)
        self.assertEqual(
            datetime.fromisoformat(dashboard["launch"]["deadline"]), datetime.fromisoformat(cutoff[1]),
            "Dashboard launch cutoff differs from NUMBERS.md",
        )
        self.assertEqual(dashboard["model"]["runs"], int(runs[1]), "Default model trial count changed")
        metrics = ("target", *QUANTILES, "probability")
        entries = dashboard["readiness"]
        self.assertCountEqual([item["edition"] for item in entries], ["STD", "CE"])
        actual = {item["edition"]: {key: item[key] for key in metrics} for item in entries}
        self.assertDictEqual(dict(rows), actual, "Dashboard default forecast differs from NUMBERS.md")

        self.assertEqual({item["edition"]: item["packed"] for item in entries}, PACKED,
                         "Packed counts must come from launch_status.xlsx")
        risks = {item["id"]: item for item in dashboard["risks"]}
        for part, (need, usable, inbound, gap) in PARTS.items():
            with self.subTest(part=part):
                self.assertEqual(
                    (risks[part]["required"], risks[part]["onHand"], risks[part]["inbound"], risks[part]["gap"]),
                    (need, usable, inbound, gap), "Component position differs from NUMBERS.md")
        sleeve = risks["CMP-GAM-004"]
        self.assertEqual(max(0, sleeve["required"] - sleeve["onHand"]), 6_000, "Standard sleeve gap before inbound")
