# Answer and citation style

## Citation
Use `{file, page, quote}` for document claims. Images may use `{file, page, quote}` where page means the viewed sheet/scan index and quote is the exact OCR or handwritten text.
If source evidence is absent, say `unknown` and identify the tool or document needed.

## Uncertainty
- Distinguish fact, tool result, assumption and estimate.
- Never transform a supplier promise into a release or a shipment status into a received quantity.
- Never output a cost or probability that was not returned by a tool.
- Preserve unknowns: missing loss-per-copy remains unknown until Dr. Vogt supplies it.

## Role output schemas
Triage final: `{"status","plan","delegations","human_checks","trace","uncertainties"}`
Analyst: `{"findings":[{"claim","source","status"}],"unknowns":[]}`
Verifier: `{"accepted":[],"rejected":[],"reason"}`
Planner: `{"options":[{"id","cost_status","probability_status","assumptions","approval"}],"recommendation","needs_human"}`
Chaser: `{"draft","supplier_id","rung","commitment_score","evidence","approval_required","forbidden_terms_checked"}`
Supplier simulation: `{"reply","evidence","commitment_score","attachments":[],"hidden_capacity_status"}`

For supplier drafts, use the supplier's preferred language; for internal outputs use English.
Do not include contract penalties, prices or delivery promises unless cited and tool/approved.
