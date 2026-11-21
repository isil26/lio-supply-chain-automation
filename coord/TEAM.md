# TEAM — humans + agents working together
Humans: Nick Federspiel, Murat, Gülsah, Leo, Isil Özyigit (team "Manti"). Fill in who owns what below.

## Human roles (assign in the first 10 min; edit this table)
| Person | Owns | Also |
|---|---|---|
| ? | Product/pitch/deck/business case (T8), office-hour questions | |
| ? | Backend + agents (T3-T5, T7) | |
| ? | Data/extraction (T1-T2) | |
| ? | UI/UX + demo (T6) | |
| ? | Supplier emails/chaser (T4) + QA | |

## How we communicate
1. **Before you start anything:** `git pull`, read `coord/STATUS.md` + `coord/INBOX.md`.
2. **Claim** work in `coord/TASKS.md` (owner = your name or your agent's name). Humans and agents use the same board.
3. **Ask another person/agent** via `coord/INBOX.md` (one line). Urgent: Discord #lio.
4. **Everyone works on `main`.** No branches or PRs. It works because each person or agent owns separate directories (see `coord/TASKS.md`). `git pull --rebase origin main` before every commit/push, commit small and often, stage only your own paths, never force-push.
5. **Sync points:** every 2 hours post one line in STATUS.md per person. Deadline checkpoints: Sat 23:00 pipeline end-to-end on real data; Sun 06:00 feature freeze; Sun 09:00 demo video recorded; Sun 12:00 SUBMIT.
6. **Data drops:** whoever notices runs `python3 bridge/sync.py`, then logs the change in FINDINGS.md.
7. **Agents:** if you run your own Claude/Codex/Copilot, tell it to read `AGENTS.md` first, and make sure its task is claimed on the board so we don't duplicate.
8. Never commit `.soony_token`, `data/`, `store/`. Share the token via the portal Settings page, not git or chat.

## Note
This repo is public; the Soony data is fictional but the brief says not to share it outside the team. Never commit raw data (`data/`), the token or `store/`.

## Setup for a new teammate
```
git clone https://github.com/isil26/lio-supply-chain-automation && cd lio-supply-chain-automation
echo '<team token from portal Settings>' > .soony_token
python3 bridge/sync.py     # fills data/
```
