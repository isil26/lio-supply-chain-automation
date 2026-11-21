# OVERVIEW (PUBLISH EVERYTHING: if it is not on GitHub it does not exist for the team or the jury) — where we are (Sat 21 Nov, 16:10). Update this file when the picture changes.
Deadline: **Sun 22 Nov 12:00 submission** (prototype, deck, video <= 3 min, code + README). Demos from 14:00. Vogt office hours **Sat 19:00**.

## The goal
Convince the jury in 3 minutes that our agents do real work (read, decide, act, escalate) on Soony's messy data, with a business case Soony would pay for. Criteria: pitch that sticks, business case, technical depth (agents, nothing hardcoded, copes with new drops), taste.

## DONE and verified
- Data bridge (portal API, SHA-256 change detection), ingestion, document extraction (282 docs, 0 errors), readiness engine (Monte Carlo + sensitivity), chaser, decision options, orchestrator + React UI, hosted Vercel preview with password.
- Demo flow passes end to end offline (`scripts/demo_check.sh`, about 80 s). Drop-robustness patches applied (T32).
- Verified findings: art book 5,900 short (80,000 vs 8,000 booking), statue 3,400 short (failed lot), game card 6,800 short, case at terminal, magnets fitted by box supplier. Single number set in docs/NUMBERS.md.
- Pitch (true hook), deck (6 slides), research (WIN_PLAN, RESEARCH_2, GAME_THEORY, REDTEAM, ARCHITECTURE_REVIEW), hidden findings (11), drop robustness matrix.
- Multi-agent system skeleton: runtime, 16 tools, 5 agents (triage, analyst, verifier, planner, chaser), 6 simulated suppliers, knowledge pack, guard harness. First REAL LLM run (gpt-4.1-mini): 27 tool calls, numbers correct, nothing sent, $0.09. OpenAI key in gitignored .env only.

## IN PROGRESS (agents running now)
- copilot-wire T47: wire knowledge + harness into live agents and make them pass the harness live (fix weak verifier, "no bottlenecks" mistake, repeated chaser drafts).
- copilot-reader T63: Document Reader agent with vision (handwriting, German/Polish notices, review queue).
- copilot-tools T39: tool layer polish.
- Teammates' agents: gülşah-agent (UI taste pass T28), murat-agent (T5 offer forecast), leo-claude (theme), codex-hosted/access/overseer (Vercel, watcher, assigned open tasks).

## MISSING (honest gaps), ranked by impact on the win
1. **Business case numbers**: cost of a missing copy, pricing. Only Dr. Vogt knows -> office hours 18:00 (docs/OFFICE_HOURS.md). Deck slide 5 still has placeholders.
2. **Live agent quality proven**: agents must pass the harness on real runs (T47). Until then, claim only "deterministic workflow + LLM-assisted steps + human gate".
3. **Agents wired into the product**: nothing in the orchestrator/UI uses the multi-agent team yet (T41 autonomy loop behind a switch; T44 UI trace view; T53 hosted replay of a recorded run).
4. **Unconfirmed facts** for Felix: 350k cases collectable? lid-magnet BOM line real? dock-held game-card lot status? (book his slot, T51).
5. **Forecast number conflict**: calibrated model (CE median 66,100) vs NUMBERS.md (62,550). Decide one (T21).
6. **Real supplier email loop**: still dry-run. Needs a registered sender address in portal Settings (human) and the safe real-mail task (T26).
7. **Demo video and rehearsals**: nothing recorded; no timed rehearsal yet (T24, T49, T59). Humans.
8. **Browser QA**: nobody has verified the UI in a real browser (T48, assigned to leo-claude).
9. **Unseen-drop proof**: re-run drop probes after T63 reader lands; state "tested 20 unseen formats" honestly (T14/T36).
10. **Submission hygiene**: README as entry point, clean-checkout test, secrets sweep, rotate OpenAI key after the hack (T25, T54, T56).
11. **Random events**: the user saw new events nobody else sees (portal notification page / Discord). Rotating watcher needed (T50, codex-overseer assigned).

## Humans must do (agents cannot)
Vogt questions at 18:00 · book Felix/Nils slots · watch portal notifications/Discord · rehearse pitch with a timer · record the video · decide who presents and who drives · rotate the API key after the hack.

## Timeline
- Now to 18:00: finish agent quality (T47/T63), prepare questions. 19:00 Vogt, then update NUMBERS/deck within 30 min.
- 18:30-23:00: wire agents into the app (T41/T44), recorded live runs (T52), hosted replay (T53), pipeline merged end to end (checkpoint 23:00).
- Sun 06:00 feature freeze. 09:00 video recorded. 12:00 submit. 14:00 demo.

## Where to look
coord/STATUS.md (who does what) · coord/TASKS.md + coord/OPEN_TASKS.md (board) · coord/SCHEDULE.md · coord/RESEARCH_INDEX.md · docs/NUMBERS.md · docs/AGENT_ROLES.md · docs/AGENT_EVAL.md.
