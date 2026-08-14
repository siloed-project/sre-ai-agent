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

### Expose the dashboard on a VPS (optional)

A custom login page and nginx reverse proxy sit in front of LangFuse. The LangFuse containers listen on loopback only; nginx is the public entry point. Cloudflare DNS is optional, but recommended for HTTPS.

The deployment workflow runs after a push to `main`. It updates the application and systemd unit files, starts the LangFuse stack, restarts the auth and agent services, and reloads nginx. The first VPS setup and all secret values remain manual.

#### Prerequisites

The VPS must have:

- Ubuntu/Debian with `sudo`, Git, Python 3.12+, and Docker Compose v2
- a `deploy` user that can SSH in and run the required `sudo systemctl` and file-copy commands
- ports 80 and 443 allowed by the VPS firewall/security group
- the repository checked out at `/opt/sre-agent`

Install nginx once, before the first deployment:

```bash
sudo apt-get update
sudo apt-get install -y nginx
```

The agent, auth server, LangFuse stack, cleanup timer, and nginx run as separate managed services (unit files are in `deploy/`):

| Service | Unit file | Auto-deployed? | What it does |
|---|---|---|---|
| LangFuse stack | `sre-agent-langfuse.service` | Yes — started/restarted on every deploy | Runs `docker compose` for LangFuse and its dependencies |
| Auth server | `sre-agent-auth.service` | Yes — restarted on every deploy | Serves the login page on `127.0.0.1:8081` |
| Trace cleanup | `sre-agent-cleanup.service` + `.timer` | Unit file only | Deletes old traces daily |
| nginx | system `nginx.service` | Yes, after one-time installation | Reverse proxy; already managed by systemd |

#### 1. Create secret files on the VPS

```bash
sudo install -d -o sre-agent -g sre-agent /etc/sre-agent

# LangFuse secrets (copy from .env.langfuse.example and fill in values)
cp /opt/sre-agent/.env.langfuse.example /etc/sre-agent/langfuse.env
chmod 600 /etc/sre-agent/langfuse.env
chown sre-agent:sre-agent /etc/sre-agent/langfuse.env
```

Fill in `/etc/sre-agent/langfuse.env`. The complete list of supported variables is in `.env.langfuse.example`; at minimum, set the database, LangFuse auth, ClickHouse, Redis, MinIO, and bootstrap values. Use strong, unique values for every `change-me` placeholder.

| Variable | What to put here |
|---|---|
| `POSTGRES_USER` | Database username |
| `POSTGRES_PASSWORD` | Strong random database password |
| `POSTGRES_DB` | Database name |
| `DATABASE_URL` | Must match the database values above |
| `NEXTAUTH_URL` | Public dashboard URL, e.g. `https://sre-agent.siloed.dev` |
| `NEXTAUTH_SECRET` | Strong random secret |
| `SALT` | Strong random salt |
| `ENCRYPTION_KEY` | 64-character hexadecimal encryption key |
| ClickHouse/Redis/MinIO variables | Credentials and internal service URLs from `.env.langfuse.example` |
| `LANGFUSE_INIT_*` variables | First-boot organization, project, and user values |

```bash
# Dashboard auth secrets (copy from .env.dashboard.example and fill in values)
cp /opt/sre-agent/.env.dashboard.example /etc/sre-agent/dashboard.env
chmod 600 /etc/sre-agent/dashboard.env
chown sre-agent:sre-agent /etc/sre-agent/dashboard.env
```

Fill in `/etc/sre-agent/dashboard.env`:

| Variable | What to put here |
|---|---|
| `DASHBOARD_USERNAME` | Login username, e.g. `admin` |
| `DASHBOARD_PASSWORD` | A strong password of your choice |
| `DASHBOARD_SECRET` | 32-char random string to sign session cookies — `openssl rand -hex 16` |

#### 2. Install and enable the systemd services

```bash
# LangFuse docker-compose service
cp /opt/sre-agent/deploy/sre-agent-langfuse.service /etc/systemd/system/

# Auth server
cp /opt/sre-agent/deploy/sre-agent-auth.service /etc/systemd/system/

# Trace cleanup (timer fires daily, with up to 1h random delay to spread load)
cp /opt/sre-agent/deploy/sre-agent-cleanup.service /etc/systemd/system/
cp /opt/sre-agent/deploy/sre-agent-cleanup.timer /etc/systemd/system/

systemctl daemon-reload
systemctl enable --now sre-agent-langfuse sre-agent-auth sre-agent-cleanup.timer
```

