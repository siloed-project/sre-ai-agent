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

## Observability (LangFuse)

The agent traces every tool call and LLM turn through [LangFuse](https://langfuse.com) when configured.

### Start LangFuse locally

Copy `.env.langfuse.example` to `.env.langfuse` and fill in the values:

| Variable | What to put here |
|---|---|
| `POSTGRES_USER` | Any username, e.g. `langfuse` |
| `POSTGRES_PASSWORD` | A strong random password — `openssl rand -hex 20` |
| `POSTGRES_DB` | Any database name, e.g. `langfuse` |
| `DATABASE_URL` | Must match the user/password/db above: `postgresql://langfuse:<password>@langfuse-db:5432/langfuse` |
| `NEXTAUTH_URL` | The public URL of the dashboard, e.g. `https://sre-agent.example.com` or `http://localhost:3000` for local use |
| `NEXTAUTH_SECRET` | 32-char random string — `openssl rand -hex 16` |
| `SALT` | 16-char random string — `openssl rand -hex 8` |

```bash
cp .env.langfuse.example .env.langfuse   # edit the file with the values above
docker compose -f docker-compose.langfuse.yml up -d
```

LangFuse is bound to `127.0.0.1:3000` (loopback only — not public). Visit `http://localhost:3000` to set up your first user, then create a project and copy the API keys.

### Configure the agent

Add to `.env`:

```
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=http://localhost:3000
```

When these vars are set, every agent run emits a trace to LangFuse. When they are absent, tracing is silently skipped and only structured stdout logging is produced.

**Configure model pricing:** In the LangFuse UI go to Settings → Models and add entries for `claude-haiku-4-5-20251001`, `claude-sonnet-4-6`, and `claude-opus-4-7` with their input/output cost per million tokens. LangFuse will then attribute cost to every trace automatically.

### Expose the dashboard (optional)

A custom login page + nginx reverse proxy can sit in front of LangFuse.  Cloudflare DNS is optional — the setup works on plain HTTP for local/dev use.

Copy `.env.dashboard.example` to `.env.dashboard` and fill in the values:

| Variable | What to put here |
|---|---|
| `DASHBOARD_USERNAME` | Login username for the dashboard, e.g. `admin` |
| `DASHBOARD_PASSWORD` | A strong password of your choice |
| `DASHBOARD_SECRET` | 32-char random string used to sign session cookies — `openssl rand -hex 16` |

```bash
# Auth server (requires itsdangerous)
cp .env.dashboard.example .env.dashboard   # edit the file with the values above
export $(cat .env.dashboard | xargs)
python scripts/auth_server.py &

# nginx (copy config from nginx/ and install)
sudo cp nginx/langfuse-proxy.conf /etc/nginx/snippets/langfuse-proxy.conf
sudo cp nginx/sre-agent.conf /etc/nginx/sites-available/sre-agent.conf
sudo ln -sf /etc/nginx/sites-available/sre-agent.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

To enable HTTPS, uncomment the TLS server block in `nginx/sre-agent.conf` and add your certificate.

### Trace retention

Delete traces older than 30 days (configurable via `LANGFUSE_RETENTION_DAYS`):

```bash
python scripts/cleanup_langfuse.py
```

Cron example (runs at 02:00 daily):

```
0 2 * * * /opt/sre-agent/.venv/bin/python /opt/sre-agent/scripts/cleanup_langfuse.py
```

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
