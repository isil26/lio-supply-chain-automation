# Team live backend

[Manti Live](https://soony-manti-live.vercel.app) runs on `instance-20261122-003928` in `europe-west8-a`. Each team member signs in as `isil`, `murat`, `nick`, `leo` or `gulsah` with the hackathon password `12345`. Judges sign in as `test` with the password provided by the team.

## Work on the server

From a local checkout, run `./scripts/vm-ssh`, then `cd ~/work/lio-supply-chain-automation`. The `lio-team` shell has passwordless sudo. The `vm-main` Git remote reads the VM’s mirror of the private repo. In a clean checkout on `main`, `git pull --ff-only vm-main main` brings in published changes. Coordinate edits in the shared worktree and use your own GitHub identity for a push. [SSH setup](../../AGENTS.md#gcp-vm-access)

```sh
sudo systemctl status lio-live --no-pager
sudo journalctl -u lio-live -n 30 --no-pager
sudo cat /var/lib/lio-live/release
```

## Runtime and state

`lio-live.service` starts at boot, runs as `lio-live`, and supervises the Python planner and Node gateway. Both bind to loopback. The production Vercel function checks the pinned SSH host key and forwards HTTP to `127.0.0.1:8890` over the existing SSH port. The `lio-vercel` account only permits forwarding to that port. Production uses the reserved address `34.154.38.26`.

The service-private directory is `/var/lib/lio-live`. `live-mail/soony.db` stores operational decisions and mail state. `mail-history.db` holds verified messages, and `live-mail/portal-sync/` contains the portal token, snapshots and latest accepted pointer. The portal worker checks for updates every two minutes, validates new snapshots and continues serving the last accepted one if validation fails. SQLite backups must include committed WAL writes. Use the SQLite backup API or stop the service before copying state.

The registered team mailbox configuration is in `mail-history.json`. The live worker reads replies via IMAP and sends eligible messages under the existing supplier-domain and approval rules. Set `CHASER_AUTO_SEND` to `0` in the service’s `config.json` and restart `lio-live` to pause automatic sending. **Verified team mailbox** shows matched read-only history. Run only one live sender against the production state.

## Supplier email translation

The supplier translator reads new Polish, Korean and Chinese correspondence from the operational and verified mailboxes. It uses local CPU models and caches English by the original message hash. Install the runtime and pinned model packages on a new host before starting the service.

```sh
sudo /opt/lio/venv/bin/pip install --only-binary=:all: ctranslate2==4.6.0 sentencepiece==0.2.1
sudo /opt/lio/venv/bin/python deploy/backend/install_translation_models.py
```

## Releases and archiving

GitHub Actions updates `/srv/lio/main.git` from development `main`. The application revision in [live-revision](live-revision) feeds `/srv/lio/production.git`. The VM watcher fetches that production mirror every 30 seconds, stages the build, checks dashboard readiness and falls back to its previous release on a startup failure. State lives outside the release directories. The working checkout can advance independently.

The production Vercel gateway authenticates named accounts and forwards the signed-in identity to the VM. The production `SOONY_USERS_JSON` setting contains the five team verifiers from `deploy/vercel/demo-users.json` and the separately provisioned `test` verifier. The VM must recognize all six usernames when the gateway forwards a signed-in request. The VM runs with `SOONY_DEMO_ACCOUNTS=0`. The existing shared password and active shared sessions also work. A shared user can view offers and switch accounts to decide. The Activity Log records the individual username on approvals, declines and confirmed negotiations. Historical decisions retain their original attribution. [Named-login configuration](../vercel/README.md#sign-in-and-audit-activity)

For the `soony-manti-live` Vercel project, build with `bash deploy/vercel/package-vm.sh FRESH_DEPLOY_DIRECTORY`. It packages the pinned application with the VM transport. The project holds `LIO_VM_FORWARD_KEY`, the gateway token and the existing session configuration as server-only settings. Stage a production build with `--skip-domain`, verify signed-out denial, login, `/api/health`, `/api/dashboard` and `/react`, then promote the tested deployment. `/api/health` reports the running `backendCommit`.

The private mail-archive workflow requests a verified export from the VM on a five-minute schedule and can also be dispatched manually. GitHub may delay scheduled runs. Only the supplier archive diff returns to the private repo. The automation SSH principal may update the two mirrors or invoke the fixed archive exporter. The Mac backend, tunnel and archive LaunchAgents are disabled. [Release and archive workflow](../../.github/workflows/lio-vm.yml)
