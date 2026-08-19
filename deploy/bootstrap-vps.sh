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

install -d -m 0755 /etc/sudoers.d
install -m 0440 /dev/stdin /etc/sudoers.d/deploy-sre-agent <<'SUDOERS'
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/deploy/sre-agent.service /etc/systemd/system/sre-agent.service
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/deploy/sre-agent-langfuse.service /etc/systemd/system/sre-agent-langfuse.service
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/deploy/sre-agent-auth.service /etc/systemd/system/sre-agent-auth.service
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/deploy/sre-agent-cleanup.service /etc/systemd/system/sre-agent-cleanup.service
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/deploy/sre-agent-cleanup.timer /etc/systemd/system/sre-agent-cleanup.timer
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/nginx/langfuse-proxy.conf /etc/nginx/snippets/langfuse-proxy.conf
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/nginx/sre-agent.conf /etc/nginx/sites-available/sre-agent.conf
deploy ALL=(ALL) NOPASSWD: /bin/ln -sfn /etc/nginx/sites-available/sre-agent.conf /etc/nginx/sites-enabled/sre-agent.conf
deploy ALL=(ALL) NOPASSWD: /usr/sbin/nginx -t
deploy ALL=(ALL) NOPASSWD: /bin/systemctl daemon-reload
deploy ALL=(ALL) NOPASSWD: /bin/systemctl enable --now nginx sre-agent-langfuse sre-agent-auth sre-agent-cleanup.timer
deploy ALL=(ALL) NOPASSWD: /bin/systemctl restart sre-agent sre-agent-auth sre-agent-langfuse
deploy ALL=(ALL) NOPASSWD: /bin/systemctl reload nginx
deploy ALL=(ALL) NOPASSWD: /usr/bin/stat -c %s /etc/sre-agent/env
deploy ALL=(ALL) NOPASSWD: /usr/bin/stat -c %s /etc/sre-agent/langfuse.env
deploy ALL=(ALL) NOPASSWD: /usr/bin/stat -c %s /etc/sre-agent/dashboard.env
SUDOERS

visudo -cf /etc/sudoers.d/deploy-sre-agent
echo "Installed /etc/sudoers.d/deploy-sre-agent"
