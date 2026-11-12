#!/usr/bin/env bash
# One-time server setup for a fresh Ubuntu server (24.04 or newer).
# Run as root:   bash deploy/setup_server.sh
# Safe to run again (it skips what's already done).
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/mezarandy23-create/special-octo-spoon.git}"
BRANCH="${BRANCH:-main}"
APP_DIR=/opt/maai

echo "==> Installing system packages"
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git ffmpeg ufw unattended-upgrades

echo "==> Firewall: allow SSH only (the bot connects out to Telegram; nothing needs to come in)"
ufw allow OpenSSH
ufw --force enable

echo "==> Automatic security updates"
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> App user and folder"
id maai >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/maai --shell /usr/sbin/nologin maai
if [ ! -d "$APP_DIR/.git" ]; then
  git clone -b "$BRANCH" "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

[ -f .env ] || cp .env.example .env
[ -f config/business.yaml ] || cp config/business.example.yaml config/business.yaml
mkdir -p data/home logs
chown -R maai:maai "$APP_DIR"
chmod 600 .env
chmod 700 data logs

echo "==> Service (starts automatically, restarts if it crashes)"
cp deploy/maai.service /etc/systemd/system/maai.service
systemctl daemon-reload
systemctl enable maai

cat <<'EOF'

Done. Next:
  1) Fill in your keys:          nano /opt/maai/.env
  2) Check your details:         nano /opt/maai/config/business.yaml
  3) Check the setup:            sudo -u maai /opt/maai/.venv/bin/python -m maai doctor
  4) Start the office:           systemctl start maai
  5) Watch it:                   journalctl -u maai -f
EOF
