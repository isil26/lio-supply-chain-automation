"""Fast offline drop regressions. Run with unittest discover -s tests/drops."""

import csv
import hashlib
from io import StringIO
import json
import os
from contextlib import closing, redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from openpyxl import Workbook

from src.docs import documents
from src.ingest.store import connect, get_state, rows
from src.orchestrator import __main__ as orchestrator

PART = "CMP-TST-001"
PRODUCT = "FG-TST-STD"
STOCK = "soony/erp/stock_snapshot.csv"
PO = "soony/erp/purchase_orders.csv"
SHIP = "soony/erp/open_shipments.csv"
STOCK_HEADER = ("snapshot_date", "site", "material_id", "batch", "quantity")
SHIP_HEADER = ("shipment_id", "reference", "material_ids", "qty", "mode", "eta", "status", "dest_site")
PO_HEADER = ("po_number", "po_line", "supplier_id", "material_id", "quantity", "order_date", "unit_price", "status")
SHIPMENTS = (("SHIP-1", "SEA-1", PART, 45, "sea", "2026-11-19", "in_transit", "DC-HAM"),)


class Mirror:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.root = self.folder / "data"
        self.db = self.folder / "audit.db"
        self.put("soony/context/onboarding_notes.md", b"Test launch goes on sale at 20:00 at DC-HAM.\n")
        self.csv("soony/context/sites.csv", ("site_id", "name"), [("DC-HAM", "Test DC")])
        self.csv("soony/master/products.csv", ("product_id", "launch_date"), [(PRODUCT, "2026-11-22")])
        self.csv("soony/master/bom.csv", ("parent_id", "child_id", "qty_per"), [(PRODUCT, PART, 1)])
        self.csv("suppliers/SUP-9001/components.csv", ("component_id", "unit_price", "currency"), [(PART, 2, "EUR")])
        self.csv(PO, PO_HEADER, [("4590000001", 1, "SUP-9001", PART, 100, "2026-11-17", 2, "open")])
        self.stock("2026-11-20", [("LOT-A", 60)])
        self.csv(SHIP, SHIP_HEADER, SHIPMENTS)
        book = Workbook()
        editions = book.active
        editions.title = "Editions"
        editions.append(("edition", "product_id", "day_one_demand", "packed", "rate_per_hour", "hours_available"))
        editions.append(("STD", PRODUCT, 100, 0, 50, 12))
        shifts = book.create_sheet("Shifts")
        shifts.append(("day", "shift", "hours"))
        shifts.append(("Sunday", "08:00–20:00", 12))
        book.save(self.root / "launch.xlsx")
        book.close()
        self.loop = orchestrator.Loop(SimpleNamespace(demo=False, online=False, data=self.root, db=self.db, interval=0))

    def path(self, source):
        path = self.root / source
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def put(self, source, body):
        self.path(source).write_bytes(body)

    def csv(self, source, header, data, delimiter=",", encoding="utf-8"):
        with self.path(source).open("w", encoding=encoding, newline="") as stream:
            writer = csv.writer(stream, delimiter=delimiter)
            writer.writerow(header)
            writer.writerows(data)

    def stock(self, date, batches, source=STOCK):
        self.csv(source, STOCK_HEADER, [(date, "DC-HAM", PART, batch, qty) for batch, qty in batches])

    def manifest(self, omit=()):
        state = self.folder / "bridge" / "state.json"
        state.parent.mkdir(exist_ok=True)
        paths = ((path.relative_to(self.root).as_posix(), path) for path in self.root.rglob("*") if path.is_file())
        state.write_text(json.dumps({key: hashlib.sha256(path.read_bytes()).hexdigest()
                                     for key, path in paths if key not in omit}), encoding="utf-8")
        self.loop.args.online = True

    def refresh(self):
        # Redirect only the manifest lookup. cycle() defaults to an offline refresh.
        with patch.object(orchestrator, "ROOT", self.folder):
            self.loop.cycle()
        return self.snapshot()

    def background_refresh(self):
        # Stop after one iteration while retaining the server's real error handling.
        with patch.object(self.loop.trigger, "wait", side_effect=lambda _: self.loop.stop.set()):
            with redirect_stderr(StringIO()) as stderr:
                self.loop.background()
        return any(line.startswith("Pipeline: ") for line in stderr.getvalue().splitlines()), self.snapshot()

    def snapshot(self):
        with closing(connect(self.db)) as con:
            return (
                orchestrator.dashboard(con),
                get_state(con, "truth"),
                list(documents(con)),
                list(rows(con, "po")),
            )


def offline_environment():
    clean = {key: value for key, value in os.environ.items()
             if not key.startswith(("CHASER_", "SOONY_IMAP_", "SOONY_LLM_"))
             and key not in {"SOONY_TOKEN", "SOONY_LOCAL_MODEL", "SOONY_VISION_MODEL"}}
    return patch.dict(os.environ, {**clean, "SOONY_LLM_PROVIDER": "none", "CHASER_REAL_SMTP": "0",
                                   "CHASER_NO_TEAM_MAIL": "1"}, clear=True)


