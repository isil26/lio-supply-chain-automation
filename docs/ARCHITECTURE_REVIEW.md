# Architecture review (arch-review, 21 Nov)

Scope: README, src/orchestrator/__main__.py, src/docs (providers, extract, pipeline), src/chaser (agent, llm), src/decide, DROP_ROBUSTNESS, REDTEAM. Topics already in coord/RESEARCH_INDEX.md (game theory, Lio positioning, robustness probes, red team scores) are not repeated. Tags: [V] read in this repo or opened online, [A] judgement.

## Verdict

The architecture is correct for the business problem (numbers from tools, language from models) and weak on the one thing the jury scores as "agents decide": no component chooses its own next action with an LLM, and the LLM is off by default. We should not rebuild. We should add one real, visible agent loop on top of the existing tools, in about 6 hours. Everything below serves that.

## 1. Multi-agent system or pipeline?

Blunt answer [V]: it is a pipeline. `Loop.cycle()` in src/orchestrator/__main__.py runs a fixed sequence under one `threading.Lock`: ingest, extract, reconcile_handwriting, readiness, choose, chaser.draft, save_state, poll, expire. The "agents" (Data Bridge, Document Agent, Readiness Engine, Decision Copilot, Supplier Chaser) are labels written by `chaser.activity()`. They do not choose tools, plan, or call each other; they are functions invoked in code order and they hand off through `save_state(con, "truth" | "options" | ...)`. The chaser's "ladder" is `next_step()`, an if/elif on status, commitment_score and sent_count. `choose()` in src/decide builds a hard-coded menu of option kinds. The LLM appears only in two optional places: `extract_with_model` (text/vision, quote validated) and `parse_reply` (default `DeterministicFakeLLM`, a regex parser). Chaser email drafts are `TEMPLATES[language][tone].format(...)`, not generated text.

What a Lio engineer would call it: a deterministic workflow with an LLM-assisted extraction step and a human approval gate. That is a respectable and arguably correct production design (Anthropic: "workflows orchestrate LLMs and tools through predefined code paths", agents "dynamically direct their own processes" [V, anthropic.com/engineering/building-effective-agents]). The problem is the wording, not the design.

Honest description to use: "Five specialised services share one evidence store. Deterministic tools compute every number. A model reads what code cannot (Korean, Chinese, Polish notices, handwriting) and every model claim must quote the source or it is rejected. Nothing is sent or committed without a named human approver." Do not say "autonomous agents" or "multi-agent" unless item A below ships. Note REDTEAM Q8 already answers "what is agentic" with the five-service list; with the current code, a sharp judge will read that as labels.

## 2. Agent loop quality against current practice

| Property | State today | Gap |
|---|---|---|
| Tool use | Tools are Python functions called by fixed code | No model-selected tool call anywhere |
| Shared state | Good: SQLite `state` rows, `pendingEvents`, `pendingRecompute` flags, activity feed with citations | None important |
| Planning | None. Option menu and ladder are rules | No plan object, no replanning on a drop |
| Verification | Strong for extraction (quote must appear in OCR/PDF text), approval gates, PP-07 limits | Verification exists only around LLM extraction, not around decisions |
| Memory across drops | `before = get_state(con,"truth")` and `drop_summary()` diff old/new truth; SHA cache | Memory is a diff, not a record of what an agent concluded last time |
| Human gates | Good (every send, PP-07 signers) | Fine |

Pattern match: we match prompt chaining without the LLM (fixed sequence with checks between steps) and a deterministic form of routing (`tone_for_state`, `next_step`). We do not match orchestrator-workers or evaluator-optimizer.

