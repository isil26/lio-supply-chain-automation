"""The 21 Nov 19:25 drop formats reach the store with source citations, idempotently."""

import json
import shutil
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from .run import ingest

DATA = Path(__file__).resolve().parents[2] / "data"
FILES = ("soony/context/launch_status.xlsx", "soony/master/bom_delta_2026-11-21.csv",
         "soony/master/components_update_2026-11-21.csv", "soony/news/2026-11-21_export_controls.json",
         "suppliers/SUP-0018_Pune_Diecast_Works/profile.json")


@unittest.skipUnless(all((DATA / name).is_file() for name in FILES), "drop files not mirrored")
class DropIngestTest(unittest.TestCase):
    def test_rows_citations_and_idempotence(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            for name in FILES:
                (root / "data" / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(DATA / name, root / "data" / name)
            database, state = root / "s.db", root / "state.json"
            first = ingest(root / "data", state, database)
            self.assertEqual({file["table"] for file in first["files"]},
                             {"launch_status", "bom_changes", "component_changes", "news_items", "suppliers"})
            second = ingest(root / "data", state, database)
            self.assertEqual(second["files"], [])
            with closing(sqlite3.connect(database)) as con:
                status = con.execute("SELECT product_id,packed,still_to_pack,rate_per_hour,source,source_sheet "
                                     "FROM launch_status WHERE kind='edition' ORDER BY product_id").fetchall()
                self.assertEqual([row[:4] for row in status],
                                 [("FG-GH6-CE", 53100, 18900, 900), ("FG-GH6-STD", 554000, 86000, 6000)])
                self.assertTrue(all(row[4].endswith("launch_status.xlsx") and row[5] == "Launch status" for row in status))
                self.assertEqual(con.execute("SELECT count(*) FROM launch_status WHERE kind='note'").fetchone()[0], 3)
                ecn = con.execute("SELECT rev_old,rev_new,use_up_old_rev FROM bom_changes "
                                  "WHERE change_id='ECN-2026-118'").fetchone()
                self.assertEqual(ecn, ("B", "C", 0))
                self.assertEqual(con.execute("SELECT new FROM component_changes WHERE component_id='CMP-GAM-010' "
                                             "AND field='critical'").fetchone()[0], "Y")
                self.assertEqual(con.execute("SELECT qualification_valid_until FROM suppliers").fetchone()[0], "2026-10-30")
                self.assertEqual(con.execute("SELECT count(*) FROM news_items").fetchone()[0], 2)
