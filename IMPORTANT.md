# IMPORTANT — what we are really building, and the new game plan
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

## 3. The product principle: removing the approval bottleneck, safely
Dr. Vogt: she would approve anything that saves the launch and leads to profit (team reports: anything under EUR 2,000,000 for launch recovery; Isil recorded the opposite: she can only give information: UNCONFIRMED in writing). The right answer is not a system that fakes approvals. It is **an approval engine with delegated authority**:

| Mode | When | What the system does |
|---|---|---|
| **AUTO (approved by delegation)** | The action is inside a *recorded* delegation from a named approver (who, what kind of action, value limit, until when), is reversible or information-only, and passes the guards (numbers grounded, cited, within PP-07 for that role) | Executes (e.g. sends an information request or a hold-and-quote request), logs "approved by delegation of <name>, record <id>", notifies the person |
| **ONE-CLICK** | Binding or money commitment inside the approver's PP-07 limit, no delegation | Prepares the full package (what, why, EUR at stake, evidence, draft) and asks the named person for a single click |
| **ESCALATE** | Approver missing/vacant/silent past the SLA, or above their limit, or Quality/Compliance must decide | Routes to the next authority per PP-07 (Category Lead vacant -> Head of Procurement section 6; above EUR 200,000 air freight a month -> CPO the same hour with cost against copies gained), with timers and reminders |
| **NEVER AUTO** | Forged identity, anything above limits, quality releases (Clara Weiss has the last word), anything we cannot ground in data | Blocks and says why |

Rules (non-negotiable): (a) the system never pretends to be a person and never fabricates an approval: AUTO means "approved under a written delegation", logged, visible, revocable; (b) delegations are data (docs/delegations.json), each with a source (a message, a meeting note, an email) and an expiry; (c) the existing harness policy_check enforces PP-07 on every run; (d) a kill switch and a dry-run default stay; (e) unconfirmed delegations (Vogt's pre-approval) count as ONE-CLICK until confirmed in writing.
**Ask Felix (and each approver) for a delegation:** "May the system approve routine information requests and reservation holds on your behalf up to EUR X until Sunday 20:00, with every action logged and you notified?" The answer becomes a delegation record.

## 4. "Handle anything": what that requires
- **Any drop, any format, any language**: new files are classified (triage), read (deterministic parser, then LLM reader with quote validation, then review queue), never silently ignored. Proven today by the 11-file drop and tests/drops (20 probes).
- **Honest limits**: closed options are reported as closed (statues, Boise, PackRight rev C), with the supplier's own words.
- **Everything traceable**: every number comes from a tool or a source; guards block invented numbers, uncited claims, unapproved sends.
- **Always recoverable**: replay mode, recorded agent runs, cold-start rehearsed, one set of numbers.

## 5. The new game plan (now to Sunday 12:00)
**Reframe the pitch (not "we save the launch", but "we remove the pain"):** 30 s: three pain points (bad news late, approvals bottleneck, paper in six languages). 90 s demo: a new drop arrives -> the system classifies it, re-ranks the actions with EUR at stake -> an action gets approved by delegation or one click -> the supplier email goes out -> the real reply comes back and changes the plan. 30 s: how it works (tools + guards + human). 30 s: business case (EUR 120 per Collector's copy, about EUR 1.95M at stake today; time-to-decision from days to minutes).

**Build order (priority):**
1. **P0 Approval engine** (T93): policy-as-code (PP-07, vacancy rules, SLA escalation, delegations) with AUTO / ONE-CLICK / ESCALATE / NEVER; wired into the action queue (T81) and the send path (T83); every decision logged. Agents: Sonnet subagents; `murat-agent`/`mail-agent` integrate.
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
