# SRE Agent CD Pipeline Design

## Goal

Automatically deploy `sre-ai-agent` to the Hetzner VPS whenever a commit lands on `main`, replacing the current manual SSH update command.

## Architecture

A two-job GitHub Actions workflow in the `sre-ai-agent` repo runs tests on every push and PR, then SSHes into the VPS as a dedicated non-root `deploy` user to pull and restart the service. The deploy user has ownership of `/opt/sre-agent` and a single `sudo` rule scoped to `systemctl restart sre-agent` — no other root access. A new Taskfile task (`sre-agent:setup-deploy-user`) in `siloed-project/infra/` provisions this user once during initial VPS setup.

## Tech Stack

- GitHub Actions (workflow YAML, repository secrets)
- SSH with `ed25519` key pair (dedicated deploy key, separate from personal key)
- systemd (`sre-agent.service`, already in place)
- Taskfile v3 (new task added to `siloed-project/infra/Taskfile.sre-agent.yml`)

---

## Components

### 1. GitHub Actions Workflow — `.github/workflows/ci-cd.yml`

Two jobs:

**`test` job** — triggers on every `push` and `pull_request`:
- Runner: `ubuntu-latest`
- Steps: checkout, `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`, `pytest`
- No secrets required

**`deploy` job** — triggers only on `push` to `main`, depends on `test`:
- Runner: `ubuntu-latest`
- Steps:
  1. Write `VPS_SSH_PRIVATE_KEY` secret to `~/.ssh/id_ed25519`, set permissions `600`
  2. Add VPS to `known_hosts` via `ssh-keyscan`
  3. SSH as `deploy@$VPS_IP` and run:
     ```
     cd /opt/sre-agent &&
     git fetch &&
     git reset --hard origin/main &&
     .venv/bin/pip install -q -r requirements.txt &&
     sudo systemctl restart sre-agent &&
     sleep 5 &&
     sudo systemctl is-active --quiet sre-agent
     ```
  4. Fail the job if `systemctl is-active` returns non-zero

**GitHub secrets required** (set once in repo Settings → Secrets → Actions):
- `VPS_SSH_PRIVATE_KEY` — contents of `~/.ssh/sre-agent-deploy` (private half of deploy key pair)
- `VPS_IP` — `46.224.239.116`

**Security properties:**
- Secrets are never exposed to fork PRs (GitHub's default behaviour for `pull_request` events)
- The deploy job condition `github.ref == 'refs/heads/main'` prevents deploy from PRs
- The workflow YAML is public but contains no credential values — only secret name references

### 2. New Taskfile Task — `siloed-project/infra/Taskfile.sre-agent.yml: setup-deploy-user`

A one-time provisioning task, run after `setup-vps`:

```bash
DEPLOY_PUBKEY_PATH=~/.ssh/sre-agent-deploy.pub task sre-agent:setup-deploy-user
```

What it does on the VPS (all via SSH as root):
1. Creates `deploy` Linux user with home directory and bash shell
2. Creates `~deploy/.ssh/`, writes the public key to `authorized_keys`, sets ownership and permissions
3. Writes `/etc/sudoers.d/deploy-sre-agent`: `deploy ALL=(ALL) NOPASSWD: /bin/systemctl restart sre-agent`
4. Changes ownership of `/opt/sre-agent` from `sre-agent` to `deploy` (the `sre-agent` service user only reads from this directory, so world-readable permissions are sufficient for it to continue running)

**Pre-condition:** caller must generate the key pair locally first:
```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/sre-agent-deploy -N ""
```
The private key (`~/.ssh/sre-agent-deploy`) is then added to GitHub as `VPS_SSH_PRIVATE_KEY`. The Taskfile only ever receives the `.pub` file.

### 3. Documentation Updates

**`README.md`** — "Updating after code changes" section:
Replace the manual SSH command with: push to `main` — GitHub Actions runs tests and deploys automatically. Retain the manual command as a "manual override" fallback for emergencies.

**`CLAUDE.md`** — Workflow section:
Add one sentence: merging to `main` triggers automatic deployment to the VPS via GitHub Actions. This signals to future Claude sessions that `main` is a live deploy target.

**`siloed-project/infra/CLAUDE.md`** — One-time secrets setup block:
Add `setup-deploy-user` as the third step in the SRE bot setup sequence, after `setup-vps`. Include a note about the two GitHub secrets (`VPS_SSH_PRIVATE_KEY`, `VPS_IP`) that must be added manually in the GitHub UI.

---

## Deployment Flow (after this is in place)

```
git push → main
  └─ GitHub Actions: test job
       └─ pytest passes
            └─ deploy job
                 └─ SSH as deploy@VPS_IP
                      └─ git fetch + reset --hard
                           └─ pip install
                                └─ sudo systemctl restart sre-agent
                                     └─ systemctl is-active (health check)
                                          └─ job green ✓ / red ✗
```

---

## One-Time Setup Sequence (operator steps, not automated)

1. `ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/sre-agent-deploy -N ""`
2. From `siloed-project/infra/`:
   ```bash
   DEPLOY_PUBKEY_PATH=~/.ssh/sre-agent-deploy.pub task sre-agent:setup-deploy-user
   ```
3. Add `VPS_SSH_PRIVATE_KEY` (contents of `~/.ssh/sre-agent-deploy`) to GitHub repo secrets
4. Add `VPS_IP` (`46.224.239.116`) to GitHub repo secrets

Root SSH access to the VPS remains unchanged for manual admin use. The deploy key is a separate credential with no other privileges.

---

## Error Handling

- If `pytest` fails: `deploy` job does not run (job dependency)
- If `git fetch`/`reset` fails: SSH command exits non-zero, job fails
- If `pip install` fails: SSH command exits non-zero, job fails
- If `systemctl restart` fails: `is-active` returns non-zero, job fails — the broken state is visible in Actions but the service may have stopped; systemd's `Restart=always` with `StartLimitBurst=3` provides a recovery window
- No automated rollback: operator SSHes as root to investigate and manually restart or revert

## Out of Scope

- Rollback automation
- GitHub Environment protection rules (no external collaborators currently)
- Staging environment
- Docker-based deployment
