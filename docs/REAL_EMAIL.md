# Real supplier email (team Gmail)

Since 21 Nov 18:45 (Gülşah's decision) mail-agent sends supplier emails automatically in live mode (`CHASER_REAL_SMTP=1`, not `--demo`): each orchestrator cycle it drafts reminders and negotiation emails, then sends every draft (`src/chaser/autosend.py`). No cap per cycle (suppliers are simulated). Kept: supplier allowlist, guardrails, anti-spam (while a supplier hasn't answered, one email per 30 min, `CHASER_AUTO_COOLDOWN_MIN`; after a reply we answer at once; never the same text twice to the same supplier). Stop it with `CHASER_AUTO_SEND=0`. The demo replay keeps dry-run and the approval step.

**Send modes (IMPORTANT.md §6, 21 Nov 20:50).** AUTO is only for information requests (status, quantity, date, documents, quotes, reminders, answers): they go out without a click and the activity log says "AUTO (information request)". Anything binding (accepting a price or offer, an order, a reservation on our terms; detected in EN/PL/KO/ZH by `autosend.binding`) is ONE-CLICK: it is sent only after a named person clicked, either Approve in the Supplier offers table, an approved action (T83/T94), or `POST /api/mail/<id>/approve {"by": "<name>"}`. Until then the email stays `awaiting click` (list: `GET /api/mail/held`) and the log says "ONE-CLICK needed". Sent binding emails are logged "ONE-CLICK approved by <name>".

## One-time setup (a human does this)
1. Team Gmail: manti.starthackathon@gmail.com (created 21 Nov). Turn on 2-Step Verification (Google Account > Security).
2. Create an app password: https://myaccount.google.com/apppasswords, name it "lio chaser", copy the 16 characters.
3. In the hackathon portal, Settings > Mail senders, add the Gmail address and press Add. Suppliers ignore mail from unregistered senders.
4. Hand the address and app password to whoever runs the app, through the team's private channel. Never commit them or paste them into a chat with agents.

## Settings
The team Gmail settings, including the app password, are tracked in the private repo at `deploy/mail/team-gmail.env` (approved by Gülşah, 21 Nov) and load automatically. To send for real, a person still sets `CHASER_REAL_SMTP=1` and approves each email. Set `CHASER_NO_TEAM_MAIL=1` to ignore the file.

## Equivalent .env (only if you want to override the tracked file)
```
CHASER_REAL_SMTP=1
CHASER_SENDER=manti.starthackathon@gmail.com
CHASER_SMTP_HOST=smtp.gmail.com
CHASER_SMTP_PORT=587
CHASER_SMTP_USERNAME=manti.starthackathon@gmail.com
CHASER_SMTP_PASSWORD=<16-char app password>
SOONY_IMAP_HOST=imap.gmail.com
SOONY_IMAP_PORT=993
SOONY_IMAP_USER=manti.starthackathon@gmail.com
SOONY_IMAP_PASSWORD=<16-char app password>
```
Load with `set -a; . ./.env; set +a`, then check the mail agent (signs in, sends nothing):
```
python3 -m src.chaser.mail_agent check
```
Then start the app as usual (`python3 -m src.orchestrator --online`). In the control room, review a supplier draft and confirm Send. Replies are read from the inbox on each cycle.

## The mail agent
`mail-agent` is the team mailbox side of the Supplier Chaser: it sends approved supplier emails from the team Gmail and reads the replies back into the control room. Code: `src/chaser/mail_agent.py` (health check), `src/chaser/__init__.py` (send/poll), `src/chaser/allowlist.py` (supplier-only).

## Safety
- Recipient allowlist (`src/chaser/allowlist.py`): real mail only goes to `@suppliers.juliansibbing.de` (the case suppliers). Override with `CHASER_ALLOWED_DOMAINS` or `CHASER_ALLOWED_RECIPIENTS` only for a self-test address.
- Manual sends require confirmation. Routine live sends use the T78 automatic mail policy. Draft guardrails cover price ceilings, walkaway positions and deadline slack.
- First real send: one supplier, one approved email, check the Gmail "Sent" folder, then wait for the reply to arrive in the inbox.
- Tests: `python3 -m unittest src.chaser.test_allowlist src.chaser.test_chaser` (needs `data/`, e.g. `cp -R case-data data`). Tests never send real mail.

