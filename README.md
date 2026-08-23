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
- A running private Cloudflare Tunnel to the kube-apiserver — see [Private kube-apiserver access](#private-kube-apiserver-access-cloudflare-tunnel) below; the cluster side is provisioned from the `siloed_dev` repo (`infra/terraform/cloudflare_tunnel_kube.tf`)

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
```

> The conversation memory directory (`/var/lib/sre-agent/`) is created and owned automatically by systemd via `StateDirectory=sre-agent` — no manual `mkdir` needed.

Copy your kubeconfig to `/etc/sre-agent/kubeconfig.yaml` (mode 600, owned by `sre-agent`). Its
`server:` field must be `https://127.0.0.1:6443` — the apiserver has no public inbound rule, so
this only resolves once `sre-agent-cloudflared-kube.service` (below) is running.

Install the systemd service (the unit file is version-controlled at `deploy/sre-agent.service`):

```bash
cp /opt/sre-agent/deploy/sre-agent.service /etc/systemd/system/sre-agent.service
systemctl daemon-reload && systemctl enable --now sre-agent
```

The service file uses `StateDirectory=sre-agent` so systemd automatically creates and owns `/var/lib/sre-agent/` on every start — no manual directory setup required.

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

### Private kube-apiserver access (Cloudflare Tunnel)

The kube-apiserver has no public inbound firewall rule — the agent reaches it through a private
Cloudflare Tunnel instead, via a local client proxy (`cloudflared access tcp`) that this VPS talks
to over loopback. This is a separate, independent tunnel from the dashboard's (below): that one is
a `cloudflared tunnel run` **server** carrying public traffic in; this one is a `cloudflared access
tcp` **client** dialing a private route out. Cluster-side setup (the tunnel, its TCP ingress rule,
and the Access service token) lives in the `siloed_dev` repo — see its `infra/CLAUDE.md` "Private
kube-apiserver access" section.

```bash
# Service token credentials (from siloed_dev: terraform output cloudflared_kube_access_service_token_id / _secret)
cp /opt/sre-agent/.env.cloudflared-kube.example /etc/sre-agent/cloudflared-kube.env
chmod 600 /etc/sre-agent/cloudflared-kube.env
chown sre-agent:sre-agent /etc/sre-agent/cloudflared-kube.env
```

Fill in `/etc/sre-agent/cloudflared-kube.env`:

| Variable | What to put here |
|---|---|
| `TUNNEL_HOSTNAME` | The private hostname from the tunnel's TCP ingress rule, e.g. `kube-api-internal.siloed.dev` |
| `TUNNEL_SERVICE_TOKEN_ID` | `terraform output -raw cloudflared_kube_access_service_token_id` in `siloed_dev`'s `infra/terraform` |
| `TUNNEL_SERVICE_TOKEN_SECRET` | `terraform output -raw cloudflared_kube_access_service_token_secret` in `siloed_dev`'s `infra/terraform` |

```bash
cp /opt/sre-agent/deploy/sre-agent-cloudflared-kube.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now sre-agent-cloudflared-kube
```

Check it's connected before starting/restarting `sre-agent`:

```bash
systemctl status sre-agent-cloudflared-kube
journalctl -u sre-agent-cloudflared-kube -f
```

This service is included in the CI/CD deploy pipeline (see [Prepare a VPS for CI/CD](#prepare-a-vps-for-cicd)) once bootstrapped once by hand as above.

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

An nginx reverse proxy sits in front of LangFuse. The LangFuse containers listen on loopback only; nginx itself also listens on loopback and is reached only through a Cloudflare Tunnel, with Cloudflare Access providing SSO — see [step 4](#4-point-a-domain-via-cloudflare-optional). Because SSO is enforced at Cloudflare's edge before any request reaches the VPS, there is no separate application-level login page.

The deployment workflow runs after a push to `main`. It updates the application and systemd unit files, starts the LangFuse stack, restarts the agent and tunnel services, and reloads nginx. The first VPS setup and all secret values remain manual.

#### Prerequisites

The VPS must have:

- Ubuntu/Debian with `sudo`, Git, Python 3.12+, and Docker Compose v2
- a `deploy` user that can SSH in and run the required `sudo systemctl` and file-copy commands
- the repository checked out at `/opt/sre-agent`
- a Cloudflare Tunnel (see [Point a domain via Cloudflare](#4-point-a-domain-via-cloudflare-optional) below) — traffic reaches nginx through `cloudflared`'s outbound connection, so no inbound port needs to be opened on the VPS firewall

Install nginx once, before the first deployment:

```bash
sudo apt-get update
sudo apt-get install -y nginx
```

The agent, LangFuse stack, cleanup timer, and nginx run as separate managed services (unit files are in `deploy/`):

| Service | Unit file | Auto-deployed? | What it does |
|---|---|---|---|
| LangFuse stack | `sre-agent-langfuse.service` | Yes — started/restarted on every deploy | Runs `docker compose` for LangFuse and its dependencies |
| Trace cleanup | `sre-agent-cleanup.service` + `.timer` | Unit file only | Deletes old traces daily |
| nginx | system `nginx.service` | Yes, after one-time installation | Reverse proxy; already managed by systemd |
| Cloudflare Tunnel | `sre-agent-cloudflared.service` | Yes — restarted on every deploy | Carries traffic from Cloudflare to nginx over an outbound connection; no inbound port needed |

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
# Cloudflare Tunnel token (copy from .env.cloudflared.example and fill in)
cp /opt/sre-agent/.env.cloudflared.example /etc/sre-agent/cloudflared.env
chmod 600 /etc/sre-agent/cloudflared.env
chown sre-agent:sre-agent /etc/sre-agent/cloudflared.env
```

Fill in `/etc/sre-agent/cloudflared.env`:

| Variable | What to put here |
|---|---|
| `TUNNEL_TOKEN` | The token shown when you create the tunnel in Cloudflare Zero Trust → Networks → Tunnels (see [step 4](#4-point-a-domain-via-cloudflare-optional)) |

#### 2. Install and enable the systemd services

```bash
# LangFuse docker-compose service
cp /opt/sre-agent/deploy/sre-agent-langfuse.service /etc/systemd/system/

# Trace cleanup (timer fires daily, with up to 1h random delay to spread load)
cp /opt/sre-agent/deploy/sre-agent-cleanup.service /etc/systemd/system/
cp /opt/sre-agent/deploy/sre-agent-cleanup.timer /etc/systemd/system/

# Cloudflare Tunnel
cp /opt/sre-agent/deploy/sre-agent-cloudflared.service /etc/systemd/system/

systemctl daemon-reload
systemctl enable --now sre-agent-langfuse sre-agent-cleanup.timer sre-agent-cloudflared
```

#### 3. Configure nginx

```bash
apt-get install -y nginx
cp /opt/sre-agent/nginx/langfuse-proxy.conf /etc/nginx/snippets/langfuse-proxy.conf
cp /opt/sre-agent/nginx/sre-agent.conf /etc/nginx/sites-available/sre-agent.conf
ln -sf /etc/nginx/sites-available/sre-agent.conf /etc/nginx/sites-enabled/
nginx -t && systemctl enable --now nginx
```

The checked-in nginx configuration listens on `127.0.0.1:80` for `sre-agent.siloed.dev` and proxies dashboard traffic to LangFuse on `127.0.0.1:3000`. If you use a different hostname, change `server_name` before enabling the site.

To enable HTTPS between Cloudflare and the VPS (SSL/TLS mode Full (strict)), uncomment the TLS server block in `nginx/sre-agent.conf` and add a Cloudflare Origin Certificate.

#### Check status

```bash
systemctl status sre-agent-langfuse sre-agent-cleanup.timer sre-agent-cloudflared nginx
journalctl -u sre-agent-langfuse -f
journalctl -u sre-agent-cloudflared -f
```

#### 4. Point a domain via Cloudflare (optional)

The dashboard is reached at a public URL (e.g. `https://sre-agent.siloed.dev`) via a **Cloudflare Tunnel**, with **Cloudflare Access** providing SSO in front of it. Unlike a plain DNS A-record setup, the VPS never accepts inbound connections on 80/443 — `cloudflared` makes an outbound-only connection to Cloudflare's edge, and the host firewall (`ufw`, hardened by `deploy/bootstrap-vps.sh`) denies all inbound traffic except SSH.

1. **Create the tunnel** in Cloudflare Zero Trust → Networks → Tunnels → *Create a tunnel* → Cloudflared. Copy the token it gives you into `/etc/sre-agent/cloudflared.env` as `TUNNEL_TOKEN` (see [step 1](#1-create-secret-files-on-the-vps)).

2. **Add a public hostname** on the tunnel:
   - Subdomain/domain: e.g. `sre-agent.siloed.dev`
   - Service: `HTTP://localhost:80` (nginx, listening on loopback only)

   Cloudflare creates the DNS record automatically — no manual A record needed.

3. **Add a Cloudflare Access application** (Zero Trust → Access → Applications → *Add an application* → Self-hosted) for the same hostname, with a policy that only allows your email/domain through your chosen identity provider. Unauthenticated requests are redirected to Cloudflare's login page before they ever reach the VPS.

4. **Update `NEXTAUTH_URL`** in `/etc/sre-agent/langfuse.env` to match the public URL:
   ```
   NEXTAUTH_URL=https://sre-agent.siloed.dev
   ```
   Then restart LangFuse: `systemctl restart sre-agent-langfuse`

5. **Update the nginx server name** in `/etc/nginx/sites-available/sre-agent.conf`:
   ```nginx
   server_name sre-agent.siloed.dev;
   ```
   Then reload: `nginx -t && systemctl reload nginx`

Cloudflare handles TLS termination at its edge; nginx only needs to serve plain HTTP on loopback for `cloudflared` to reach.

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
sudo systemctl status sre-agent sre-agent-langfuse sre-agent-cloudflared nginx --no-pager
sudo docker compose -f /opt/sre-agent/docker-compose.langfuse.yml ps
sudo nginx -t
curl -I http://127.0.0.1:3000
```

Open `https://sre-agent.siloed.dev`. Cloudflare Access's login page should appear first; after signing in, the tunnel forwards the request to nginx, which proxies it to the LangFuse dashboard.

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

### Prepare a VPS for CI/CD

The deployment workflow connects as the unprivileged `deploy` user. On a new
Ubuntu VPS, install Docker, Docker Compose, nginx, and the `deploy` user first,
then run the repository bootstrap script as root:

```bash
sudo /opt/sre-agent/deploy/bootstrap-vps.sh
```

The bootstrap script also installs `cloudflared` (if missing) and hardens the
host firewall with `ufw` — allowing SSH only and denying all other inbound
traffic, since the Cloudflare Tunnel reaches nginx over an outbound
connection and never needs an open inbound port.

Before enabling CI deployment, provision these non-empty files on the VPS;
they contain secrets and must not be committed:

```text
/etc/sre-agent/env
/etc/sre-agent/langfuse.env
/etc/sre-agent/cloudflared.env
/etc/sre-agent/cloudflared-kube.env
```

The CI preflight checks that Docker, Compose, nginx, `cloudflared`, and these
files exist. The Langfuse systemd service pulls current container images
before starting them.

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
