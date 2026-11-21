# 3-minute pitch — speaker notes

## 0:00–0:30 — Problem

**0:00–0:10**
"Sun 22 Nov at 20:00, DC-HAM needs 640,000 STD and 72,000 Collector's Editions."

**0:10–0:20**
"Sunday, 8 p.m. 640,000 standard boxes, 72,000 numbered Collector's Editions, one warehouse. SAP shows the Collector's Edition fine. It isn't: 80,000 art books booked where 8,000 were ordered, a failed statue lot still counted as stock. We read the paper SAP never sees. Watch."

**0:20–0:30**
"This is the exception layer: a virtual procurement department whose agents execute the workflow, while a human approves decisions."

## 0:30–2:15 — Live demo

**0:30–0:45**
Open the live control room. Point to SAP-vs-reality: game cards show 34,800 naive SAP short versus a 6,800 usable-stock gap, art books 5,900, statues 3,400.

**0:45–1:10**
Replay a supplier drop. Narrate only: "The system detects a change, reruns cited extraction and recalculates MRP."

**1:10–1:35**
Open evidence. Show the source and quote beside the exception. Explain that LLM extraction/drafting is optional, but the deterministic MRP and Monte Carlo numbers remain tools, not prompts.

**1:35–1:55**
Open the Supplier Chaser draft and approval card. Say: "The agent drafts and routes; it does not send or commit cost without human approval."

**1:55–2:15**
Use the simulated reply and final Plan B card. Keep the fallback open: do not claim unverified prices or lot status. Stop the tour here.

## 2:15–2:45 — Architecture

**2:15–2:25**
"The workflow is sync -> OCR and cited facts -> MRP and Monte Carlo -> chaser and decision copilot -> human approval."

**2:25–2:35**
"A new data drop reruns the state. Every fact carries a source file, page and quote."

**2:35–2:45**
"The numbers are the scenario frequencies from 500 runs. We show assumptions and evidence rather than pretend to predict the future."

## 2:45–3:00 — Business and ask

**2:45–2:52**
"Remaining finished goods at cost: EUR 1,523,200 STD and EUR 869,400 CE. Those are cost of goods, not revenue."

**2:52–2:57**
"We need Dr. Vogt's cost per missing copy and the approved pricing model."

**2:57–3:00**
"Ask: run the replay on the next drop, validate the economics, and scale the virtual procurement department to adjacent fixed-date launches."
