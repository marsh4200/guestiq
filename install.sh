#!/usr/bin/env bash
#
# GuestIQ one-line installer
#   curl -fsSL https://raw.githubusercontent.com/marsh4200/guestiq/main/install.sh | bash
#
set -e

REPO="${GUESTIQ_REPO:-marsh4200/guestiq}"
BRANCH="${GUESTIQ_BRANCH:-main}"
DIR="${GUESTIQ_DIR:-$HOME/guestiq}"
PORT=9921

echo "==> GuestIQ installer"

# --- checks ---------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is not installed. Install Docker first: https://docs.docker.com/engine/install/"
  exit 1
fi
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose";
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE="docker-compose";
else echo "ERROR: docker compose plugin not found."; exit 1; fi
if ! command -v git >/dev/null 2>&1; then
  echo "ERROR: git is required (used for updates)."; exit 1; fi

# --- fetch / update repo --------------------------------------------------
if [ -d "$DIR/.git" ]; then
  echo "==> Updating existing install in $DIR"
  git -C "$DIR" pull --ff-only
else
  echo "==> Cloning into $DIR"
  git clone --branch "$BRANCH" "https://github.com/$REPO.git" "$DIR"
fi

cd "$DIR"
mkdir -p data

# --- build & run ----------------------------------------------------------
echo "==> Building and starting container (port $PORT)"
$COMPOSE up -d --build

# --- install the update watcher (systemd if available, else nohup) --------
if command -v systemctl >/dev/null 2>&1 && [ "$(id -u)" = "0" ]; then
  echo "==> Installing systemd update watcher"
  cat > /etc/systemd/system/guestiq-watch.service <<UNIT
[Unit]
Description=GuestIQ update watcher
After=docker.service

[Service]
Type=simple
WorkingDirectory=$DIR
ExecStart=/usr/bin/env bash $DIR/update.sh --watch
Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
  systemctl enable --now guestiq-watch.service
else
  echo "==> Starting background update watcher (nohup)"
  pkill -f "guestiq.*update.sh --watch" 2>/dev/null || true
  nohup bash "$DIR/update.sh" --watch >/tmp/guestiq-watch.log 2>&1 &
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo ""
echo "============================================================"
echo " GuestIQ is running"
echo "   Admin console : http://${IP:-localhost}:$PORT/admin"
echo "   Default login : password 'admin'  (change it in Settings)"
echo "   Data stored in: $DIR/data"
echo "============================================================"
