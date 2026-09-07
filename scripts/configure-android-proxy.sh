#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 SERVER_ADDRESS [PORT]" >&2
  exit 2
fi

server_address="$1"
port="${2:-8080}"
serial_args=()
if [[ -n "${ANDROID_SERIAL:-}" ]]; then
  serial_args=(-s "$ANDROID_SERIAL")
fi

current="$(adb "${serial_args[@]}" shell settings get global http_proxy | tr -d '\r')"
echo "Previous Android proxy: $current"
adb "${serial_args[@]}" shell settings put global http_proxy "${server_address}:${port}"
echo "Android proxy set to ${server_address}:${port}"
