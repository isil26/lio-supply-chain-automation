# Approval engine (T93): PP-07 as code, with delegated authority

Code: `src/decide/approvals.py`. Data: `docs/delegations.json`. Audit log: sqlite `store/approvals.db` (tables `approvals_log`, `approvals_pending`; pass any connection or `:memory:`).
Demo: `.venv/bin/python -m src.decide.approvals --demo`. Tests: `.venv/bin/python -m unittest tests.test_approvals`.

## Modes
| Mode | Meaning |
|---|---|
| AUTO | A confirmed-in-writing, active delegation covers kind and value (strictly under the limit); the action is information-only (supplier_info_request, internal_message), hold_and_quote or reversible, and not binding; no guard fired. Logged `decided_by='delegation'`, "approved by delegation of <name>, record <id>", never as the person. The approver is notified (`reminder_text`). |
| ONE_CLICK | Named approver per PP-07 gives one click. Also what an unconfirmed delegation produces (`notes` contains "delegation unconfirmed", `delegation_id` is set). |
| ESCALATE | Approver vacant/unavailable, SLA expired, or above the standard approver's limit (air freight over EUR 200,000 per month and category goes to the CPO, SLA 15 min, "same hour"). `approver` is the person who must act now; `escalation_chain` the rest. |
| NEVER | Never automatic: quality releases (Clara Weiss last word; `required_signers` lists Clara Weiss, Daniel Okafor, Category Lead or Head of Procurement under §6), missing evidence, reveals slack/walkaway/maximum premium/cost per missing copy/break-even, missing value, unknown kind, value at or above EUR 5,000,000 with CPO or CFO unavailable. Humans can still decide through `record_human_decision`. |

## Rules in the code
PP-07 §2 value ladder (Buyer < 50k, Category Lead < 500k, Head of Procurement < 2M, CPO < 5M, CPO+CFO above) · §3 dock slot Katrin Jansen, deputy Raj Patel · §4 air freight (month-to-date + new value > 200,000: CPO) · §5 supplier release Supplier Quality Lead + Category Lead; Pune conditional release expired 2026-10-30 (reported in `blocked_by`, release escalates) · §6 exceptions: Head of Procurement · vacancy: Category Lead Collector's Items is vacant until 2026-11-23 (Arjun Krishnan), so route to Dr. Vogt under §6, Daniel Okafor co-signs releases/quality · SLA default 30 min; each further expired SLA moves one step up the chain · kill switch `APPROVALS_KILL_SWITCH=1` (or `kill_switch=True`) turns AUTO into ONE_CLICK · a delegation cannot create authority (delegator must hold at least the needed PP-07 role; dock slots and releases are never covered by a value delegation).

## Delegations (docs/delegations.json)
Record: `id, delegator, delegate ('system'), action_kinds, max_value_eur, valid_from, valid_until, conditions {information_only, reversible, hold_and_quote}, source {who, when, medium}, confirmed_in_writing`. Seed: DEL-001 Dr. Vogt, "anything under EUR 2,000,000 for launch recovery", **confirmed_in_writing false** (relayed report; Isil's recording says information only). Helpers: `add_delegation(record)`, `confirm_delegation(id, evidence_ref)`, `revoke_delegation(id, by)`; CLI `--confirm DEL-001 --evidence "mail ..."`, `--revoke DEL-001 --by "Dr. Maren Vogt"`. When Dr. Vogt or Felix answers "yes, up to EUR X until Sunday 20:00" in writing, add or confirm the record: nothing else changes.

Records marked `simulated` can authorize actions only in the offline replay. Live evaluation excludes these records, and replay decisions identify the approval as simulated.

## Action shape
`{id, kind, value_eur, category ('Game Media' | 'Print & Packaging' | "Collector's Items"), part/edition, recipient, binding, reversible, evidence: [...], requested_at (for SLA), month_to_date_eur (air freight), approver_role (optional, proposed), site, supplier, conditional_release_expired}`. Kinds: supplier_info_request, hold_and_quote, purchase_order, air_freight, dock_slot, quality_exception, supplier_release, internal_message. Naive timestamps are read as Hamburg time (CET).

## Integration (others wire this; nothing here edits their files)
1. **Creating an action (T81 queue / murat-agent):** `con = approvals.connect(); ev = approvals.submit(con, action, now)`. Show `ev["mode"]` as the badge, `ev["approver"]` and `ev["reason"]`, `ev["sla_minutes"]`. `submit` logs the decision and, unless AUTO, registers it as pending for SLA tracking.
2. **POST /api/actions/<id>/approve (murat-agent):** read the caller's name (the person clicking), then `approvals.record_human_decision(con, action_id, approver_name, "approve"|"reject", note)`. It raises `PermissionError` if that person is not on the route (approver, co-signer, deputy, chain), and for multi-signer actions returns `status: pending, waiting_for: [...]` until all have approved. Only when `status == "approved"` call the dispatcher.
3. **mail-agent `actions.on_approve(con, action, approved_by)`:** before sending, `ev = approvals.evaluate(action, now)`. Send if `ev["mode"] == "AUTO"` (pass `approved_by=f"delegation:{ev['delegation_id']}"`) or if a human decision was recorded for the action; never send on NEVER/ESCALATE without `record_human_decision`. Record the AUTO decision with `approvals.submit` (it logs `decided_by='delegation'`).
4. **Harness:** `approvals.policy_check(actions, now)` returns `{"violations": [...], "ok": bool}` in the same shape as `harness.policy_check` (rule `approvals`): flags NEVER actions and approvals claimed by someone who is not on the route. Merge its violations into the harness result.
5. **Timers:** call `approvals.escalate_due(con, now)` every minute (scheduler or the orchestrator tick). It returns overdue pending actions with `next_approver`, `reminder` text (EN) and logs one `system-escalated` row per step. `approvals.reminder_text(action, ev)` also gives the AUTO notification ("FYI ... under your delegation DEL-001").
6. **Audit:** `approvals.log_rows(con, action_id?)`.
