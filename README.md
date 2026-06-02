# SRE Q&A Agent

An agent, which can be reached by a Telegram bot and pure CLI that answers read-only questions about a Kubernetes cluster using Claude Haiku.

## Requirements

- Docker
- A valid `~/.kube/config` with cluster access
- An [Anthropic API key](https://console.anthropic.com)

## Build

```bash
docker build -t sre-agent .
```

## Run

```bash
docker run --rm \
  -v ~/.kube/config:/root/.kube/config:ro \
  -e ANTHROPIC_API_KEY=your-key-here \
  sre-agent "Which pods are unhealthy?"
```

## Telegram Bot (systemd on VPS)

The agent also runs as an interactive Telegram bot, deployed as a systemd service on any Linux VPS. It answers the same read-only Kubernetes questions sent via Telegram from an allowlisted chat ID.

### Prerequisites

- A Linux VPS with SSH root access
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- A kubeconfig scoped to a read-only ServiceAccount
- `ANTHROPIC_API_KEY`

### Setup

On the VPS:

```bash
# Create a system user
useradd --system --no-create-home --shell /usr/sbin/nologin sre-agent

# Install dependencies and clone
apt-get install -y python3 python3-venv git
git clone https://github.com/siloed-project/sre-ai-agent.git /opt/sre-agent
python3 -m venv /opt/sre-agent/.venv
/opt/sre-agent/.venv/bin/pip install -r /opt/sre-agent/requirements.txt
chown -R sre-agent:sre-agent /opt/sre-agent

# Create secrets directory and env file
mkdir -p /etc/sre-agent && chmod 700 /etc/sre-agent
cat > /etc/sre-agent/env <<EOF
ANTHROPIC_API_KEY=<your-key>
TELEGRAM_BOT_TOKEN=<your-token>
ALLOWED_CHAT_IDS=<comma-separated-chat-ids>
KUBECONFIG=/etc/sre-agent/kubeconfig.yaml
MEMORY_DB_PATH=/var/lib/sre-agent/memory.db
EOF
chmod 600 /etc/sre-agent/env
chown -R sre-agent:sre-agent /etc/sre-agent

# Create the conversation memory directory
mkdir -p /var/lib/sre-agent
chown sre-agent:sre-agent /var/lib/sre-agent
chmod 750 /var/lib/sre-agent
```

Copy your kubeconfig to `/etc/sre-agent/kubeconfig.yaml` (mode 600, owned by `sre-agent`).

Install the systemd service:

```ini
# /etc/systemd/system/sre-agent.service
[Unit]
Description=SRE AI Telegram Bot
After=network.target

[Service]
User=sre-agent
EnvironmentFile=/etc/sre-agent/env
WorkingDirectory=/opt/sre-agent
ExecStart=/opt/sre-agent/.venv/bin/python -m app.telegram_bot
Restart=always
RestartSec=10
StartLimitIntervalSec=60
StartLimitBurst=3
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now sre-agent
```

### Updating after code changes

Deployment is automatic: push to `main` triggers GitHub Actions, which runs tests and deploys to the VPS if they pass.

**Manual override** (emergency rollback or off-pipeline fix):
```bash
ssh root@<vps-ip> 'cd /opt/sre-agent && git reset --hard <sha> && .venv/bin/pip install -r requirements.txt && systemctl restart sre-agent'
```

### Logs

```bash
ssh root@<vps-ip> 'journalctl -u sre-agent -f'
```

### If the VPS IP changes

The VPS IP only changes if the server is deleted and recreated — Hetzner preserves the IP across stop/start cycles. If it does change:

1. Update the `VPS_IP` secret in the GitHub repo (Settings → Secrets → Actions).
2. Re-run `setup-vps` and `setup-deploy-user` on the new server — the existing deploy key in GitHub secrets stays valid and does not need to be regenerated.

## Example questions

```bash
docker run --rm -v ~/.kube/config:/root/.kube/config:ro -e ANTHROPIC_API_KEY=... sre-agent \
  "Are any nodes under pressure?"

docker run --rm -v ~/.kube/config:/root/.kube/config:ro -e ANTHROPIC_API_KEY=... sre-agent \
  "Which deployments have unavailable replicas?"

docker run --rm -v ~/.kube/config:/root/.kube/config:ro -e ANTHROPIC_API_KEY=... sre-agent \
  "Show me recent warning events in the kube-system namespace."

docker run --rm -v ~/.kube/config:/root/.kube/config:ro -e ANTHROPIC_API_KEY=... sre-agent \
  "Are there any pods restarting frequently?"

docker run --rm -v ~/.kube/config:/root/.kube/config:ro -e ANTHROPIC_API_KEY=... sre-agent \
  "Show me the last 50 lines of logs from the api pod in the payments namespace."

docker run --rm -v ~/.kube/config:/root/.kube/config:ro -e ANTHROPIC_API_KEY=... sre-agent \
  "What was the api pod logging before it crashed?"
```
