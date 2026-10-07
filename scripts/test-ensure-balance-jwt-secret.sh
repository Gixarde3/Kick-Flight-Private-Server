#!/usr/bin/env bash
set -Eeuo pipefail

repo_root=$(cd -- "$(dirname -- "$0")/.." && pwd)
tmp_dir=$(mktemp -d)
trap 'rm -rf -- "$tmp_dir"' EXIT
secret="$tmp_dir/private/jwt-secret"
env_file="$tmp_dir/balance.env"
resolver="$repo_root/scripts/resolve-balance-jwt-secret-path.py"

default_secret=$(python3 "$resolver" "$tmp_dir" "$env_file")
[[ "$default_secret" == "$tmp_dir/.local/balance-auth/jwt-secret" ]]
cat > "$env_file" <<'EOF'
KF_BALANCE_AUTH_DB=/srv/private/auth.sqlite3
EOF
[[ $(python3 "$resolver" "$tmp_dir" "$env_file") == /srv/private/jwt-secret ]]
cat >> "$env_file" <<'EOF'
KF_BALANCE_JWT_SECRET_FILE=/run/kickflight/private-signing-key
EOF
[[ $(python3 "$resolver" "$tmp_dir" "$env_file") == /run/kickflight/private-signing-key ]]

bash "$repo_root/scripts/ensure-balance-jwt-secret.sh" \
  "$repo_root/tools/balance/generate_jwt_secret.py" "$secret" "$(id -un)"
[[ $(stat -c '%a' "$tmp_dir/private") == 700 ]]
[[ $(stat -c '%a' "$secret") == 600 ]]
[[ $(stat -c '%u' "$secret") == $(id -u) ]]

before=$(sha256sum "$secret" | cut -d ' ' -f 1)
bash "$repo_root/scripts/ensure-balance-jwt-secret.sh" \
  "$repo_root/tools/balance/generate_jwt_secret.py" "$secret" "$(id -un)"
after=$(sha256sum "$secret" | cut -d ' ' -f 1)
[[ "$before" == "$after" ]]

invalid="$tmp_dir/invalid/jwt-secret"
mkdir -m 700 "$(dirname -- "$invalid")"
head -c 31 /dev/zero > "$invalid"
chmod 600 "$invalid"
if bash "$repo_root/scripts/ensure-balance-jwt-secret.sh" \
  "$repo_root/tools/balance/generate_jwt_secret.py" "$invalid" "$(id -un)" >/dev/null 2>&1; then
  echo "invalid short key was accepted" >&2
  exit 1
fi
[[ $(stat -c '%a' "$invalid") == 600 ]]
[[ $(wc -c < "$invalid") == 31 ]]

shared="$tmp_dir/shared"
mkdir -m 755 "$shared"
if bash "$repo_root/scripts/ensure-balance-jwt-secret.sh" \
  "$repo_root/tools/balance/generate_jwt_secret.py" "$shared/key" "$(id -un)" >/dev/null 2>&1; then
  echo "insecure existing parent directory was accepted" >&2
  exit 1
fi
[[ $(stat -c '%a' "$shared") == 755 ]]
[[ ! -e "$shared/key" ]]
echo "balance JWT key provisioning checks passed"
