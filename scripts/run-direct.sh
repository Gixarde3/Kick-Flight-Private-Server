#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
config="$repo/config/apk-direct-server.local.json"

if [[ ! -f "$config" ]]; then
  echo "Missing $config" >&2
  exit 1
fi

read -r direct_host direct_port < <(python3 - "$config" <<'PY'
import json
import sys
from urllib.parse import urlsplit

config = json.load(open(sys.argv[1], encoding="utf-8-sig"))
url = urlsplit(config["serverBaseUrl"])
if url.scheme != "http" or not url.hostname:
    raise SystemExit("serverBaseUrl must be a direct http:// URL")
print(url.hostname, url.port or 80)
PY
)

export DIRECT_CLIENT_HOST="$direct_host"
export HTTP_PORT="$direct_port"
export ENABLE_CAPTURE="${ENABLE_CAPTURE:-true}"
exec "$repo/scripts/run-local.sh"
