# 3-minute pitch + demo script (T8, owner: nick). ALL NUMBERS come from docs/NUMBERS.md (single source). Assumptions marked [A]

## Story in one line
"SAP shows the Collector's Edition fine. It isn't: an 80,000-vs-8,000 art-book booking and a failed statue lot are invisible to it. Our agents read the paper SAP never sees."

## 0:00-0:30 Problem (hook), spoken (about 80 words)
"Sunday, 8 p.m. Soony's Grand Heist launches: 640,000 standard boxes, 72,000 numbered Collector's Editions, one warehouse in Hamburg. Procurement told us: 'We find out at the dock.' SAP shows the Collector's Edition fine. It isn't. A goods receipt booked 80,000 art books where 8,000 were ordered, and a handwritten correction on the delivery note says so. A statue lot failed inspection but still counts as stock. We read the paper SAP never sees. Watch."
(Do NOT say "SAP says Soony is fine": SAP already shows game card, case and magnet gaps; what it hides is art book and statues. Game card 128 GB is the first line stop.)

## 0:30-2:15 Live demo (one storyline; start the demo early)
Dr. Vogt told us two things: a missing Collector's copy costs Soony EUR 120 (Standard EUR 32), and she does not want another dashboard. So the demo is a list of actions.
1. **What SAP hides** (10 s): art book 80,000 booked vs 8,000 ordered (handwritten correction, click the scan and quote); statue lot failed inspection but counts as stock; sleeves split across revision B and C.
2. **The action list** (40 s): five actions, each with owner, deadline, euros at stake: Hamburg dock slot + early customs for the 28,000-card air lot (about EUR 1.05M avoided, Katrin Jansen), collect the 350,000 cases (Raj Patel), protect the Collector's Edition with art books and statues (about EUR 232,000 net), statue exception (Daniel Okafor + Head of Procurement), sleeve revision (Marketing). Release Gate shows GO / HOLD / HUMAN per part.
3. **A new drop arrives** (30 s): the list re-ranks, the agent drafts the supplier email in the supplier's language and the internal request; the numbers it quotes are checked against tool results.
4. **A human approves** (15 s): one click; PP-07 approver named; nothing binding sent without it.

## 2:15-2:45 How it works (one slide, keep it honest)
Deterministic tools produce every number (forecast, optimizer, gate); LLM agents read documents (handwriting, Polish/Korean/Chinese), draft, and plan; a guard harness blocks invented numbers, uncited claims and unapproved sends; recorded real agent runs replay offline. Say "a team of tool-using agents with a human gate", not "autonomous".

## 2:45-3:00 Business case
"About EUR 1.95M of refunds are at stake this weekend (EUR 120 per Collector's copy, EUR 32 per Standard). One action, the Hamburg dock slot, avoids about EUR 1.05M. We would charge a fraction of one launch's exposure [price to decide]. Same problem in consoles, consumer electronics, seasonal retail."
Honest caveats to say if asked: exposure, not forecast of refunds; Standard EUR 32 to be confirmed; dock fee and 4-hour handling are assumptions.
