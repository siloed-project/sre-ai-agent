#!/usr/bin/env bash
set -euo pipefail

# Prepare a Debian/Ubuntu VM for deployment. Application secrets and SSH
# authorization stay operator-managed; Tailscale enrollment is optional.
with_tailscale=false
case "${1:-}" in
  "") ;;
  --with-tailscale) with_tailscale=true ;;
  --help) echo "Usage: sudo $0 [--with-tailscale]"; exit 0 ;;
  *) echo "Usage: sudo $0 [--with-tailscale]" >&2; exit 1 ;;
esac
[[ $# -le 1 ]] || { echo 'Too many arguments' >&2; exit 1; }

if [ "${EUID}" -ne 0 ]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
command -v apt-get >/dev/null || { echo 'Requires Debian/Ubuntu with apt-get' >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
packages=(python3 python3-venv git curl ca-certificates nginx sudo ufw)
if ! command -v docker >/dev/null; then
  packages+=(docker.io)
  # Debian packages the client separately; Ubuntu includes it in docker.io.
  if apt-cache show docker-cli >/dev/null 2>&1; then packages+=(docker-cli); fi
fi
if ! docker compose version >/dev/null 2>&1; then
  if apt-cache show docker-compose-plugin >/dev/null 2>&1; then
    packages+=(docker-compose-plugin)
  elif apt-cache show docker-compose-v2 >/dev/null 2>&1; then
    packages+=(docker-compose-v2)
  else
    packages+=(docker-compose)
  fi
fi
apt-get install -y --no-install-recommends "${packages[@]}"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else "Python 3.12+ is required")'

id sre-agent >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin sre-agent
id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deploy
usermod -aG docker deploy
install -d -m 0700 -o sre-agent -g sre-agent /etc/sre-agent
install -d -m 0750 -o sre-agent -g sre-agent /var/lib/sre-agent
install -d -m 0700 -o deploy -g deploy /home/deploy/.ssh
install -d -m 0755 -o deploy -g deploy /opt/sre-agent
if [[ -d /opt/sre-agent/.git ]]; then
  chown -R deploy:deploy /opt/sre-agent
fi

install -d -m 0755 /etc/docker /etc/systemd/journald.conf.d
if [[ ! -e /etc/docker/daemon.json ]]; then
  printf '%s\n' '{"log-driver":"local","log-opts":{"max-size":"10m","max-file":"3"}}' > /etc/docker/daemon.json
  systemctl restart docker
fi
printf '[Journal]\nSystemMaxUse=100M\n' > /etc/systemd/journald.conf.d/sre-agent.conf
systemctl restart systemd-journald
systemctl enable --now docker
docker compose version

if "$with_tailscale"; then
  if ! command -v tailscale >/dev/null; then
    . /etc/os-release
    case "$ID" in debian|ubuntu) ;; *) echo 'Unsupported Tailscale apt distribution' >&2; exit 1 ;; esac
    curl -fsSL "https://pkgs.tailscale.com/stable/$ID/$VERSION_CODENAME.noarmor.gpg" -o /usr/share/keyrings/tailscale-archive-keyring.gpg
    curl -fsSL "https://pkgs.tailscale.com/stable/$ID/$VERSION_CODENAME.tailscale-keyring.list" -o /etc/apt/sources.list.d/tailscale.list
    apt-get update -q
    apt-get install -y --no-install-recommends tailscale
  fi
  systemctl enable --now tailscaled
  echo 'Tailscale installed; enroll separately with tailscale up.'
fi

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

# Unit files use this path; recent packages install into /usr/local/bin.
if [[ ! -e /usr/bin/cloudflared ]]; then
  ln -s "$(command -v cloudflared)" /usr/bin/cloudflared
fi

if [[ -L /etc/nginx/sites-enabled/default ]]; then
  unlink /etc/nginx/sites-enabled/default
  nginx -t
  systemctl restart nginx
fi
apt-get clean

install -d -m 0755 /etc/sudoers.d
install -m 0440 /dev/stdin /etc/sudoers.d/deploy-sre-agent <<'SUDOERS'
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/deploy/sre-agent.service /etc/systemd/system/sre-agent.service
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/deploy/sre-agent-langfuse.service /etc/systemd/system/sre-agent-langfuse.service
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/deploy/sre-agent-cleanup.service /etc/systemd/system/sre-agent-cleanup.service
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/deploy/sre-agent-cleanup.timer /etc/systemd/system/sre-agent-cleanup.timer
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/deploy/sre-agent-docker-prune.service /etc/systemd/system/sre-agent-docker-prune.service
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/deploy/sre-agent-docker-prune.timer /etc/systemd/system/sre-agent-docker-prune.timer
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/deploy/sre-agent-cloudflared.service /etc/systemd/system/sre-agent-cloudflared.service
# sre-agent-cloudflared-kube.service is optional -- these grants sit unused
# if you don't provision /etc/sre-agent/cloudflared-kube.env (see README
# "Private kube-apiserver access"). ci-cd.yml only invokes them when it does.
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/deploy/sre-agent-cloudflared-kube.service /etc/systemd/system/sre-agent-cloudflared-kube.service
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/nginx/langfuse-proxy.conf /etc/nginx/snippets/langfuse-proxy.conf
deploy ALL=(ALL) NOPASSWD: /bin/cp /opt/sre-agent/nginx/sre-agent.conf /etc/nginx/sites-available/sre-agent.conf
deploy ALL=(ALL) NOPASSWD: /bin/ln -sfn /etc/nginx/sites-available/sre-agent.conf /etc/nginx/sites-enabled/sre-agent.conf
deploy ALL=(ALL) NOPASSWD: /usr/sbin/nginx -t
deploy ALL=(ALL) NOPASSWD: /bin/systemctl daemon-reload
deploy ALL=(ALL) NOPASSWD: /bin/systemctl enable --now nginx sre-agent-langfuse sre-agent-cleanup.timer sre-agent-docker-prune.timer sre-agent-cloudflared
deploy ALL=(ALL) NOPASSWD: /bin/systemctl restart sre-agent sre-agent-langfuse sre-agent-cloudflared
deploy ALL=(ALL) NOPASSWD: /bin/systemctl enable --now sre-agent-cloudflared-kube
deploy ALL=(ALL) NOPASSWD: /bin/systemctl restart sre-agent-cloudflared-kube
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
