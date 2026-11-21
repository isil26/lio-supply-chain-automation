# Compact few-shot examples

## 1. Good art-book analysis
Tool trace: `get_readiness()` -> result; `search_documents(query="art book GR 5000413065")` -> `{file:"WZ-261116-473.jpg",page:"1",quote:"handwritten correction"}`.
Final: `"Claim: the receiving scan contradicts the GR booking. Cite both records and describe the correction; do not copy a forecast number unless get_readiness returned it."`
Good because it separates source evidence from tool-derived conclusions.

## 2. Bad unsupported supplier claim
Bad: `"Karton will deliver all missing art books Friday."`
Why bad: no verifiable document, and Friday is supplier/commitment language without evidence.
Correction: return the offer status and cite it, then request a packing list and truck slot.

## 3. Pune quality hold escalation
Tool trace: `search_documents(query="Pune PPAP release")` -> contract and organisation evidence.
Final: `"Pune remains conditional. PPAP plus written release by Supplier Quality and Collector's Items Category Lead are required; role is vacant. Escalate to human; do not count Pune as released."`
Good because it identifies both the internal signers and the vacancy.

## 4. Refusal to send without approval
Tool trace: `draft_email(...)` -> draft and `send_email(...)` -> approval gate result.
Final: `"Draft prepared in supplier language. Send not attempted; pending human approval."`
Bad alternative: `"Email sent"` after a dry-run or denied gate.

## 5. Unseen German notice
Tool trace: `search_documents(query="unseen German notice")` -> no matching parser/coverage.
Final: `{"status":"needs_review","file":"unseen_german_notice.pdf","reason":"unknown format or incomplete coverage","forecast_changed":false}`
Good because the agent requests review rather than guessing.

## 6. Numeric claim copied from a tool
Tool trace: `get_readiness()` -> named JSON fields.
Final: copy only the exact returned field names and values, and attach the tool output reference.
Bad: reusing a number seen in a slide or doc as if it came from the current tool run.
