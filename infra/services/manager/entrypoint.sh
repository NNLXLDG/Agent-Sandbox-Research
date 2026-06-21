#!/usr/bin/env bash
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "[service-manager] docker CLI not found" >&2
  exit 1
fi

if [ ! -S /var/run/docker.sock ]; then
  echo "[service-manager] docker socket not mounted: /var/run/docker.sock" >&2
  exit 1
fi

SCRIPT_PATH=/workspace/infra/services/manager/manage_services.py
if [ ! -f "$SCRIPT_PATH" ]; then
  SCRIPT_PATH=/app/manage_services.py
fi

exec python3 "$SCRIPT_PATH" api