## Best supplier, split orders, negotiation, reminders, attachments (T74-T77)
Code: `src/chaser/negotiate.py` (model), `src/chaser/supplier_facts.py` (case-file facts), `src/chaser/followup.py` (reminders, attachments). Control room card: `web/src/suppliers/BestSupplier.tsx` via `GET /api/suppliers/best`; its button calls `POST /api/suppliers/drafts`, which only creates drafts.

**Adaptive model.** Per material it first reads the situation:
- *time pressure* (0-1): hours to the cut-off (4 days out = 0) and how little slack the offers leave;
- *price spread* (0-1): how far apart the offered prices are (25% apart or more = 1).
It then shifts the weights: time pressure adds weight to on-time chance, delivery buffer, shipping/customs risk and approval status; price spread adds weight to price and payment terms. Mode is reported as time-critical, cost-critical or balanced. Offers under a minimum on-time chance (30%, rising to 70% under full time pressure) are backups only.

Factors (each 0-1, source in brackets): on-time chance (stated ETA, adjusted by `src/decide/reliability.py` PO history when available), quantity covered (reply), price in EUR (reply; FX assumed, `CHASER_FX_EUR`), delivery buffer (p90 ETA vs cut-off), proof (none/date/date+qty/shipping document or attachment), reply speed (message times), track record (PO history), shipping and customs risk (profile.csv incoterm + country outside EU), approval status (profile.csv qualification_status; conditional = PP-07 release), minimum order (components.csv moq), payment terms (profile.csv payment_terms), single-supplier dependence (components.csv primary + master critical flag).

**Split orders.** If no eligible supplier covers the need, the best eligible ones are combined; uncovered units are reported.

**Negotiation levers** per picked supplier: price (anchor = agreed contract price from components.csv if the offer is above it, else the cheapest other on-time offer, else 5-10% depending on price spread), earlier delivery and an early partial shipment (buffer under 24 h), free express (time-critical), smaller minimum order (need below MOQ). EN/PL/KO/ZH, guardrail-checked, saved as drafts.

**Reminders.** `python3 -m src.chaser.mail_agent remind [--save-drafts]`: wait before reminding = hours left / 6, between 2 and 12 h. Two reminders, then the feed says to call.

**Answering replies.** Every real supplier reply that we have not answered gets one answer draft in the supplier's language (`followup.answer_replies`, run by autosend): part shipment + earliest date if they cannot deliver, pickup details for EXW/forwarder answers, the missing quantity/date/price, or the packing list/booking reference. The Hwaseong card and Karton book threads are answered by `supplier_loop.py` instead.

**Attachments.** Replies' attachments are stored in `messages.parsed.attachments` (name, type, kind: air_waybill / bill_of_lading / packing_list / invoice / delivery_note, text from PDF or text files). Any recognised shipping document counts as the strongest proof. Unreadable files are flagged `needs_review`.

## Game-card and Karton follow-ups

In **Agents**, the supplier actions show the matched reply, dispatch or pending status, and any PP-07 review. The game-card loop sends one same-thread request for outstanding shipment details. A complete reply needs no such request. A reply that moves the lot beyond the packing cut-off blocks the stale dock recommendation and raises launch recovery for review.

The Karton loop keeps the art-book offer separate from the small-lot exception. It waits two hours after a pending exception reply before requesting the status once on the existing thread. A firm denial routes to alternate sourcing review. The operational worker can read the verified mailbox checkpoint specified by `SOONY_MAIL_HISTORY_DB`. It reconciles those messages before evaluating outbound actions.

Routine live email uses the existing `CHASER_REAL_SMTP` and `CHASER_AUTO_SEND` settings and supplier allowlist. Distinct component requests can go to the same supplier in one cycle. A pending reply delays another message for the same recipient and component for up to 30 minutes. Set `CHASER_AUTO_COOLDOWN_MIN=0` to remove the wait. Duplicate bodies for the same recipient remain suppressed, and `CHASER_AUTO_MAX_PER_CYCLE` still sets an optional cap for the general mail queue. The Mac demo uses dry-run transport. The verified mailbox and one-shot replay packaging never dispatch. Booking a slot and issuing a purchase order still need PP-07 approval.
