# Data map

- `case-data/soony/master/products.csv`: FG-* finished goods and launch metadata.
- `case-data/soony/master/bom.csv`: FG-* to CMP-* quantities and validity.
- `case-data/soony/master/components.csv`: CMP-* descriptions, revisions and categories.
- `case-data/soony/erp/stock_snapshot.csv`: DC-HAM batch quantities and last-count dates.
- `case-data/soony/erp/goods_receipts.csv`: goods receipts linked to PO, supplier and receiving document.
- `case-data/soony/erp/purchase_orders_2025H2-2026.csv`: modern PO lines, comma separator and ISO dates.
- `case-data/soony/erp/purchase_orders_legacy_2024-2025H1.csv`: semicolon legacy export; decimal comma, MM/DD/YYYY, SAP fields EBELN/LIFNR/MATNR/WEDAT/EINDT/ZZCONF.
- `case-data/soony/erp/open_shipments.csv`: shipment, supplier, PO and material links.
- `case-data/soony/logistics/open_shipments_tracker_v37_FINAL_final2.xlsx`: tracker view; compare to ERP status and update timestamps.
- `case-data/soony/receiving/DC-HAM/`: delivery notes and images; prefixes DN-, SN- and WZ- identify supplier families.
- `case-data/suppliers/<SUP-*>/profile.csv`: supplier contact, country, language and notes.
- `case-data/suppliers/<SUP-*>/order_confirmations/`: PO-level confirmation PDFs.
- `case-data/suppliers/<SUP-*>/contracts/` and `notices/`: contract clauses and launch notices.

ID mappings:
- Legacy LIFNR 19 maps to SUP-0019.
- Modern PO item `00010` maps to PO line 1; `00020` maps to line 2.
- PR-CC-0312 -> CMP-GAM-003, PR-SL-0604 -> CMP-GAM-004, PR-RB-2207 -> CMP-GAM-007.
- Keep PO, shipment, batch and supplier identifiers separate.

Tool answers:
- `get_readiness`/`list_shortfalls`: deterministic readiness and component gaps.
- `search_documents`/`get_document`: cited document lookup.
- `compare_sources`: reconcile ERP, receiving and shipment evidence.
- `whatif`/`breakeven`/`supplier_history`: explicit scenario assumptions and supplier reliability.
- `draft_email`, `parse_reply`, `send_email`: draft and reply operations; send is approval-gated.
