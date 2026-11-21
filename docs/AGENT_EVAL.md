# Agent evaluation report

The harness is now attached to every `AgentTeam.run_event()` result. Violations set
`proposal_status` to `blocked by harness` and block pending approvals/decisions. Each
role prompt loads its knowledge pack and requires the role JSON schema; delegation and
supplier drafts are idempotent.

| Scenario | Live runs | Verified pass rate | Cost |
|---|---:|---:|---:|
| art_book_shortfall | 2 recorded in `docs/agent_runs/art_book_live.json` | 100% | $0.057892 |
| quality_hold | not completed | unknown | budget exhausted |
| german_notice | not completed | unknown | budget exhausted |

The existing art-book cassette had zero hallucinated numeric values, no supplier send,
and correct deterministic evidence. A later all-scenario live attempt was stopped at
$1.694971; its stop violations were caused by shared historical traces, now fixed by
isolating each evaluator run. Fake golden scenarios remain available via
`python3 -m tests.agent_eval.run_eval --fake`.
