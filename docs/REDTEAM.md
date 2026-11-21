# REDTEAM: skeptical panel review (3 Lio engineers + 1 jury member)
Based on PITCH_3MIN.md, NUMBERS.md, SPEAKER_NOTES.md, RESEARCH_2.md s5, README, STATUS. Claims we cannot yet prove are tagged **[UNPROVEN]**.

## 1. Scores

| Criterion | Score | Biggest weakness | One-hour fix |
|---|---|---|---|
| Pitch that sticks | 6 | The hook "SAP says Soony is fine" is false by our own NUMBERS.md: naive SAP netting already shows game card, case and magnet short. The true edge is narrower: SAP hides the two Collector's Edition gaps and overstates the others. An engineer who knows SAP will catch this in 10 seconds. The 0:00-0:30 block also never mentions what we learned from Soony staff ("we find out at the dock") as a spoken quote. | Use the rewritten opening in s4. Say "SAP gets the loud problems half right and misses the quiet ones", then show the 0 vs 5,900 art-book contrast. |
| Real business case | 4 | There is no Soony-sourced number. Value at stake is cost of goods, not revenue or penalty, and the "EUR 12k pilot fee" and "<1% of goods at risk" are guesses. "Who else" is one sentence of generic categories. | Ask Vogt one question in office hours (cost of a missed copy on day one). If he gives nothing, show a break-even slide: "one prevented art-book miss = EUR X; we are worth it if P(miss) drops by Y points". Name 2 concrete adjacent buyers, not "every manufacturer". |
| Technical depth | 6 | "Agents that act" is weakened by three facts in our own docs: the LLM is optional (local model, live Ollama run still pending), the supplier reply is a mock, and send defaults to dry-run. A Lio engineer will say the deterministic parts are a script with a UI. | Run one real LLM-read on a stranger file on stage (or a recorded screen of it), and show the activity-feed trace: tool, input, output, source. Say plainly which steps are deterministic on purpose. |
| Taste | 7 | Too much on one screen is likely (SAP-vs-reality, forecast, evidence, feed, threads, 7 options). The jury said a dashboard is not enough, and our hero view is a dashboard until the agent acts. | Make the demo start on the one art-book storyline and hide everything else. The first thing on screen is the 0 vs 5,900 pair. |

Overall: roughly 5.5/10. The finding is real and strong. The pitch oversells it and under-proves the business and agency claims.

## 2. Fifteen Q&A questions

1. **Why is this not a script?** Facts come from OCR/LLM reads with quote validation. Numbers come from MRP and simulation tools, by design. A new file in the portal reruns the state. Show a drop changing the output. [LLM step on a never-seen file: UNPROVEN until Ollama run done.]
2. **SAP already shows game card, case and magnet short. What do you add?** Honest: it shows them wrongly. Game card gap is 6,800 not 34,800, case is 0 not 32,000 (350,000 at Hamburg terminal), and SAP shows no art-book or statue gap while we find 5,900 and 3,400. Both directions matter.
3. **How did you verify 5,900 art books?** GR 5000413065 booked 80,000 vs 8,000 ordered, plus handwritten correction on delivery note WZ-261116-473. Show file and page. Usable stock 19,300 vs need 25,200.
4. **Is the statue finding real?** 5,600-pc lot on quality hold (9/125 defective, limit 3), booked unrestricted. Usable 21,800 vs 25,200 need.
5. **Your forecast says 0% on target and p10=p50. Is it broken?** It is a hard stop at the game-card gap, so spread is small. It is scenario frequency under stated assumptions from 500 runs, not a prediction. Assumptions are overridable.
6. **Extraction accuracy?** 282 documents, 0 extraction errors, delivery-note false alarms 12 to 3 after a fix. No labelled ground truth beyond checked cases; 8 scans routed to human review. Never say "99%".
7. **How do you stop a wrong number going out?** Cited quote must match the source span, every send passes the approval gate, default is dry-run, PP-07 limits (buyer < EUR 50k, category lead < 500k, head of procurement < 2M).
8. **What is actually agentic?** Name them: ingest, doc reader, truth/MRP, chaser, decision. They hand off through shared SQLite state. Chaser drafts in KO/ZH/PL/EN and routes for approval. It does not commit spend.
9. **Supplier reply is a mock. Does it work on a real one?** Parser is deterministic with confidence, low confidence stays open and escalates. Real SMTP/IMAP is wired but gated. [Real round trip: UNPROVEN.]
10. **New data drop, truly unseen?** Tested replays only. T14 robustness work on unseen formats is still in progress. [Arbitrary unseen format: UNPROVEN.] Offer the audience a file.
11. **Why would Soony pay, how much?** Unknown. We have cost of goods at risk (EUR 1.52M STD, EUR 0.87M CE, not revenue). Price is a guess. Say so and show the break-even. [Willingness to pay: UNPROVEN.]
12. **Why not Lio or SAP does this?** They handle the routine path. We sit on the exception layer where the ERP is wrong. Evidence is the art-book gap SAP never saw.
13. **10,000 POs, another ERP?** Built for one site and one launch. Schema is typed and ERP-agnostic in design; first thing to break is OCR throughput. [Scale: UNPROVEN.]
14. **The magnet gap?** Not claimed. BOM line looks like a double count (supplier fits magnets in box CMP-GAM-007); needs Felix Brunner to confirm. We flag, not guess.
15. **What did you not verify?** Magnet line, whether the 350k cases can be collected today, status of the dock-held game card lot, any price but the art-book option (EUR 12,390 is a materials estimate only, no freight or dock slot).

