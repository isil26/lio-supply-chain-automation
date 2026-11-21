# IMPORTANT — what we are really building, and the new game plan

> ## THE TEST CASE RULE (read first, applies to every agent)
> **Soony, Grand Heist 6, the six suppliers, Dr. Vogt, Felix Brunner, Katrin Jansen and everyone else in the case are a FICTIONAL TEST CASE.** The product we are building is general: an exception autopilot for procurement. The case is only the data we prove it on.
> - **Never block waiting for approval from a fictional person.** In the test case, approvals are SIMULATED: the approver personas are test personas and their delegations are test delegations (`docs/delegations.json`, records `DEL-TEST-*`, labelled `SIMULATED`). Use them so the full loop (detect -> decide -> approve -> send -> reply) runs end to end without anyone waiting.
> - **Label simulation honestly** in code, UI and docs ("simulated approval, test case"). Never claim a real person approved something.
> - **Real vs test:** the product logic (policy engine, guards, audit log, delegation records) is real and must be correct; the *people and their answers* are the test case.
> - Do not spend time asking humans to confirm fictional approvals in writing. Do not stall on "unconfirmed delegation": in test mode use the simulated delegations; in a real deployment the same engine would demand written delegations.
> - Real constraints remain: no real emails except the registered team sender to the six supplier addresses (information requests), no secrets in git, humans on the team decide scope and priorities.

Written Sat 21 Nov ~20:20 by nick, from what the team learned today. READ THIS BEFORE ANYTHING ELSE. If it conflicts with an older document, this wins.

## 1. The point
**The launch is the example, not the goal.** Whether the fictional Grand Heist 6 launch is saved does not decide the hackathon. The jury scores the system: can it handle anything that arrives, and does it remove the real pain points. The best proof that it works is that it keeps working when the data changes and the answers are inconvenient (today: statues cannot be bought anywhere, Boise cannot help, a sleeve revision was banned mid-afternoon). The system said so plainly and still found the best remaining actions.

**One sentence:** an exception autopilot for procurement: it notices what changed (in any file, any language, any format), decides what matters, prepares the action, gets it approved (or approves it within delegated authority), sends it, and tracks the reply, without a dashboard.

## 2. The pain points we actually saw (from Soony's staff and data)
1. **Bad news arrives late.** "We find out at the dock." Buyers delay bad news because they get blamed.
2. **Approvals are the bottleneck.** The right approver is missing, busy or vacant (Category Lead seat empty), limits are by value (PP-07), dock slots need the site lead, quality has the last word, the CPO wants rush decisions "the same hour". Felix, Paul, Tobias, Katrin, Daniel, Dr. Vogt each hold a piece. People are the slow part.
3. **Half the truth is on paper, in other languages** (handwriting, Polish/Korean/Chinese notices, scans).
4. **Phone tag.** Buyers chase suppliers by phone daily; nobody can read every reply.
5. **Forty dashboards, no actions.** Dr. Vogt and the CPO both said it: not dashboards, "one page per day on what can stop a line".
6. **Systems disagree** (SAP vs tracker vs scans vs supplier confirmations) and nobody owns the reconciliation.

## 3. The product principle: AUTOMATE the routine, delegate once, ask humans only for what is binding
Nobody should chase Felix, Paul, Katrin or Dr. Vogt for every message. The design goal is **zero approval chasing for routine work**:

1. **Delegate once, then run.** Each approver gives ONE written delegation (docs/delegations.json): which kinds of action, up to how many EUR, until when. From then on the system acts without asking again.
2. **AUTONOMOUS by default for routine actions:** information requests, document chasers, reservation holds, quote requests, reminders, replies that only ask or confirm facts, internal notifications. They run immediately, are logged, and the approver is notified after the fact (not asked before).
3. **ONE-CLICK only for the few binding or irreversible things:** purchase orders, money commitments, dock slots, written EXW/forwarder confirmations. The system prepares the whole package; the owner presses one button.
4. **ESCALATE automatically** when the approver is absent, vacant or silent past an SLA (Category Lead vacant -> Head of Procurement section 6; air freight above EUR 200,000 a month -> CPO within the hour, with cost against copies gained).
5. **NEVER AUTO:** quality releases (Clara Weiss has the last word), anything above PP-07 limits, anything we cannot ground in data, anything that would reveal our slack, walkaway or maximum premium.

