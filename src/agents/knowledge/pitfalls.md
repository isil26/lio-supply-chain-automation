# Pitfalls and tool checks

## ERP and receiving
- Booking versus quantity: a goods-receipt batch may be booked at 80,000 against an ordered 8,000.
  - Check: compare the receipt to the PO and receiving scan with `search_documents` or `compare_sources`.
- A quality-failed lot may remain unrestricted in ERP.
  - Check: inspect lot, inspection report and PPAP/release status before counting usable stock.
- `last_count` may predate recent goods receipts or corrections.
  - Check: compare stock_snapshot timestamps with goods_receipts and receiving documents.
- Cancellation lines on delivered POs can look like open stock.
  - Check: use the latest ERP status and delivered/received quantities, not tracker-only status.

## Documents and IDs
- Printed thousands separators differ: dots/spaces may denote thousands.
  - Check: verify the canonical quantity against the source quote and PO line.
- PO item 00010/00020 maps to PO lines 1/2, not the SAP line string itself.
- Legacy LIFNR 19 maps to SUP-0019.
- Handwritten receiving quantities override printed figures.
  - Check: compare the image crop, OCR text and GR row.

## Logistics and contracts
- Tracker status may omit ERP shipments or disagree with ERP.
  - Check: reconcile every shipment ID and retain both source citations.
- ETA is not the promised delivery; add route, customs and last-mile handling where the tool does so.
- DDP in ERP may conflict with EXW in an order confirmation.
  - Check: retrieve the relevant PO and OC; never infer seller liability.
- A rev B sleeve may be PO master at one supplier while rev C is required elsewhere.
  - Check: compare component revision and release document.
- Lid magnets may be fitted inside the collector box, not stocked separately.
  - Check: inspect PackRight Annex B and BOM interpretation; do not double-count until confirmed.
- Pune supply is conditional and blocked while the Collector's Items Category Lead is vacant.
  - Check: route review to Supplier Quality and the authorised Category Lead.

## Release gate and pack plan
- The sleeve revision conflict (CMP-GAM-004, rev B vs rev C) is a HUMAN item: report quantities per revision from release_gate_status and escalate_to_human to Marketing / Head of Procurement; never pick a revision.
- The quarantined statue lot (CMP-GAM-010) is HOLD until written quality release; do not count it as packable.
- The game card (CMP-GAM-001) is the binding shared part for both editions, so an earlier arrival of the 28,000 air lot is the biggest lever; the art book and statue only matter for the Collector's share.
- Never state units gained that are not in the packplan result; copy numbers exactly from the tool.
