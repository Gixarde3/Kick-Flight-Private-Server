#!/usr/bin/env bash
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
http_port="${HTTP_PORT:-18080}"
capture="${ENABLE_CAPTURE:-true}"

export HttpPort="$http_port"
export GrpcPort="18081"
export Harness__PersistCaptures="$capture"

export Harness__DirectClientHosts__0="${DIRECT_CLIENT_HOST:-127.0.0.1}"
export Harness__DirectClientHosts__1="10.0.2.2"
export Harness__DirectClientHosts__2="127.0.0.1"
export Harness__DirectClientHosts__3="localhost"
export Harness__DirectClientHosts__4="192.168.1.141"
export Harness__DirectClientHosts__5="192.168.1.32"

if ! command -v dotnet >/dev/null 2>&1; then
  export PATH="/opt/homebrew/opt/dotnet@8/bin:$PATH"
fi

# Ensure LuxonServer (Photon Realtime dependency) is running
if command -v docker >/dev/null 2>&1; then
  if ! docker ps --format '{{.Names}}' | grep -q "^luxon-server$"; then
    echo "Starting luxon-server dependency..."
    if docker ps -a --format '{{.Names}}' | grep -q "^luxon-server$"; then
      docker start luxon-server >/dev/null 2>&1 || true
    else
      luxon_dir="$repo/submodules/luxonserver"
      if [ ! -d "$luxon_dir" ]; then
        luxon_dir="/tmp/luxonserver"
      fi
      docker run -d --name luxon-server \
        -p 5055:5055/udp -p 5055:5055/tcp \
        -p 5056:5056/udp -p 5056:5056/tcp \
        -p 5058:5058/udp -p 5058:5058/tcp \
        -v "$luxon_dir:/src" \
        -w /src \
        gcc:14-bookworm /src/luxon_server >/dev/null 2>&1 || true
    fi
  fi
  echo "LuxonServer (Photon Realtime) status: Running on ports 5055, 5056, 5058"
fi

echo "Kick-Flight local server: http://0.0.0.0:${http_port}"
exec dotnet run \
  --project "$repo/src/KickFlight.BootstrapApi/KickFlight.BootstrapApi.csproj" \
  --no-launch-profile
