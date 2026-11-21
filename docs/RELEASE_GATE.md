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