## 3. Five ways the live demo embarrasses us

1. **Wi-Fi or portal sync fails.** Mitigation: run replay mode (`python3 -m src.orchestrator --demo`) on localhost only; no `--online`; recorded 60-second capture open in another tab; static Vercel replay as third fallback.
2. **OCR first run takes minutes / Tesseract language packs missing.** Mitigation: warm the DB and OCR cache before going on stage; never start from empty `store/`; run `scripts/demo_check.sh` an hour before.
3. **Numbers on screen differ from deck (re-run changed something).** Mitigation: freeze NUMBERS.md now; one agreed commit; after any drop, diff the numbers against it before the panel. Deck uses only frozen figures.
4. **Panel asks "is the reply real?" and the mock is obvious.** Mitigation: label it "simulated supplier reply" in the first sentence, before they ask. Show the parser output with confidence and the quote it parsed.
5. **Price card shows EUR 12.4k and someone asks where it came from.** Mitigation: say "materials estimate only, freight and dock slot not included". Never quote a price for the other 6 options. If a hidden finding (T13) lands late, do not add it to the demo.

## 4. Rewritten first 30 seconds (about 80 words)

"Sunday, 8 p.m. Soony's Grand Heist launches: 640,000 standard boxes, 72,000 numbered Collector's Editions, one warehouse in Hamburg. Procurement told us: 'We find out at the dock.' SAP shows the Collector's Edition fine. It isn't. A goods receipt booked 80,000 art books where 8,000 were ordered, and a handwritten correction on the delivery note says so. A statue lot failed inspection but sits as usable stock. We read the paper SAP never sees. Watch."

## 5. What to cut

- **Statement "SAP says Soony is fine" (pitch, speaker notes 0:10).** Replace with the narrower, true claim above.
- **Monte Carlo as a headline.** One line only. "0% on target" invites a fight. Show it as a gauge that moves when the drop lands, no p10/p50/p90 table.
- **Case, magnet and game-card rows on the demo table.** Keep the art-book and statue pair as the story; mention the game card as the first line stop. Magnet stays off stage (unconfirmed).
- **Seven decision options.** Show one (art-book hold) with its price. The rest dilutes.
- **Architecture slide detail (SHA-256, 30-min buckets).** Say the five agents and "numbers come from tools, LLM reads and drafts" in 20 seconds.
- **"Every manufacturer with a hard ship date" business line.** Replace with one named buyer type (collectible and board-game publishers, consumer-electronics launches) only if we can say why they have the same paper problem. Otherwise drop "who else" to one honest sentence.
- **Any claim in the 2:45-3:00 block that depends on the EUR 12k pilot fee or "<1%".** Both are guesses; label them or remove them.

Priority order for the next hour: (1) fix the hook, (2) get a Soony number or show break-even, (3) run one stranger file through the LLM path, (4) freeze numbers and warm the demo DB, (5) cut the demo to the single art-book storyline.
