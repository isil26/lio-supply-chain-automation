# Real supplier email (team Gmail)

The Supplier Chaser sends only after a person approves each email. Dry-run stays the default. On stage we keep dry-run.

## One-time setup (a human does this)
1. Create a new Gmail account for the team. Turn on 2-Step Verification (Google Account > Security).
2. Create an app password: https://myaccount.google.com/apppasswords, name it "lio chaser", copy the 16 characters.
3. In the hackathon portal, Settings > Mail senders, add the Gmail address and press Add. Suppliers ignore mail from unregistered senders.
4. Hand the address and app password to whoever runs the app, through the team's private channel. Never commit them or paste them into a chat with agents.

## .env on the machine that runs the app (gitignored)
```
CHASER_REAL_SMTP=1
CHASER_SENDER=<team gmail address>
CHASER_SMTP_HOST=smtp.gmail.com
CHASER_SMTP_PORT=587
CHASER_SMTP_USERNAME=<team gmail address>
CHASER_SMTP_PASSWORD=<16-char app password>
SOONY_IMAP_HOST=imap.gmail.com
SOONY_IMAP_PORT=993
SOONY_IMAP_USER=<team gmail address>
SOONY_IMAP_PASSWORD=<16-char app password>
```
Load with `set -a; . ./.env; set +a`, then start the app as usual.

## Safety
- Recipient allowlist (`src/chaser/allowlist.py`): real mail only goes to `@suppliers.juliansibbing.de` (the case suppliers). Override with `CHASER_ALLOWED_DOMAINS` or `CHASER_ALLOWED_RECIPIENTS` only for a self-test address.
- Every send still needs human approval and passes the draft guardrails (no price ceilings, walkaway or deadline slack).
- First real send: one supplier, one approved email, check the Gmail "Sent" folder, then wait for the reply to arrive in the inbox.
- Tests: `python3 -m unittest src.chaser.test_allowlist src.chaser.test_chaser` (needs `data/`, e.g. `cp -R case-data data`). Tests never send real mail.
