# PROTOCOL for delegating to other agent CLIs (lead only)
- Codex: `codex exec -s workspace-write --skip-git-repo-check --ephemeral -C <repo> -o <out> - < prompt.md`
- Copilot: `copilot -p "$(cat prompt.md)" -s --allow-tool 'write' --allow-tool 'shell(npm:*)'`
- Every prompt must say: read AGENTS.md + coord/STATUS.md first, owned directory, deliverable, do not read .soony_token.
- Review diffs before marking tasks done. One delegation round per task, then integrate.
