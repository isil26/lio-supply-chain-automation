# Agent live runs

- **2026-11-21 art_book:** live model `gpt-4.1-mini`; real cost **$0.057892**; **130,117 input tokens** and **3,653 output tokens**.
- Trace: `art_book_live.json`. It contains model-visible summaries and tool calls; API keys and authorization data are omitted/redacted.
- Observed hallucinated numeric values: **0**.
- The run delegated to analyst, verifier, planner and chaser. It used deterministic evidence tools and kept outbound sending behind the approval gate; no supplier email was sent.
