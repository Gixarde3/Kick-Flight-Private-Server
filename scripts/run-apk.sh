#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ -f "$SCRIPT_DIR/base.apk" ]]; then
  repo="$SCRIPT_DIR"
else
  repo="$(cd "$SCRIPT_DIR/.." && pwd -P)"
fi
cd "$repo"

# 1. Resolver IP de forma automática
custom_ip="${1:-${SERVER_IP:-}}"
port="${PORT:-18080}"

detect_ip() {
  local ip=""
  local def_iface
  def_iface=$(route get default 2>/dev/null | awk '/interface:/ {print $2}')
  if [[ -n "$def_iface" ]]; then
    ip=$(ipconfig getifaddr "$def_iface" 2>/dev/null || true)
  fi
  if [[ -z "$ip" ]]; then
    for iface in en0 en1 en2 wlan0; do
      ip=$(ipconfig getifaddr "$iface" 2>/dev/null || true)
      [[ -n "$ip" ]] && break
    done
  fi
  if [[ -z "$ip" ]]; then
    ip=$(ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -n1)
  fi
  echo "$ip"
}

if [[ -n "$custom_ip" && "$custom_ip" != --* ]]; then
  target_ip="$custom_ip"
else
  target_ip="$(detect_ip)"
fi

if [[ -z "$target_ip" ]]; then
  echo "❌ Error: No se pudo detectar la IP local del Mac automáticamente." >&2
  echo "   Por favor especifica tu IP: $0 <TU_IP>" >&2
  exit 1
fi

server_url="http://${target_ip}:${port}"

echo "=========================================================="
echo "🚀 KICK-FLIGHT: AUTOPATCH APK & SERVIDOR LOCAL"
echo "=========================================================="
echo "📍 IP Mac Detectada:  $target_ip"
echo "🌐 URL Servidor:      $server_url"
echo "=========================================================="

# 2. Actualizar config/apk-direct-server.local.json
config_file="$repo/config/apk-direct-server.local.json"
if [[ -f "$config_file" ]]; then
  python3 -c "
import json
path = '$config_file'
with open(path, 'r', encoding='utf-8-sig') as f:
    data = json.load(f)
data['serverBaseUrl'] = '$server_url'
with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
"
  echo "✅ Configuración actualizada: $config_file -> $server_url"
fi

# 3. Regenerar catálogo y fixtures de Octo
echo ""
echo "📦 Regenerando catálogo de recursos Octo..."
python3 "$repo/scripts/build-title-resource-catalog.py"

# 4. Construir y firmar el APK patcheado
echo ""
echo "🔨 Compilando y firmando APK para $server_url..."
SERVER_BASE_URL="$server_url" "$repo/scripts/build-direct-apk.sh"

safe_host="${server_url#http://}"
safe_host="${safe_host//:/-}"
output_apk="$repo/.local/artifacts/KickFlight-2.11.0-direct-${safe_host}.apk"

echo ""
echo "=========================================================="
echo "🎉 APK GENERADA EXITOSAMENTE:"
echo "📱 $output_apk"
echo "=========================================================="

# 5. Instalar automáticamente por ADB si hay un dispositivo conectado
adb_device=$(adb devices 2>/dev/null | grep -w "device" | awk '{print $1}' | head -n1 || true)
if [[ -n "$adb_device" ]]; then
  echo ""
  echo "📲 Dispositivo Android detectado por ADB ($adb_device). Instalando..."
  adb -s "$adb_device" install -r "$output_apk" || true
fi

# Si se pasó el flag --build-only o -b, terminar aquí
if [[ "${1:-}" == "--build-only" || "${2:-}" == "--build-only" || "${1:-}" == "-b" ]]; then
  echo "🏁 Proceso terminado (--build-only)."
  exit 0
fi

# 6. Liberar el puerto si ya está en uso
echo ""
echo "🔍 Comprobando si el puerto $port está ocupado..."
existing_pids=$(lsof -ti :"$port" 2>/dev/null || true)
if [[ -n "$existing_pids" ]]; then
  echo "⚠️  Liberando puerto $port (terminando PIDs: $existing_pids)..."
  kill -9 $existing_pids 2>/dev/null || true
  sleep 1
fi

# 7. Iniciar el servidor local
echo ""
echo "=========================================================="
echo "⚡ INICIANDO SERVIDOR KICK-FLIGHT EN TIEMPO REAL..."
echo "=========================================================="
echo "Instala el APK en tu teléfono (o conecta por USB):"
echo "  adb install -r $output_apk"
echo ""
echo "Presiona Ctrl+C para detener el servidor cuando termines."
echo "=========================================================="
echo ""

export DIRECT_CLIENT_HOST="$target_ip"
export HTTP_PORT="$port"
export ENABLE_CAPTURE="true"
exec "$repo/scripts/run-local.sh"
