#!/usr/bin/env bash
# Provision or validate the panel's signing key as the systemd service user. Never replace a key.
set -Eeuo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: ensure-balance-jwt-secret.sh GENERATOR SECRET_FILE SERVICE_USER" >&2
  exit 2
fi

generator=$1
secret_file=$2
service_user=$3
[[ -f "$generator" ]] || { echo "JWT key generator is missing" >&2; exit 1; }
[[ "$secret_file" == /* ]] || { echo "secret file path must be absolute" >&2; exit 2; }
id "$service_user" >/dev/null 2>&1 || { echo "service user does not exist" >&2; exit 1; }
service_group=$(id -gn "$service_user")
service_uid=$(id -u "$service_user")
secret_dir=$(dirname -- "$secret_file")

if [[ -L "$secret_dir" ]]; then
  echo "JWT secret directory must not be a symlink" >&2
  exit 1
elif [[ -e "$secret_dir" ]]; then
  [[ -d "$secret_dir" ]] || { echo "JWT secret parent is not a directory" >&2; exit 1; }
  dir_owner=$(stat -c '%u' -- "$secret_dir")
  dir_mode=$(stat -c '%a' -- "$secret_dir")
  [[ "$dir_owner" == "$service_uid" && "$dir_mode" == 700 ]] || {
    echo "existing JWT secret directory must be owned by the service user and have mode 0700" >&2
    exit 1
  }
elif [[ $(id -u) -eq 0 ]]; then
  mkdir -m 0700 -- "$secret_dir"
  chown "$service_user:$service_group" -- "$secret_dir"
else
  mkdir -m 0700 -- "$secret_dir"
fi

if [[ $(id -u) -eq 0 ]]; then
  run_as_service_user() { runuser -u "$service_user" -- "$@"; }
elif [[ $(id -un) == "$service_user" ]]; then
  run_as_service_user() { "$@"; }
else
  echo "run this helper as root or as the service user" >&2
  exit 1
fi

if [[ ! -e "$secret_file" && ! -L "$secret_file" ]]; then
  run_as_service_user python3 "$generator" --path "$secret_file"
fi

# load_jwt_secret verifies regular-file type, owner, mode 0600, and minimum key length.
run_as_service_user env PYTHONPATH="$(dirname -- "$generator")" python3 - "$secret_file" <<'PY'
import sys
from auth import load_jwt_secret
load_jwt_secret(sys.argv[1])
PY
