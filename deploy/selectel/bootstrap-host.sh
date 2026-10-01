#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

if ! swapon --show=NAME --noheadings | grep -qx '/swapfile'; then
  if [[ ! -f /swapfile ]]; then
    fallocate -l 1G /swapfile
  fi
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
fi
grep -qE '^/swapfile\s' /etc/fstab || printf '/swapfile none swap sw 0 0\n' >> /etc/fstab

cat >/etc/sysctl.d/60-temli.conf <<'EOF'
vm.swappiness=10
vm.vfs_cache_pressure=50
EOF
sysctl --system >/dev/null

apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl docker.io docker-compose-v2 git ufw
systemctl enable --now docker

install -d -m 750 /opt/temli
install -d -m 700 /opt/temli/secrets
install -d -m 700 /var/lib/temli/storage
install -d -m 700 /var/lib/temli/replica
install -d -m 700 /var/lib/temli/scratch

ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Password authentication is unnecessary after the dedicated deployment key
# has been verified. Root remains available with public-key authentication for
# recovery through the provider console.
cat >/etc/ssh/sshd_config.d/01-temli-hardening.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
EOF
rm -f /etc/ssh/sshd_config.d/60-temli-hardening.conf
sshd -t
systemctl reload ssh

printf 'bootstrap=ok\n'
docker --version
docker compose version
free -h
df -h /
