# Soony ingestion

Run from the repository root with Python 3.10+, SQLite 3.37+, and Pydantic 2. Install the dependency in your Python environment and run the CLI.

```sh
python3 -m pip install -r src/ingest/requirements.txt
python3 -m src.ingest.run
python3 -m unittest src.ingest.test_sanity
```

The CLI builds `store/soony.db`. It loads both PO exports and creates `purchase_orders`, `goods_receipts`, `stock`, `open_shipments`, `bom`, `components`, `products`, `suppliers`, `routes`, and `packout_log`. The `supplier_components` table holds the supplier catalogs with supplier and component IDs for joins.

Every record carries a path relative to `data/` in `source`, the worksheet name in `source_sheet` (empty for CSV), and a one-based `source_row`. PO and shipment records retain the original status in `status_raw`. The purchase order history preserves a row per source, and both shipment sources are queryable by `shipment_id`. Unavailable values, such as currency and incoterm in the legacy PO export, are SQL `NULL`. Dates and timestamps are ISO text, quantity and price columns are numeric, and ID lists use `|` as the separator.

CSV headers are matched by name and aliases. UTF-8, BOM-marked Unicode, and common Windows text encodings are supported. ISO, dotted, and slash dates are normalized. Ambiguous slash dates use month/day in the SAP or legacy PO export and day/month elsewhere. The shipment workbook reader uses cell values and any cached formula results.

The CLI prints a JSON diff and saves the same JSON in `ingest_state.summary`. `files` lists inputs added, modified, or removed by SHA-256 with row counts before and after. `tables` shows current row counts and row additions and removals. An edited row appears as one addition and one removal. `bridge_files` gives the SHA-256 changes reported for the full bridge manifest, including files outside ingestion. The first run reports additions. An unchanged rerun leaves the data rows in place.

The bridge manifest controls which synced files are current. The CLI verifies input bytes against its digests and ignores stale downloads removed from the manifest. When the manifest is absent, it discovers matching files under `data/` and hashes them locally. A parse or hash error exits with a nonzero status and rolls back the refresh. Use `--data`, `--state`, and `--db` for an isolated run.

```sql
SELECT shipment_id, status, eta, source, source_sheet, source_row
FROM open_shipments
WHERE shipment_id = 'SHP-EXAMPLE';

SELECT summary FROM ingest_state WHERE id = 1;
```
