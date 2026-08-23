#!/usr/bin/env bash
set -euo pipefail

# Run this script as root on the deployment host. It installs the narrowly
# scoped sudo policy required by .github/workflows/ci-cd.yml. It deliberately
# does not create or modify application secrets.

if [ "${EUID}" -ne 0 ]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

id deploy >/dev/null 2>&1 || { echo "Missing deploy user" >&2; exit 1; }
for command in docker nginx systemctl visudo; do
  command -v "${command}" >/dev/null || {
    echo "Missing required command: ${command}" >&2
    exit 1
  }
done

# Cloudflare Tunnel (cloudflared) — carries traffic to nginx over an
# outbound-only connection, so the VPS never needs to accept inbound
# connections on 80/443. Install the binary if it isn't already present.
if ! command -v cloudflared >/dev/null; then
  echo "Installing cloudflared..."
  arch="$(dpkg --print-architecture)"
  tmp_deb="$(mktemp --suffix=.deb)"
  curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${arch}.deb" -o "${tmp_deb}"
  dpkg -i "${tmp_deb}"
  rm -f "${tmp_deb}"
fi

install -d -m 0755 /etc/sudoers.d
install -m 0440 /dev/stdin /etc/sudoers.d/deploy-sre-agent <<'SUDOERS'
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/deploy/sre-agent.service /etc/systemd/system/sre-agent.service
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/deploy/sre-agent-langfuse.service /etc/systemd/system/sre-agent-langfuse.service
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/deploy/sre-agent-cleanup.service /etc/systemd/system/sre-agent-cleanup.service
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/deploy/sre-agent-cleanup.timer /etc/systemd/system/sre-agent-cleanup.timer
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/deploy/sre-agent-cloudflared.service /etc/systemd/system/sre-agent-cloudflared.service
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/deploy/sre-agent-cloudflared-kube.service /etc/systemd/system/sre-agent-cloudflared-kube.service
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/nginx/langfuse-proxy.conf /etc/nginx/snippets/langfuse-proxy.conf
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/nginx/sre-agent.conf /etc/nginx/sites-available/sre-agent.conf
deploy ALL=(ALL) NOPASSWD: /bin/ln -sfn /etc/nginx/sites-available/sre-agent.conf /etc/nginx/sites-enabled/sre-agent.conf
deploy ALL=(ALL) NOPASSWD: /usr/sbin/nginx -t
deploy ALL=(ALL) NOPASSWD: /bin/systemctl daemon-reload
deploy ALL=(ALL) NOPASSWD: /bin/systemctl enable --now nginx sre-agent-langfuse sre-agent-cleanup.timer sre-agent-cloudflared sre-agent-cloudflared-kube
deploy ALL=(ALL) NOPASSWD: /bin/systemctl restart sre-agent sre-agent-langfuse sre-agent-cloudflared sre-agent-cloudflared-kube
deploy ALL=(ALL) NOPASSWD: /bin/systemctl reload nginx
deploy ALL=(ALL) NOPASSWD: /usr/bin/stat -c %s /etc/sre-agent/env
deploy ALL=(ALL) NOPASSWD: /usr/bin/stat -c %s /etc/sre-agent/langfuse.env
deploy ALL=(ALL) NOPASSWD: /usr/bin/stat -c %s /etc/sre-agent/cloudflared.env
deploy ALL=(ALL) NOPASSWD: /usr/bin/stat -c %s /etc/sre-agent/cloudflared-kube.env
SUDOERS

visudo -cf /etc/sudoers.d/deploy-sre-agent
echo "Installed /etc/sudoers.d/deploy-sre-agent"

# Harden the host firewall: allow SSH only, deny all other inbound traffic.
# cloudflared reaches nginx via its outbound tunnel connection, so 80/443
# never need to be opened on the VPS.
if command -v ufw >/dev/null; then
  ufw allow OpenSSH
  ufw default deny incoming
  ufw default allow outgoing
  ufw --force enable
  echo "ufw enabled: inbound denied by default except OpenSSH"
else
  echo "ufw not found — skipping firewall hardening; lock down 80/443 via your cloud provider's firewall instead" >&2
fi
