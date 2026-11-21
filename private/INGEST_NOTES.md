# Ingestion findings

Paths below are relative to `data/`. Row numbers include the header, and workbook references name the worksheet.

## Shipments

- **Two status conflicts.** `soony/erp/open_shipments.csv` row 2 lists `SHP-2026-04276` as `arrived_port` and says it was discharged and available for pickup. `soony/logistics/open_shipments_tracker_v37_FINAL_final2.xlsx`, Tracker row 2, says `in transit` with the comment “RP: call terminal.” ERP row 3 lists `SHP-2026-04281` as `in_delivery`, while Tracker row 3 says `in transit`. The ETAs agree for all 14 shipments shared by the sources.
- **Tracker coverage.** The workbook has 14 shipment rows (Tracker rows 2–15). The ERP CSV has 25 (rows 2–26). ERP rows 16–26 have no matching tracker row, including the two Hwaseong and Boise air shipments `SHP-2026-04311` and `SHP-2026-04314` (ERP rows 17 and 19).
- **ETA location and transit.** ERP row 17 gives a Nov 20 ETD and Nov 21 ETA for `SHP-2026-04311` on `RT-005`. `soony/master/routes.csv` row 6 gives two days for ICN–FRA and row 10 gives one more day for FRA–DC-HAM on `RT-009`. The launch workbook `soony/context/launch_plan_GH6.xlsx` counts the 48,000 cards on this flight as due before launch (Inbound row 2 and Parts row 4). The air ETA is for FRA.
- **Sea transit varies from the route master.** ERP row 8 gives 41 calendar days from ETD to ETA for the delayed `SHP-2026-04298`, compared with 32 days for `RT-002` in `soony/master/routes.csv` row 3. The same route also has 36-day and 34-day ERP records in rows 2 and 6.

## Inventory and receiving

- **Lid magnets are listed with zero stock.** `soony/erp/stock_snapshot.csv` row 33 shows `CMP-MAG-005` at zero with no batch. `soony/master/bom.csv` row 17 specifies four per collector’s edition, and the launch workbook Parts row 13 flags 100,800 needed and zero inbound. `suppliers/SUP-0029_Guangzhou_PackRight/components.csv` row 5 says the supplier fits the magnets into `CMP-GAM-007` and does not order, receive, or stock them separately. The BOM and stock quantities remain as recorded.
- **Game cards below safety stock.** `soony/erp/stock_snapshot.csv` rows 2–4 show 118,400 units across the three `CMP-GAM-001` lots, with 0.7 weeks of cover and a repeated 344,000-unit safety target. The count date is Nov 10 for each lot. The matching goods receipts in `soony/erp/goods_receipts.csv` rows 386, 387, and 390 were posted Nov 13–16.
- **Tenfold art-book receipt.** `soony/erp/goods_receipts.csv` row 393 records 80,000 received against 8,000 ordered for PO `4500318768` line 3 and says “over delivery accepted.” `soony/erp/purchase_orders_2025H2-2026.csv` row 272 confirms the 8,000-unit PO line. Stock snapshot row 25 carries 80,000 in the corresponding batch `5000413065`, and the launch workbook Parts row 9 counts 91,300 art books in ERP stock.
- **Receipts without PO references.** `soony/erp/goods_receipts.csv` rows 330, 356, and 382 record 78,000 units of `PRM-GH6-PIN` in total, booked as miscellaneous merchandise. The material ID is absent from `soony/master/components.csv` rows 2–13.
- **PO delivery dates can describe the final installment.** For example, goods receipt rows 156 and 160 record 6,100 and 2,900 units on Oct 2 and Oct 10 for PO `4500318550` line 1. The modern PO export row 30 records Oct 10 as the actual delivery date and 9,000 as the order quantity.

## PO history and packout

- **Legacy currency and cancellation evidence.** `soony/erp/purchase_orders_legacy_2024-2025H1.csv` row 1 has no currency column. Row 2 uses `NETPR=1,5200`, `LIFNR=19`, and `ZZSTAT=GL`. Row 16 uses `ZZSTAT=LO` with a negative quantity and no delivery date, consistent with cancellation rows 107 and 156 in the modern PO export.
- **Sourcing status differs by supplier.** Pune’s `suppliers/SUP-0018_Pune_Diecast_Works/profile.csv` row 2 says qualification is conditional. Its `components.csv` row 2 lists 20% of statue sourcing, and goods receipt row 391 already records a 5,600-unit delivery. The modern PO export rows 298 and 312 show two later Pune orders awaiting approval.
- **Packout totals reconcile.** `soony/erp/packout_log.csv` rows 2–29 sum to 512,000 Standard and 46,800 Collector’s units, matching `soony/erp/stock_snapshot.csv` rows 35–36 and launch workbook Editions rows 4–5.
