# SRE Agent CD Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate deployment of `sre-ai-agent` to the Hetzner VPS on every push to `main` via GitHub Actions, replacing the manual SSH update command.

**Architecture:** A two-job GitHub Actions workflow runs `pytest` on every push/PR and, on `main` pushes only, SSHes into the VPS as a dedicated non-root `deploy` user to pull the latest code and restart the service. A new Taskfile task in `siloed-project/infra/` provisions that user once. Both repos get a PR each.

**Tech Stack:** GitHub Actions, SSH ed25519 key pair, systemd, Taskfile v3, Python 3.12

---

## File Structure

**`sre-ai-agent` repo** (primary — new branch `feat/cd-pipeline` from `main`):
- Create: `.github/workflows/ci-cd.yml` — two-job CI/CD workflow
- Modify: `README.md` — replace manual update command with auto-deploy note
- Modify: `CLAUDE.md` — flag `main` as a live deploy target

**`siloed-project` repo** (supporting — new branch `feat/sre-agent-deploy-user` from `master`):
- Modify: `infra/Taskfile.sre-agent.yml` — add `setup-deploy-user` task
- Modify: `infra/CLAUDE.md` — add `setup-deploy-user` to one-time setup sequence

---

## Task 1: GitHub Actions Workflow

**Files:**
- Create: `sre-ai-agent/.github/workflows/ci-cd.yml`

- [ ] **Step 1: Create branch and directory**

```bash
cd /path/to/sre-ai-agent
git checkout main && git pull
git checkout -b feat/cd-pipeline
mkdir -p .github/workflows
```

- [ ] **Step 2: Write the workflow file**

Create `.github/workflows/ci-cd.yml` with this exact content:

```yaml
name: CI/CD

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: |
          python3 -m venv .venv
          .venv/bin/pip install -r requirements.txt
      - name: Run tests
        run: .venv/bin/pytest

  deploy:
    runs-on: ubuntu-latest
    needs: test
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    steps:
      - name: Set up SSH key
        run: |
          mkdir -p ~/.ssh
          echo "${{ secrets.VPS_SSH_PRIVATE_KEY }}" > ~/.ssh/id_ed25519
          chmod 600 ~/.ssh/id_ed25519
      - name: Add VPS to known hosts
        run: ssh-keyscan -H ${{ secrets.VPS_IP }} >> ~/.ssh/known_hosts
      - name: Deploy to VPS
        run: |
          ssh deploy@${{ secrets.VPS_IP }} '
            set -e
            cd /opt/sre-agent
            git fetch
            git reset --hard origin/main
            .venv/bin/pip install -q -r requirements.txt
            sudo systemctl restart sre-agent
            sleep 5
            sudo systemctl is-active --quiet sre-agent
          '
```

- [ ] **Step 3: Validate YAML syntax**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci-cd.yml')); print('YAML OK')"
```

Expected: `YAML OK`

- [ ] **Step 4: Verify the workflow structure looks correct**

Check:
- `test` job triggers on both `push` and `pull_request`
- `deploy` job has `needs: test` and `if:` condition limiting it to `push` on `main`
- The SSH command uses `set -e` so any failure aborts the deploy
- `systemctl is-active --quiet` is the last command — non-zero exit fails the job

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci-cd.yml
git commit -m "feat(ci): add GitHub Actions CI/CD workflow"
```

---

## Task 2: Update sre-ai-agent Docs

**Files:**
- Modify: `sre-ai-agent/README.md` (lines 93–97)
- Modify: `sre-ai-agent/CLAUDE.md` (line 7)

(Continue on the `feat/cd-pipeline` branch from Task 1.)

- [ ] **Step 1: Update README "Updating after code changes" section**

The current section (lines 93–97) is:

```markdown
### Updating after code changes

```bash
ssh root@<vps-ip> 'cd /opt/sre-agent && git pull && .venv/bin/pip install -r requirements.txt && systemctl restart sre-agent'
```
```

Replace it with:

```markdown
### Updating after code changes

Deployment is automatic: push to `main` triggers GitHub Actions, which runs tests and deploys to the VPS if they pass.

**Manual override** (emergency rollback or off-pipeline fix):
```bash
ssh root@<vps-ip> 'cd /opt/sre-agent && git reset --hard <sha> && .venv/bin/pip install -r requirements.txt && systemctl restart sre-agent'
```
```

- [ ] **Step 2: Update CLAUDE.md Workflow section**

The current Workflow section (lines 5–7) is:

```markdown
## Workflow

Every feature must be developed on its own branch and merged via a pull request — no feature commits directly to `main`.
```

Replace it with:

