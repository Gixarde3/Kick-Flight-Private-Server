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

echo "Kick-Flight local server: http://0.0.0.0:${http_port}"
exec dotnet run \
  --project "$repo/src/KickFlight.BootstrapApi/KickFlight.BootstrapApi.csproj" \
  --no-launch-profile
