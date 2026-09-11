#!/usr/bin/env bash
#
# GuestIQ updater.
#   ./update.sh          -> pull latest + rebuild once
#   ./update.sh --watch  -> loop: watch for the in-app "Update now" flag and apply
#
set -e
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$DIR"

if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose";
else COMPOSE="docker-compose"; fi

FLAG="$DIR/data/.update_requested"

do_update() {
  echo "[GuestIQ] pulling latest…"
  git pull --ff-only || { echo "[GuestIQ] git pull failed"; return 1; }
  echo "[GuestIQ] rebuilding…"
  $COMPOSE up -d --build
  echo "[GuestIQ] update complete."
}

if [ "$1" = "--watch" ]; then
  echo "[GuestIQ] update watcher started (checking every 30s)…"
  while true; do
    if [ -f "$FLAG" ]; then
      echo "[GuestIQ] update requested via console."
      rm -f "$FLAG"
      do_update || true
    fi
    sleep 30
  done
else
  do_update
fi
