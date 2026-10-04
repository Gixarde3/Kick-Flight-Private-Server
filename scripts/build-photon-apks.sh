#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
server_ip="${1:-}"
if [[ -z "$server_ip" ]]; then
  echo "Usage: $0 <LAN server IP>" >&2
  exit 2
fi

python3 - "$repo/submodules/luxonserver/config.yml" "$server_ip" <<'PY'
import re
import sys
from pathlib import Path

config = Path(sys.argv[1]).read_text()
host = sys.argv[2]
for port in (5055, 5056, 5058):
    if not re.search(rf"^\s*external_address:\s*{re.escape(host)}:{port}\s*$", config, re.M):
        raise SystemExit(f"LuxonServer must advertise {host}:{port} before a phone can join")
PY

phone_apk="$repo/.local/artifacts/KickFlight-2.11.0-${server_ip}-PHOTON.apk"
emulator_apk="$repo/.local/artifacts/KickFlight-2.11.0-10.0.2.2-PHOTON.apk"
mkdir -p "$repo/.local/artifacts"

KF_PHOTON=1 SERVER_BASE_URL="http://${server_ip}:18080" OUTPUT_APK="$phone_apk" \
  "$repo/scripts/build-direct-apk.sh" > "$repo/.local/artifacts/build-phone-photon.log" 2>&1
KF_PHOTON=1 SERVER_BASE_URL="http://10.0.2.2:18080" OUTPUT_APK="$emulator_apk" \
  "$repo/scripts/build-direct-apk.sh" > "$repo/.local/artifacts/build-emulator-photon.log" 2>&1

python3 - "$phone_apk" "$emulator_apk" <<'PY'
import sys
from zipfile import ZipFile

for path in sys.argv[1:]:
    with ZipFile(path) as apk:
        lib = apk.read("lib/arm64-v8a/libil2cpp.so")
    if lib[0x13EFE74:0x13EFE7C] != bytes.fromhex("e003271ec0035fd6"):
        raise SystemExit(f"Photon join patch missing from {path}")
    if lib[0x13EF4C0:0x13EF4C4] != bytes.fromhex("687e0190"):
        raise SystemExit(f"Offline battle bridge found in {path}")
    print(path)
PY
