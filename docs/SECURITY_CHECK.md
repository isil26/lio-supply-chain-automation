# Security and secrets check (T54)

Run by isil-agent on Sat 21 Nov 2026, about 18:30 CET, against `main` (`387bde0` plus later commits). No secret values are written in this file.

## Verdict
The repo is safe **while it stays private**. It is **not safe to make public** as is: two live credentials and the full Soony case data are committed. Decide before submission how judges get access (see "Before submission").

## Checklist
| Check | Result | Notes |
|---|---|---|
| Repo visibility | OK, private | Anonymous GitHub API returns 404. |
| API keys in tracked files (OpenAI, GitHub, AWS, Google, private keys) | OK, none | Pattern scan of all tracked files outside `case-data/`. The one hit, `deploy/vercel/recording.py:14`, is a redaction regex. |
| API keys anywhere in git history | OK, none | Same patterns over every commit on every branch. |
| `.soony_token`, `.env`, `data/`, `store/` tracked | OK, never | All in `.gitignore`; never added in history. The OpenAI key lives only in the ignored `.env`. |
| `deploy/vercel/team-password.txt` | **Committed** | Hosted dashboard password. Deliberate (README: shared with collaborators). Exposed to anyone with repo access, and stays in history even if deleted. |
| `deploy/mail/team-gmail.env` | **Committed** | Team Gmail address plus SMTP and IMAP app password, loaded automatically by `src/chaser/mailenv.py`. Deliberate ("approved by Gülşah"). Same exposure as above. |
| `case-data/` (308 files) | **Committed** | The brief says the Soony data must not be shared outside the team. Fine in a private repo, a leak in a public one. |
| Personal data | Note | `scripts/autosync.sh` contains a teammate's personal email as the git author. Other addresses are test placeholders or the case suppliers. |
| Agent recordings (`docs/agent_runs/`) | OK | Exports state that API keys and authorization data are removed; `recording.py` redacts `sk-…`, `gh*_…` and bearer tokens. No keys found. |
| Hosted app auth | OK | Password gate with a SHA-256 hash and replay key in Vercel environment variables, eight-hour signed cookie, uncached responses. Gateway tokens come from environment variables, not files. |
| Real email safety | **Changed, check the claims** | `src/chaser/autosend.py` (mail-agent, Gülşah's decision) sends every current draft **without per-email human approval** once `CHASER_REAL_SMTP=1`. Allowlist (`@suppliers.juliansibbing.de` only), body guardrails and a 30-minute per-address cooldown stay on; no per-cycle cap by default. Off with `CHASER_AUTO_SEND=0`. README still says "Each message requires human confirmation": update the README or the pitch so they match. |

## Before submission (humans decide)
1. **How do judges see the repo?** If it becomes public, or a public copy is made: remove `deploy/vercel/team-password.txt`, `deploy/mail/team-gmail.env` and `case-data/` from a fresh history (a new repo or squashed export, since deleting files keeps them in history), and replace the personal email in `scripts/autosync.sh`.
2. **Rotate after the hackathon regardless:** the Gmail app password, the Vercel team password (new `SOONY_TEAM_PASSWORD_HASH`), and the OpenAI key (already on the list).
3. **Pick one email story for the pitch:** "agents send, humans approve" or "agents send on their own within guardrails". The code currently does the second in live mode.