#### 3. Configure nginx

```bash
apt-get install -y nginx
cp /opt/sre-agent/nginx/langfuse-proxy.conf /etc/nginx/snippets/langfuse-proxy.conf
cp /opt/sre-agent/nginx/sre-agent.conf /etc/nginx/sites-available/sre-agent.conf
ln -sf /etc/nginx/sites-available/sre-agent.conf /etc/nginx/sites-enabled/
nginx -t && systemctl enable --now nginx
```

The checked-in nginx configuration listens on port 80 for `sre-agent.siloed.dev`, proxies `/login` to the auth server on `127.0.0.1:8081`, and proxies authenticated dashboard traffic to LangFuse on `127.0.0.1:3000`. If you use a different hostname, change `server_name` before enabling the site.

To enable HTTPS, uncomment the TLS server block in `nginx/sre-agent.conf` and add your certificate path.

#### Check status

```bash
systemctl status sre-agent-langfuse sre-agent-auth sre-agent-cleanup.timer nginx
journalctl -u sre-agent-langfuse -f
journalctl -u sre-agent-auth -f
```

#### 4. Point a domain via Cloudflare (optional)

If you want the dashboard reachable at a public URL (e.g. `https://sre-agent.siloed.dev`) you can proxy it through Cloudflare — this gives you free TLS without managing certificates yourself.

1. **Add a DNS record** in the Cloudflare dashboard for your domain:
   - Type: `A`
   - Name: `sre-agent` (or whatever subdomain you want)
   - IPv4 address: your VPS public IP
   - Proxy status: **Proxied** (orange cloud)

2. **Set SSL/TLS mode** to **Full** (Cloudflare dashboard → SSL/TLS → Overview). This encrypts the browser-to-Cloudflare connection while allowing Cloudflare to connect to the port-80 nginx origin. Use **Full (strict)** only after installing a trusted certificate, such as a Cloudflare Origin Certificate, on nginx.

3. **Update `NEXTAUTH_URL`** in `/etc/sre-agent/langfuse.env` to match the public URL:
   ```
   NEXTAUTH_URL=https://sre-agent.siloed.dev
   ```
   Then restart LangFuse: `systemctl restart sre-agent-langfuse`

4. **Update the nginx server name** in `/etc/nginx/sites-available/sre-agent.conf`:
   ```nginx
   server_name sre-agent.siloed.dev;
   ```
   Then reload: `nginx -t && systemctl reload nginx`

That's it — Cloudflare handles TLS termination and the HTTP server block on the VPS serves the proxied traffic. The HTTPS TLS block in `nginx/sre-agent.conf` is only needed if you want end-to-end encryption between Cloudflare and your VPS (SSL/TLS mode **Full (strict)**), in which case you'd add a Cloudflare origin certificate at the path shown in the commented block.

#### Configure agent tracing on the VPS

Add the LangFuse project keys to `/etc/sre-agent/env`:

```dotenv
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://sre-agent.siloed.dev
```

Then restart the agent:

```bash
sudo systemctl restart sre-agent
```

#### Verify the deployment

```bash
sudo systemctl status sre-agent sre-agent-auth sre-agent-langfuse nginx --no-pager
sudo docker compose -f /opt/sre-agent/docker-compose.langfuse.yml ps
sudo nginx -t
curl -I http://127.0.0.1:3000
curl -I http://127.0.0.1:8081/login
```

Open `https://sre-agent.siloed.dev`. The custom SRE Agent login page should appear first; after signing in, nginx forwards the request to the LangFuse dashboard.

### Trace retention

`sre-agent-cleanup.timer` (installed in step 2 above) runs `scripts/cleanup_langfuse.py` once a day and deletes traces older than `LANGFUSE_RETENTION_DAYS` (default: 30). Check its status with:

```bash
systemctl status sre-agent-cleanup.timer
journalctl -u sre-agent-cleanup.service
```

To run it manually at any time:

```bash
systemctl start sre-agent-cleanup.service
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
