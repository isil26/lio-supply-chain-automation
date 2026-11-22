# Manti pitch script (3 minutes)

Deck: [Manti-pitch-deck-final.pdf](../Manti-pitch-deck-final.pdf) · Timing: [TIMING.md](TIMING.md)

## 0:00–0:30 · Problem (slides 1–4)

**[Slide 1]** Hi, we're Manti. Our AI agents read all the paperwork a supply chain produces, find what's really missing before launch, and tell procurement exactly what to do.

**[Slide 2]** Nobody has time to read everything a supply chain produces. For one launch, Soony had 308 files and 93 supplier emails in four languages, and one weekend left.

**[Slide 3]** SAP counts stock that isn't there. It books 80,000 art books when 8,000 arrived. It counts statues that failed inspection. Our starting forecast put about €1.95 million at risk this weekend. Even after 28,000 game cards were flown in, 6,800 are still missing.

**[Slide 4]** Dr. Vogt, Soony's Head of Procurement, told us three things: a missing Collector's copy costs €120, she wants things to act on rather than another screen to watch, and named signers approve. So our screen opens with a list of actions, not charts. Felix asked for a product that keeps working after this weekend, at any company. So we built agents that act.

## 0:30–2:15 · Live demo (slide 5, then switch to soony-manti-live.vercel.app)

**[Slide 5, then switch to the browser]** Here it is, live.

**[Dashboard: forecast, "The race to 20:00"]** This is the launch right now: how many copies we'll pack by Sunday 20:00, and which part stops the line first. It reruns whenever a new file arrives.

**[Click a red number → source evidence]** Every number has a source. Here is the delivery note with the handwritten correction that SAP never saw.

**[Agents page: the live graph]** These are the agents at work. One reads, one checks against SAP, one verifies and rejects facts without a source, one plans, and one chases suppliers.

**[Dashboard: Supplier offers → open an email thread]** These are real emails. The agent wrote to a Polish supplier in Polish, and the reply is translated back.

**[Upcoming decisions → Approve → "Review approval"]** Each decision shows who signs, the deadline and the euros at stake. I click Approve, see exactly which email goes out, and confirm. Nothing binding leaves without a person.

**[Activity Log]** Every action is logged with who did it.

## 2:15–3:00 · Business (switch back to slide 6, 45 seconds at most)

**[Slide 6]** Soony had €1.95 million at risk. We charge 5% of the loss we avoid, about €42,000 per launch. Running the agents costs us $10 to $40, and Soony keeps around €800,000, a 20× return. Every company with a fixed launch date has this problem: games, electronics, toys, cosmetics, limited drops. The same agents plug into their ERP, suppliers and approvers. Thank you.

**[Jump to slide 9, the team, and leave it up for Q&A]**

## Likely jury questions

**What happens when a new data drop arrives?** Every file is checksummed. When one changes, the agents reread it, rerun the forecast and re-rank the decisions automatically. The site shows it live.

**Can the AI make a mistake that costs money?** Plain supplier questions go out automatically. Anything binding, like an order, air freight or a quality release, needs one click from the named signer. Numbers without a source are rejected.

**How did you get to €42k and €840k?** €120 per Collector's copy is Dr. Vogt's figure. €840k is our model of the best five actions, which cost €31.5k. The fee is 5% of the loss avoided. Details are in docs/BUSINESS_CASE.md.

**What does it take to onboard another company?** Connect their ERP export, their supplier list and their approval rules. The agents don't depend on what the company sells.

**Why hasn't anyone done this?** By hand it takes about 228 hours per launch, which is 9 to 10 people in a 48-hour crunch. Reading scans and multilingual email for cents has only just become possible.