Single pattern to add for the most credible "agents decide" evidence in 6 hours: orchestrator-workers, in its smallest honest form, a **triage agent with a closed tool set**. After each drop, a model receives (a) the drop diff and truth summary, (b) the list of open issues, and must emit a JSON plan: which existing tools to call, in which order, with what arguments, and why (e.g. `run_sensitivity(part)`, `draft_chase(supplier, po, rung)`, `request_review(file, reason)`, `quote_air_freight(part, qty)`). Code validates each call against a whitelist and an argument schema, executes, feeds results back for at most 3 rounds, then stops. Every step lands in the activity feed ("Triage Agent chose X because Y"). Reasons for choosing this over evaluator-optimizer: it produces visible decisions and tool use; the evaluator loop would only polish email text. Add a deterministic fallback plan (today's `cycle()` order) when no model is configured or validation fails, so the demo cannot break. Plan-and-execute is a close cousin: this is exactly a plan step plus code execution; call it that.

The guardrail story stays intact: the model can only call tools that are already side-effect-free or that create drafts and review items. Sending, ordering and spend remain human-gated.

## 3. Where an LLM genuinely beats code here

1. Multilingual notices and contracts (Korean, Chinese, Polish): regex and templates fail on clause meaning (who owes what, which dates). Already wired via `LocalTranslationClient`, off by default.
2. Handwritten delivery-note corrections: Tesseract plus crop checks exist; a vision model with the cell crop is the better reader, validated against independent OCR.
3. Supplier reply parsing: the current `DeterministicFakeLLM` matches "delay", "late", "confirmed". It misreads "we cannot ship Friday but can ship Monday" (matches "cannot", returns blocked) [A, from reading the regexes]. A model with a JSON schema is clearly better.
4. Email drafting in the supplier's language that references the actual conflict and quotes the evidence: templates cannot adapt to "what we need" beyond a format field.
5. Conflict explanation for the approver (why ERP and receipt disagree, one paragraph with citations).

Where it does not beat code: MRP, the Monte Carlo, thresholds, approval routing. Keep those deterministic and say so.

Minimal visible, validated LLM step (one new module, `src/llm/client.py`, about 120 lines):
- One `complete_json(task, schema, prompt, images=None)` function. Provider chosen by env: `SOONY_LLM_PROVIDER=ollama|openai_compat|anthropic|none`. Ollama and any OpenAI-compatible endpoint use the same `/v1/chat/completions` call already in `providers._complete`; the API variant only changes URL and an `Authorization` header from an env var (today `_complete` rejects non-loopback hosts; add an explicit `SOONY_LLM_ALLOW_REMOTE=1` and keep the default).
- Validation: schema check (jsonschema or hand-rolled), quote must be a normalised substring of the source text (reuse `validate_facts`/`compact` from src/docs/extract.py), numbers in the quote must equal numbers in the value. Reject and log otherwise.
- Cache: key = sha256(task + model + prompt text + image bytes); table next to `docs_cache.sqlite3`. Cached answers keep original timestamps (already the convention). This makes the demo replayable offline and bounds cost.
- Cost awareness: log tokens and a cost estimate into the activity feed; call the model only for pages where deterministic parsers returned nothing or flagged review; truncate long text; per-cycle call budget (env, default 20).
- Config drift: README documents `SOONY_LOCAL_MODEL`/`SOONY_VISION_MODEL`/`SOONY_LOCAL_URL`; coord/HANDOFFS.md documents `SOONY_LLM_MODEL`/`SOONY_LLM_VISION_MODEL`/`SOONY_LLM_URL`/`SOONY_LLM_PROVIDER`. Pick one set before the demo; a judge following the README may silently get deterministic mode.
- Live Ollama has never been run in this workspace (HANDOFFS, STATUS). This is the biggest unproven depth claim; run it before building more.

## 4. Robustness to unseen formats

Observed in docs/DROP_ROBUSTNESS.md [V]: unfamiliar inputs fail silently. German notice gave generic fields without a warning; `.eml` files are ignored entirely; a re-columned order confirmation extracted only the PO with no warning; a corrupt PDF showed a successful drop banner. The common cause is that "no facts extracted" is treated as success.

Architecture change: introduce a **coverage contract per file** and a three-tier ladder.
1. Known parser matches and yields the required fields: accept.
2. Otherwise fallback extractor: a model proposes `{field, value, quote}` entries against a field registry (the fields we actually consume: PO, part, qty, ETA, status, dates, clause types). Every entry passes quote validation (section 3). Accepted facts are stored with `method="llm_fallback"` and lower confidence; they may display but must not change the forecast until approved. The forecast-changing allowlist stays small.
3. Otherwise a review-queue item with reason, file, and what was tried. Never a green banner.

Concretely: a `coverage` field on each document row (`full | partial | none`) computed by comparing extracted keys with the expected keys for its `kind`; `.eml` and unknown extensions routed to the same queue instead of being skipped; a dashboard panel "Needs a human" fed by `review_reasons`. The patch already proposed in DROP_ROBUSTNESS (surface rejections, flag `unparsed_confirmation`, shared CSV decoder) is the right cheap start; apply it first. Schema discovery for tabular files (header to canonical-field mapping by alias plus model suggestion, confirmed by value-type checks) is a larger task; limit to the alias table plus a review item when a required column is missing, as is done now.

## 5. State and consistency risks (single process, SQLite)

- `Loop.cycle()` holds `self.lock` across the whole run, including `bridge/sync.py` (up to 180 s) and OCR. HTTP handlers that need the lock (promote_drop, sync trigger) block for that long during a demo [V for the lock structure; A for the handler timing, I did not read the handler body].
- Multiple connections: ingest/store sets WAL and `timeout=30`; `ChaserStore.connect()` opens plain `sqlite3.connect(self.path)` with default 5 s timeout and no WAL pragma [V]. Under a write from the cycle plus a UI approval, "database is locked" is possible. Cheap fix: one shared `connect()` with WAL, busy_timeout 30000, used everywhere.
- Recompute atomicity: `pendingRecompute` is set, then truth, options and drafts are computed outside one transaction, then saved in a second one. A crash in between leaves `pendingRecompute=True`, which is the intended retry, so this is acceptable. But `choose()` reads docs while `extract` may be mid-write only if two cycles overlap; the lock prevents that.
- Option ids are hashes of option content (`hashlib.sha256(version)`), so an approval attached to an id silently becomes stale when the numbers move after a drop. That is correct behaviour if the UI says "re-approval needed"; check that it does.
- DROP_ROBUSTNESS findings that are consistency bugs rather than format issues: same file copied to a second path doubles stock (120 instead of 60); header-only stock CSV published as empty snapshot and created a false air-freight option; UTF-16 PO CSV passed ingest but crashed document reconcile. Header-only/zero-row snapshots should be rejected like zero-byte files.
- The docs pipeline uses `fcntl.flock`, fine on macOS/Linux, unavailable on Windows. Irrelevant for the demo laptop.
- Demo risk: replay mode copies `docs_cache.sqlite3` with the backup API, good. Never run the demo from an empty `store/`.

## 6. Five changes, ranked by impact over effort

Each is sized for another agent with Copilot, under 3 hours.

**A. Triage agent with closed tool set (highest impact, ~3 h).**
Files: new `src/agent/triage.py`, `src/agent/tools.py`; edit `src/orchestrator/__main__.py` (call after `choose()` when a drop changed truth), `src/orchestrator/control-room.html` (render steps). `tools.py` wraps existing functions with JSON schemas: `get_part_status`, `run_sensitivity` (src/truth/sensitivity), `list_open_issues`, `draft_chase` (chaser.draft), `queue_review`, `explain_conflict`. `triage.py`: loop of at most 3 model turns, validate tool name and args, execute, append result, record each step via `chaser.activity(con, "Triage Agent", ...)` with the stated reason; persist plan and outcome in state `agentRuns` so the next drop receives "last run said X". Fallback: fixed plan when provider is `none`. Test: scripted fake model returns a plan, assert only whitelisted tools run and a bad tool name is rejected.

**B. Shared LLM client with validation, cache and cost log (~2 h, prerequisite for A and C).**
Files: new `src/llm/client.py`; edit `src/docs/providers.py` to delegate `_complete`; edit `src/chaser/llm.py` to add `LLMReplyParser` using it with a ReplyParse schema and a quote check, selected when a model is configured, otherwise the existing fake. Unify env names in README and HANDOFFS. Then run once on the real German notice and a handwritten crop, save the activity trace for the deck.

**C. Fallback extractor and coverage contract (~3 h).**
Files: `src/docs/pipeline.py` (compute `coverage` per row; call fallback when `partial|none`), `src/docs/extract.py` (reuse `validate_facts` with method `llm_fallback`), `src/docs/pipeline.py` source discovery (include `.eml`, parse with stdlib `email`, route body and attachments to the same extractor), `src/orchestrator/__main__.py` (apply the DROP_ROBUSTNESS diff for review items and `sync.error`), React/standalone: "Needs a human" panel. Rule: fallback facts do not move the forecast until a human approves.

**D. LLM-drafted chaser with validator (~2 h).**
Files: `src/chaser/agent.py` (`draft()` tries a model draft in the supplier language, falls back to `TEMPLATES`); `src/chaser/guardrails.py` (check the draft contains PO, component, deadline, no invented numbers, no price or commitment language). Keep the human confirm. Show the validator result next to the draft. Evaluator-optimizer in miniature: if validation fails, one retry with the error text, then the template.

**E. State hardening (~1 h).**
Files: `src/chaser/store.py` (WAL, busy_timeout via shared `connect`); `src/ingest` (reject header-only snapshots; dedupe identical lots by content hash across paths); `src/orchestrator/__main__.py` (move `bridge/sync.py` subprocess outside the lock, apply results after). Low glamour, removes demo-day failures.

Order: B, A, C, then E, then D if time remains. Do the live Ollama run (B) first; every other claim depends on it.

**What not to build in 20 hours:** a generic multi-agent framework (LangGraph, AutoGen) or message bus; autonomous email sending or purchase commitments; vector database or RAG over the data (the corpus is small and structured); fine-tuning; model-generated forecasts or numbers; a second UI; full schema discovery for arbitrary ERP exports; multi-process or Postgres migration; more option kinds in `choose()` before the existing ones are proven. Also do not cite papers on slides that nobody opened; RESEARCH_INDEX already flags GAME_THEORY names as unverified.

## What to say tonight

"Deterministic tools for every number, a model for everything written in a language or by hand, a triage agent that picks which tools to run after each drop, and a human for every irreversible step. When a file is unfamiliar, we say so and route it to a person instead of guessing." That is true after A, B, C; before them, drop the word "triage agent" and the claim about unfamiliar files.