### Sending in a person's name: allowed only with consent and transparency
Messages to suppliers go out in the name of the responsible Soony role **only under that person's delegation**, with an honest signature (for example: "Felix Brunner, Senior Buyer, Soony · sent by his procurement assistant"). Suppliers reply to the same thread and nothing slows down. We do **not** build anything that makes a third party believe a specific person personally wrote a message when they did not, and we never invent an approval, a signature or an identity. No one-off 'approved by Felix' without his delegation record. This is both the safe design and the one judges can trust.

| Mode | When | What happens |
|---|---|---|
| AUTONOMOUS (by delegation) | routine action covered by a confirmed delegation, under its limit | runs now, logged "sent under delegation of <name>, record <id>", person notified |
| ONE-CLICK | binding or irreversible, or delegation unconfirmed | full package prepared; one click by the named approver |
| ESCALATE | approver silent / vacant / above limit | next authority per PP-07 with timers |
| NEVER AUTO | quality releases, over limits, ungrounded, leaks | blocked, with the reason |
Controls: kill switch (APPROVALS_KILL_SWITCH=1), dry-run default in the demo, audit log, delegations revocable. Unconfirmed delegations (Dr. Vogt's pre-approval) count as ONE-CLICK until confirmed in writing.
**Ask each approver for a delegation** (Felix, Paul Winter, Katrin Jansen, Tobias Brandt, Dr. Vogt): "May the system send routine information requests and reservation holds in your name, with an assistant signature, up to EUR X until Sunday 20:00, and tell you afterwards?"

## 4. "Handle anything": what that requires
- **Any drop, any format, any language**: new files are classified (triage), read (deterministic parser, then LLM reader with quote validation, then review queue), never silently ignored. Proven today by the 11-file drop and tests/drops (20 probes).
- **Honest limits**: closed options are reported as closed (statues, Boise, PackRight rev C), with the supplier's own words.
- **Everything traceable**: every number comes from a tool or a source; guards block invented numbers, uncited claims, unapproved sends.
- **Always recoverable**: replay mode, recorded agent runs, cold-start rehearsed, one set of numbers.

## 5. The new game plan (automation first) (now to Sunday 12:00)
**Reframe the pitch (not "we save the launch", but "we remove the pain"):** 30 s: three pain points (bad news late, approvals bottleneck, paper in six languages). 90 s demo: a new drop arrives -> the system classifies it, re-ranks the actions with EUR at stake -> an action gets approved by delegation or one click -> the supplier email goes out -> the real reply comes back and changes the plan. 30 s: how it works (tools + guards + human). 30 s: business case (EUR 120 per Collector's copy, about EUR 1.95M at stake today; time-to-decision from days to minutes).

**Build order (priority):**
1. **P0 Approval engine** (T93, built): policy-as-code (PP-07, vacancy rules, SLA escalation, delegations) with AUTONOMOUS / ONE-CLICK / ESCALATE / NEVER; next: make routine actions AUTONOMOUS by default under delegation, send with the transparent assistant signature; wired into the action queue (T81) and the send path (T83); every decision logged. Agents: Sonnet subagents; `murat-agent`/`mail-agent` integrate.
2. **P0 Robustness**: surprise-drop tests pass; cold start rehearsed; one demo path; numbers consistent; secrets out of git.
3. **P1 Delegation capture**: delegations.json + a small UI/CLI to record "Felix delegates X up to EUR Y until T"; seed with Dr. Vogt's statement flagged UNCONFIRMED.
4. **P1 Action list as the home screen** (T82) with mode badges (AUTO / ONE-CLICK / ESCALATED) and time-to-decision.
5. **P1 Pitch + deck + video** rebuilt around the pain points (nick), rehearsed 3 times, video recorded by 09:00.
6. **P2 Evaluation**: honest agent pass rates (several live runs per scenario), shown on one slide.
7. **STOP building**: new engines, new visualisations, more option types. Freeze Sunday 06:00.

## 6. Open decisions (humans)
- Supplier email auto-send (mail-agent's decision): allow AUTO only for information-only requests; binding requests stay ONE-CLICK.
- Get Dr. Vogt's and Felix's delegation (and the EUR 2,000,000 statement) in writing.
- Price: share of avoided loss (proposal 5%, see docs/PROFIT_PLAN.md) vs subscription: decide before the pitch.

## 7. Where things are
coord/DEADLINES.md · coord/OVERVIEW.md · coord/OPEN_TASKS.md · docs/NUMBERS.md (baseline after the 19:25 drop) · docs/SUPPLIER_REPLIES.md · docs/PROFIT_PLAN.md · docs/AUTHORIZATIONS.md · docs/OFFICE_HOURS.md · docs/VOGT_BREAKEVEN.md