class DropTests(unittest.TestCase):
    def setUp(self):
        environment = offline_environment()
        environment.start()
        self.addCleanup(environment.stop)
        folder = TemporaryDirectory(prefix="soony-drop-")
        self.addCleanup(folder.cleanup)
        self.mirror = Mirror(folder.name)
        self.base_ui, self.base, _, _ = self.mirror.refresh()
        self.assertEqual(self.base["parts"][PART]["shortfall"], 0)
        self.assertEqual(self.base["editions"][PRODUCT]["p50"], 100)

    def test_aliases_delimiters_encodings_and_dates_in_stock(self):
        for encoding, delimiter, date in (("utf-16", ";", "21.11.2026"), ("cp1252", ",", "11/21/2026")):
            with self.subTest(encoding=encoding, delimiter=delimiter):
                self.mirror.csv(STOCK, ("lot", "qty", "sku", "warehouse", "as_of"),
                                [("MÜNCHEN", "50,5", PART, "DC-HAM", date),
                                 ("DÜSSELDORF", "30,5", PART, "DC-HAM", date)], delimiter, encoding)
                ui, truth, _, _ = self.mirror.refresh()
                self.assertEqual(truth["snapshot"], "2026-11-21")
                self.assertEqual(truth["parts"][PART]["on_hand"], 81)
                self.assertEqual(ui["drop"]["changes"][0]["action"], "changed")
                self.assertIsNone(ui["sync"]["error"])

    def test_new_stock_snapshot_replaces_old_day(self):
        new = "soony/erp/stock_snapshot_next.csv"
        self.mirror.stock("2026-11-21", [("NEW-A", 20), ("NEW-B", 10)], new)
        ui, truth, _, _ = self.mirror.refresh()
        self.assertEqual(truth["parts"][PART]["on_hand"], 30)
        self.assertEqual(truth["parts"][PART]["shortfall"], 25)
        self.assertEqual(truth["editions"][PRODUCT]["p50"], 75)
        self.assertEqual([option["kind"] for option in ui["options"]], ["air"])

    def test_shipment_delay_then_cancellation(self):
        for status, eta, options in (("delayed", "2026-11-23", ["air"]), ("cancelled", "2026-11-23", [])):
            with self.subTest(status=status):
                old = SHIPMENTS[0]
                self.mirror.csv(SHIP, SHIP_HEADER, [(*old[:5], eta, status, old[-1])])
                ui, truth, _, _ = self.mirror.refresh()
                self.assertEqual(truth["parts"][PART]["shortfall"], 40)
                self.assertEqual(truth["editions"][PRODUCT]["p50"], 60)
                self.assertEqual([option["kind"] for option in ui["options"]], options)
                self.assertEqual(bool(truth["inbound"]), status != "cancelled")
                self.assertEqual(ui["drop"]["changes"][0]["action"], "changed")

    def test_split_with_explicit_quantities_and_ids(self):
        self.mirror.csv(SHIP, SHIP_HEADER, [
            ("SHIP-1A", "SEA-1A", PART, 20, "sea", "2026-11-19", "in_transit", "DC-HAM"),
            ("SHIP-1B", "SEA-1B", PART, 25, "sea", "2026-11-24", "delayed", "DC-HAM"),
        ])
        ui, truth, _, _ = self.mirror.refresh()
        self.assertEqual({row["id"]: row["quantity"] for row in truth["inbound"]}, {"SHIP-1A": 20, "SHIP-1B": 25})
        self.assertEqual(truth["parts"][PART]["shortfall"], 20)
        self.assertEqual(truth["editions"][PRODUCT]["p50"], 80)
        self.assertEqual([option["kind"] for option in ui["options"]], ["air"])

    def test_manifest_removal_excludes_file_left_on_disk(self):
        self.mirror.manifest()
        self.mirror.refresh()
        self.mirror.manifest(omit={SHIP})
        ui, truth, _, _ = self.mirror.refresh()
        self.assertTrue(self.mirror.path(SHIP).is_file())
        self.assertFalse(truth["inbound"])
        self.assertEqual(truth["editions"][PRODUCT]["p50"], 60)
        self.assertFalse(ui["options"])
        self.assertEqual([(event["file"], event["action"]) for event in ui["drop"]["changes"]], [(SHIP, "removed")])

    def test_empty_stock_upload_retains_last_good_forecast(self):
        self.mirror.put(STOCK, b"")
        raised, (ui, truth, _, _) = self.mirror.background_refresh()
        self.assertTrue(raised)
        self.assertIn(f"{STOCK}: CSV has no header", ui["sync"]["error"])
        self.assertEqual(truth, self.base)
        self.assertEqual(ui["options"], self.base_ui["options"])

    def test_changed_bytes_at_same_path_replace_previous_rows(self):
        self.mirror.stock("2026-11-20", [("LOT-A", 10)])
        ui, truth, _, _ = self.mirror.refresh()
        self.assertEqual(truth["parts"][PART]["on_hand"], 10)
        self.assertEqual(truth["editions"][PRODUCT]["p50"], 55)
        self.assertEqual([option["kind"] for option in ui["options"]], ["air"])
        self.assertEqual(ui["drop"]["changes"][0]["action"], "changed")
        self.assertEqual(self.mirror.refresh()[1], truth)


if __name__ == "__main__":
    unittest.main()
