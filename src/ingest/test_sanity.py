"""Quick, offline checks for source normalization and transactional replay."""

import hashlib
import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from .run import ingest

LEGACY = "soony/erp/purchase_orders_legacy.csv"
MODERN = "soony/erp/purchase_orders_current.csv"
SHIPMENTS = "soony/erp/open_shipments.csv"
TRACKER = "soony/logistics/open_shipments_tracker.xlsx"
PROFILE = "suppliers/SUP-0019_Fixture/profile.csv"


class IngestionSanityTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.data = root / "data"
        self.state = root / "state.json"
        self.database = root / "soony.db"
        self.manifest = {}
        self.write(LEGACY, (
            "EBELN;EBELP;LIFNR;MATNR;MENGE;NETPR;BEDAT;ZZSTAT;ERNAM\r\n"
            '4500000001;00010;19;cmp-gam-003;44000;1,5200;08/12/2024;GL;"André"\r\n'
        ).encode("cp1252"))
        self.write(MODERN, (
            "Material ID\tVendor ID\tPO Number\tLine Number\tOrder Date\tQty\tStatus\n"
            "CMP-GAM-003\tSUP-0019\t4500000001\t1\t2025-07-04\t20000\tOpen\n"
        ).encode("utf-16"))
        self.write(SHIPMENTS, b"shipment_id,status,eta\nSHP-1,arrived_port,2026-11-19\n")
        self.write(PROFILE, b"Supplier Name,Supplier ID\nFixture Supplier,0019\n")
        book = self.data / TRACKER
        book.parent.mkdir(parents=True)
        # Shared strings, an introductory row, a sparse record, and an Excel date serial.
        with ZipFile(book, "w") as archive:
            archive.writestr("xl/workbook.xml", """
                <workbook xmlns:r="urn:relationships">
                  <workbookPr date1904="1"/>
                  <sheets><sheet name="Tracker" r:id="rId1"/></sheets>
                </workbook>
            """)
            archive.writestr("xl/_rels/workbook.xml.rels", """
                <Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>
            """)
            archive.writestr("xl/sharedStrings.xml", "<sst><si><t>Fixture Supplier</t></si></sst>")
            archive.writestr("xl/worksheets/sheet1.xml", """
                <worksheet><sheetData>
                  <row r="1"><c r="A1" t="inlineStr"><is><t>Shipment</t></is></c></row>
                  <row r="3">
                    <c r="A3" t="inlineStr"><is><t>Shipment</t></is></c>
                    <c r="B3" t="inlineStr"><is><t>Supplier</t></is></c>
                    <c r="C3" t="inlineStr"><is><t>ETA</t></is></c>
                    <c r="D3" t="inlineStr"><is><t>Status</t></is></c>
                  </row>
                  <row r="7">
                    <c r="A7" t="inlineStr"><is><t>SHP-1</t></is></c>
                    <c r="B7" t="s"><v>0</v></c>
                    <c r="C7"><v>44883</v></c>
                    <c r="D7" t="inlineStr"><is><t>in transit</t></is></c>
                  </row>
                </sheetData></worksheet>
            """)
        self.write(TRACKER, book.read_bytes())

    def write(self, source, body):
        path = self.data / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        self.manifest[source] = hashlib.sha256(body).hexdigest()

    def run_ingest(self):
        self.state.write_text(json.dumps(self.manifest), encoding="utf-8")
        return ingest(self.data, self.state, self.database)

    def query(self, sql):
        with sqlite3.connect(self.database) as db:
            return db.execute(sql).fetchall()

    def test_initial_snapshot_and_replay(self):
        first = self.run_ingest()
        self.assertEqual(len(first["files"]), 5)
        self.assertEqual(first["tables"]["purchase_orders"]["rows"], 2)
        self.assertEqual(self.query("""
            SELECT po_line, supplier_id, unit_price, order_date, status, status_raw, buyer
            FROM purchase_orders WHERE po_number = '4500000001' AND status_raw = 'GL'
        """), [(1, "SUP-0019", 1.52, "2024-08-12", "delivered", "GL", "André")])
        self.assertEqual(self.query("""
            SELECT status, source_sheet, source_row, supplier_id, eta FROM open_shipments
            WHERE shipment_id = 'SHP-1' ORDER BY source
        """), [("arrived_port", "", 2, None, "2026-11-19"),
               ("in_transit", "Tracker", 7, "SUP-0019", "2026-11-19")])
        replay = self.run_ingest()
        self.assertEqual(replay["files"], [])
        self.assertEqual(replay["bridge_files"], [])
        self.assertEqual(replay["tables"]["open_shipments"], {"rows": 2, "added": 0, "removed": 0})

    def test_overlapping_exports_and_repeated_rows_count_once(self):
        copy = "soony/erp/open_shipments_update.csv"
        self.write(copy, b"shipment_id,status,eta\nSHP-1,arrived_port,2026-11-19\n"
                         b"SHP-2,in_transit,2026-11-20\nSHP-2,in_transit,2026-11-20\n")
        self.run_ingest()
        self.assertEqual(self.query("SELECT shipment_id, source_row FROM open_shipments "
                                    "WHERE source_sheet = '' ORDER BY shipment_id"),
                         [("SHP-1", 2), ("SHP-2", 3)])
        del self.manifest[SHIPMENTS]
        self.run_ingest()
        self.assertEqual(self.query("SELECT source FROM open_shipments WHERE shipment_id='SHP-1' "
                                    "AND source_sheet=''"), [(copy,)])

    def test_changed_removed_and_invalid_inputs(self):
        self.run_ingest()
        self.write(SHIPMENTS, b"Shipment,Shipment Status,ETA\nSHP-1,in_delivery,2026-11-20\n")
        modified = self.run_ingest()
        self.assertEqual(modified["files"][0]["change"], "modified")
        self.assertEqual(modified["tables"]["open_shipments"], {"rows": 2, "added": 1, "removed": 1})
        self.assertEqual(self.query("SELECT status FROM open_shipments WHERE source_sheet = ''"),
                         [("in_delivery",)])

        # A bridge deletion can leave the old download on disk.
        del self.manifest[TRACKER]
        removed = self.run_ingest()
        self.assertEqual(removed["files"][0]["change"], "removed")
        self.assertEqual(removed["tables"]["open_shipments"]["rows"], 1)

        self.write(SHIPMENTS, b"Shipment,Shipment Status,ETA\nSHP-1,in_delivery,invalid-date\n")
        with self.assertRaisesRegex(ValueError, r"open_shipments.csv: row 2: eta"):
            self.run_ingest()
        self.assertEqual(self.query("SELECT eta FROM open_shipments"), [("2026-11-20",)])
        self.assertEqual(json.loads(self.query("SELECT summary FROM ingest_state")[0][0]), removed)


if __name__ == "__main__":
    unittest.main()
