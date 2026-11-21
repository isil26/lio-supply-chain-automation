# Supplier Chaser

The Supplier Chaser drafts multilingual supplier outreach, requires human approval, persists thread state in SQLite, logs every action, and parses supplier replies.

## CLI

```bash
python3 -m src.chaser.run draft \
  --supplier-id SUP-0019 \
  --component CMP-GAM-006 \
  --po 4500000001 \
  --need "confirmed launch quantity and delivery ETA" \
  --deadline "2026-11-22T20:00:00+01:00"

python3 -m src.chaser.run approve <thread-id>
python3 -m src.chaser.run send <thread-id> --mode dry-run
python3 -m src.chaser.run send <thread-id> --mode mock
python3 -m src.chaser.run mock-reply <thread-id> "Shipped Friday, maybe 5000 pcs"
python3 -m src.chaser.run reply <thread-id> "We shipped 5000 pcs, ETA 2026-11-22"
python3 -m src.chaser.run list
python3 -m src.chaser.run log --thread-id <thread-id>
```

Supplier contact data and `preferred_language` come from `data/suppliers/*/profile.csv`. KO, ZH, PL, and EN templates are supported.

## Approval and sending

Drafts start in `pending`. `approve` changes them to `approved`; only approved threads can enter `send`. Default mode is `dry-run`, and it records the attempt without outbound delivery.

`mock` mode records an outbound message and adds a mock inbox record for demos. Real SMTP is disabled unless `CHASER_REAL_SMTP=1`. Every real send also requires `CHASER_SENDER`, a sender address registered in the portal. SMTP host, port, username, and password are read from `CHASER_SMTP_HOST`, `CHASER_SMTP_PORT`, `CHASER_SMTP_USERNAME`, and `CHASER_SMTP_PASSWORD`. Passwords and other secrets must only be supplied through environment variables.

## State and logs

SQLite defaults to `store/chaser.sqlite` and contains threads, messages, replies, mock inbox records, and `action_log`.

## Reply parsing

`LLMClient` is a pluggable protocol. `DeterministicFakeLLM` provides offline parsing for demos and tests. It extracts status, ETA, quantity, confidence, and `needs_human` from messy replies without network access.
Replies also receive a verifiable commitment score: `none` (0), `date_only` (1), `date_and_quantity` (2), or `document_or_booking_reference` (3). The parser returns `what_to_ask_next`, and the escalation ladder persists R0-R4 state and timestamps in SQLite.

Use `tone="r1_document"` to draft a firm multilingual request for per-lot quantities and a packing list or booking reference. `validate_draft()` blocks binding commitments and disclosures of deadline slack, walkaway alternatives, maximum premium or cost per missing copy. The send path rechecks the stored draft before any outbound attempt.

## Approved actions (T83)

`src/chaser/actions.py` is the send path for the action queue: `on_approve(con, action, approved_by)` emails approved supplier actions through the normal send path and turns internal actions into prepared messages with the euro case; `status(con)` lists them with reply tracking. Try `python3 -m src.chaser.actions demo`.
