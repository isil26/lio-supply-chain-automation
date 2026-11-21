# Art-book run provenance for T53

[Machine-readable handoff](art-book-live.json) is safe structured metadata for the protected hosted panel. It covers the art-book run reported by [copilot-live](../art_book_live.json). Its coverage value is `summary_only`.

## What the panel can show

Show **Reported live-run summary · detailed trace unavailable**. The model, roles, hand-off targets, approval flag, and usage totals come from the published summary. The totals of $0.057892, 130,117 input tokens, and 3,653 output tokens are reported aggregate figures. The original CLI summed the full `agent_trace` table in the selected database. The original database boundaries and attribution to an individual pass could not be checked. The run and event timestamps are unknown.

The empty `steps`, `proposed_calls`, `verified_handoffs`, and `approvals_pending` arrays mean there are no independently verified event records in this handoff. The summary separately reports role completion, delegation targets, a pending approval, and no supplier send. It gives no individual tool names, execution statuses, hand-off order, or approval identifiers. Do not present those summary fields as a timeline or an approved decision.

## Source checks

- The published summary and README were verified against the initial Git commit. The manifest pins the sources by commit and SHA-256.
- The [existing display snapshot](../../../web/public/snapshot/agent_run.json) is a derived artifact. The [exporter](../../../scripts/export_agent_run.py) creates five rows labeled `recorded_run`, splits aggregate cost evenly, and sets the latency of each row to zero. Those rows do not establish tool execution, status, time, cost, or order.
- The original runner referenced a teammate’s local checkout. Its default trace database was `store/soony.db`, and the recorder's default cassette directory was `store/agent_cassettes/`. The original database and cassettes were unavailable on this Mac. The accessible hosted replay database contained four zero-cost runs and no trace rows. Git history and the repository’s Actions artifacts provided no original per-event evidence. The separate live evaluation reports identify different evaluation runs.
- No run was repeated. The handoff file is nested so the existing exporter’s root-level JSON glob still selects its existing inputs.

A future verified timeline needs the original run boundary and recorded tool execution rows, with proposal and result identifiers if available. Export only structured event fields and keep raw requests, responses, reasoning, credentials, and correspondence in private storage.