```markdown
## Workflow

Every feature must be developed on its own branch and merged via a pull request — no feature commits directly to `main`. Merging to `main` triggers automatic deployment to the VPS via GitHub Actions — treat `main` as a live deploy target.
```

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: update deployment instructions for automated CD"
```

- [ ] **Step 4: Push and open PR**

```bash
git push -u origin feat/cd-pipeline
```

Open a PR from `feat/cd-pipeline` → `main` in the `sre-ai-agent` repo. Title: `feat(ci): add GitHub Actions CI/CD pipeline`.

Note: the workflow will not trigger a deploy when this PR merges until the two GitHub secrets (`VPS_SSH_PRIVATE_KEY`, `VPS_IP`) are added and the `setup-deploy-user` task (Task 3) has been run on the VPS. The `deploy` job will fail with an SSH error until then — this is expected.

---

## Task 3: Taskfile `setup-deploy-user` Task

**Files:**
- Modify: `siloed-project/infra/Taskfile.sre-agent.yml`

- [ ] **Step 1: Create branch**

```bash
cd /path/to/siloed-project
git checkout master && git pull
git checkout -b feat/sre-agent-deploy-user
```

- [ ] **Step 2: Add the task to Taskfile.sre-agent.yml**

Open `infra/Taskfile.sre-agent.yml`. After the closing lines of the `setup-vps` task (after line 129, before `ssh-config:`), add:

```yaml
  setup-deploy-user:
    desc: "Create non-root deploy user on the SRE agent VPS for GitHub Actions CD. Requires DEPLOY_PUBKEY_PATH env var pointing to the public key (.pub) file. Run after setup-vps. Pre-condition: generate key with: ssh-keygen -t ed25519 -C github-actions-deploy -f ~/.ssh/sre-agent-deploy -N ''"
    cmds:
      - cmd: |
          set -e

          if [ -z "${DEPLOY_PUBKEY_PATH}" ]; then
            echo "ERROR: DEPLOY_PUBKEY_PATH env var is required."; exit 1
          fi
          if [ ! -f "${DEPLOY_PUBKEY_PATH}" ]; then
            echo "ERROR: Public key file not found: ${DEPLOY_PUBKEY_PATH}"; exit 1
          fi

          VPS_IP=$(hcloud server describe sre-agent -o json | jq -r '.public_net.ipv4.ip')
          if [ -z "$VPS_IP" ] || [ "$VPS_IP" = "null" ]; then
            echo "ERROR: VPS not found. Run 'task sre-agent:create-vps' first."; exit 1
          fi
          echo "==> VPS IP: $VPS_IP"

          PUBKEY=$(cat "${DEPLOY_PUBKEY_PATH}")
          SSH="ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 root@$VPS_IP"

          echo "==> Creating deploy user..."
          $SSH "useradd --create-home --shell /bin/bash deploy 2>/dev/null || true"

          echo "==> Setting up SSH authorized_keys for deploy user..."
          $SSH "
            mkdir -p /home/deploy/.ssh &&
            echo '${PUBKEY}' > /home/deploy/.ssh/authorized_keys &&
            chmod 700 /home/deploy/.ssh &&
            chmod 600 /home/deploy/.ssh/authorized_keys &&
            chown -R deploy:deploy /home/deploy/.ssh
          "

          echo "==> Writing sudoers rule..."
          $SSH "echo 'deploy ALL=(ALL) NOPASSWD: /bin/systemctl restart sre-agent' > /etc/sudoers.d/deploy-sre-agent && chmod 440 /etc/sudoers.d/deploy-sre-agent"

          echo "==> Transferring /opt/sre-agent ownership to deploy user..."
          $SSH "chown -R deploy:deploy /opt/sre-agent"

          echo ""
          echo "==> deploy user ready. Verify with:"
          echo "    ssh deploy@$VPS_IP 'echo ok'"
          echo ""
          echo "Next: add VPS_SSH_PRIVATE_KEY and VPS_IP to GitHub repo secrets:"
          echo "    https://github.com/siloed-project/sre-ai-agent/settings/secrets/actions"

```

- [ ] **Step 3: Verify the task appears correctly**

```bash
cd infra && task --list | grep setup-deploy-user
```

Expected: `sre-agent:setup-deploy-user  Create non-root deploy user...`

---

## Task 4: Update infra/CLAUDE.md

**Files:**
- Modify: `siloed-project/infra/CLAUDE.md`

(Continue on `feat/sre-agent-deploy-user` from Task 3.)

- [ ] **Step 1: Update the one-time setup block**

The current SRE bot section in `infra/CLAUDE.md` (lines 27–30) is:

```markdown
# SRE Telegram bot — VPS + K8s access (run once after sre-agent-rbac ArgoCD app syncs)
task sre-agent:create-vps                                                          # Create Hetzner cax11 VPS
ANTHROPIC_API_KEY=<key> TELEGRAM_BOT_TOKEN=<token> task sre-agent:setup-vps      # Provision end-to-end
```

Replace it with:

```markdown
# SRE Telegram bot — VPS + K8s access (run once after sre-agent-rbac ArgoCD app syncs)
task sre-agent:create-vps                                                          # Create Hetzner cax11 VPS
ANTHROPIC_API_KEY=<key> TELEGRAM_BOT_TOKEN=<token> task sre-agent:setup-vps      # Provision end-to-end

