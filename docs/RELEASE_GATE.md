# Release Gate

`python3 -m src.decide.release_gate` evaluates every BOM material from the
current readiness result. `GO` means the reconciled usable stock can be packed;
`HOLD` quarantines a failed inspection lot; `HUMAN` stops release until the
named business owner resolves an artwork, embedded-component, or qualification
conflict. Every reason carries the source file and page/row/quote supplied by
ingestion or document extraction.

Quality holds remove the inspected quantity from the GO quantity. Conflicting
artwork revisions are presented as a Marketing decision, not as an invented
“wrong” revision. A supplier-fitted component that also appears in the BOM is
an Engineering decision. Conditional Pune statue supply requires PPAP and
written Supplier Quality and Category Lead release; a vacant Category Lead is
escalated to Procurement. ERP-versus-confirmation Incoterm differences are
flagged as commercial review only and do not block packing.

`GET /api/release-gate` and the read-only `release_gate_status(part_id?)`
agent tool expose the same result. The gate is recomputed from the store on
each call, so a newly ingested inspection report can change a verdict. It
cannot determine the cost of a missed copy, legal acceptance of a quality
concession, or whether Marketing accepts a revision; those remain human
decisions.

## v2 (21 Nov drop, ECN-2026-118/119)

The 21 Nov files are read straight from `data/` by `load_drop()` (bom_delta,
components_update, supplier `profile.json`, org chart v2, CPO memo), so the gate
does not wait for the store. A missing file simply disables its rule.

- **ECN revision with `use_up_old_rev=N` (CMP-GAM-004, B to C):** the received
  rev B lot (64,000, PackRight PO 4500318738) is HOLD, the open rev B quantity
  (675,000) is "do not accept, ask the supplier to re-print rev C", Karton rev C
  is GO. Part status is HOLD; `go_quantity` is the usable rev C quantity (stock
  minus the rev B lot), so the Standard edition count reflects rev C sleeves only.
  Decision owner: Sofia Marchetti (Category Lead Print & Packaging): re-order /
  re-print rev C and what to do with the rev B pieces. The old Marketing "B or C"
  question is gone because rev C is the released revision.
- **`use_up_old_rev=Y` (ECN-119 poster rev A to B):** stays GO with a note.
- **Critical part on hold (CMP-GAM-010):** the reason names the critical flag
  (components_update, Mei Lin); `required_authority` is Quality & Compliance
  (Clara Weiss) for HOLD to GO (CPO memo: "Quality & Compliance has the last word,
  not the pack-out plan").
- **Pune qualification expired:** conditional, `validUntil` before the as-of date
  (deadline date) and `extendedBy` null. PP-07 section 5: POs after expiry are held
  awaiting approval; extension needs Supplier Quality Lead and Category Lead in
  writing, once, max 90 days. The Category Lead Collector's Items is vacant until
  Arjun Krishnan (from 2026-11-23), so the exception goes to the Head of
  Procurement (Dr. Maren Vogt, section 6) with Daniel Okafor as co-signer.
- **Rare earth:** magnet verdict unchanged (HUMAN only for the BOM double-count).
  Note: launch boxes are covered, deliveries after 2026-12-01 move out 6 weeks
  (63 to 105 d), a post-launch risk.
- Per-edition `units_with_go_parts` uses GO quantities only and lists `limited_by`.
  Extra part fields: `ecn`, `do_not_accept_quantity`, `usable_new_revision_quantity`,
  `old_revision_lot_quantity`, `required_authority`, `required_human_action.decisions`.
