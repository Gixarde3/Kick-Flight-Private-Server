#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
listen_host="${LISTEN_HOST:-0.0.0.0}"
listen_port="${LISTEN_PORT:-8080}"
backend_port="${BACKEND_PORT:-18080}"
conf_dir="$repo/certs/mitmproxy"

if ! command -v mitmdump >/dev/null 2>&1; then
  echo "mitmdump is missing. Install it with: brew install mitmproxy" >&2
  exit 1
fi

mkdir -p "$conf_dir"
export KICKFLIGHT_BACKEND_HOST="127.0.0.1"
export KICKFLIGHT_BACKEND_PORT="$backend_port"

echo "Kick-Flight local-only proxy: ${listen_host}:${listen_port} -> 127.0.0.1:${backend_port}"
exec mitmdump \
  --listen-host "$listen_host" \
  --listen-port "$listen_port" \
  --set "confdir=$conf_dir" \
  --set block_global=false \
  --set connection_strategy=lazy \
  --set termlog_verbosity=info \
  -s "$repo/scripts/mitm_local_only.py"