# CD pipeline — run once after setup-vps to enable auto-deploy from GitHub Actions
# First generate the deploy key: ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/sre-agent-deploy -N ""
DEPLOY_PUBKEY_PATH=~/.ssh/sre-agent-deploy.pub task sre-agent:setup-deploy-user  # Create non-root deploy user
# Then add to https://github.com/siloed-project/sre-ai-agent/settings/secrets/actions:
#   VPS_SSH_PRIVATE_KEY = contents of ~/.ssh/sre-agent-deploy
#   VPS_IP              = 46.224.239.116
```

- [ ] **Step 2: Commit both Taskfile and CLAUDE.md changes**

```bash
git add infra/Taskfile.sre-agent.yml infra/CLAUDE.md
git commit -m "feat(sre-agent): add setup-deploy-user task for GitHub Actions CD"
```

- [ ] **Step 3: Push and open PR**

```bash
git push -u origin feat/sre-agent-deploy-user
```

Open a PR from `feat/sre-agent-deploy-user` → `master` in the `siloed-project` repo. Title: `feat(sre-agent): add setup-deploy-user task for GitHub Actions CD`.

---

## Task 5: Wire Up Secrets and Verify

These are manual operator steps performed **after both PRs are merged**.

- [ ] **Step 1: Generate the deploy key pair (if not already done)**

```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/sre-agent-deploy -N ""
```

Expected: two files created — `~/.ssh/sre-agent-deploy` (private) and `~/.ssh/sre-agent-deploy.pub` (public).

- [ ] **Step 2: Run setup-deploy-user on the VPS**

From `siloed-project/infra/`:

```bash
HCLOUD_TOKEN=<token> DEPLOY_PUBKEY_PATH=~/.ssh/sre-agent-deploy.pub task sre-agent:setup-deploy-user
```

Expected output ends with:
```
==> deploy user ready. Verify with:
    ssh deploy@46.224.239.116 'echo ok'
```

- [ ] **Step 3: Smoke-test the deploy user**

```bash
ssh -i ~/.ssh/sre-agent-deploy deploy@46.224.239.116 'echo ok'
```

Expected: `ok`

- [ ] **Step 4: Add GitHub secrets**

Go to `https://github.com/siloed-project/sre-ai-agent/settings/secrets/actions` and add:
- `VPS_SSH_PRIVATE_KEY` — paste the full contents of `~/.ssh/sre-agent-deploy`
- `VPS_IP` — `46.224.239.116`

- [ ] **Step 5: Trigger a test deployment**

Make a trivial commit to `main` (e.g., add a blank line to README, or merge any pending PR) and watch the Actions tab at `https://github.com/siloed-project/sre-ai-agent/actions`.

Expected:
- `test` job: green
- `deploy` job: green, last line `systemctl is-active` exits 0

- [ ] **Step 6: Verify the service is still running on the VPS**

```bash
ssh root@46.224.239.116 'systemctl status sre-agent --no-pager'
```

Expected: `Active: active (running)`

---

## Operational Note: If the VPS IP Changes

The VPS IP only changes if the server is deleted and recreated — Hetzner preserves the IP across stop/start cycles. If it does change (e.g. after `hcloud server delete sre-agent` + `task sre-agent:create-vps`), two things must be updated:

1. **Update the `VPS_IP` GitHub secret** — go to `https://github.com/siloed-project/sre-ai-agent/settings/secrets/actions` and update `VPS_IP` to the new IP. The `ssh-keyscan` step in the workflow runs fresh on every deploy so `known_hosts` self-corrects automatically.

2. **Re-run the VPS setup** — the new server has no `deploy` user yet. Repeat the full sequence:
   ```bash
   ANTHROPIC_API_KEY=<key> TELEGRAM_BOT_TOKEN=<token> task sre-agent:setup-vps
   DEPLOY_PUBKEY_PATH=~/.ssh/sre-agent-deploy.pub task sre-agent:setup-deploy-user
   ```
   The deploy key pair (`~/.ssh/sre-agent-deploy`) does not need to be regenerated — the existing private key in GitHub secrets stays valid.
