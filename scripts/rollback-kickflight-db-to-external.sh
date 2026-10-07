#!/usr/bin/env bash
# Restore post-cutover local player data to the preserved external PostgreSQL database, then switch only
# the API back to the external profile. Credentials are read from the private pre-cutover env file.
set -Eeuo pipefail

app_dir=${KF_APP_DIR:-/opt/kickflight}
state_dir=${KF_DB_MIGRATION_DIR:-$app_dir/.local/db-migration-20261007}
backup_dir=${KF_DB_BACKUP_DIR:-$state_dir/backups}
pre_cutover_env="$state_dir/pre-cutover.env"
external_baseline="$state_dir/external-baseline.json"
external_target="$state_dir/external-target.json"
fingerprint_sql="$app_dir/scripts/player-db-fingerprint.sql"
external_env_file=""
local_compose="$app_dir/deploy/docker-compose.vps.yml"
external_compose="$app_dir/deploy/docker-compose.vps.external-db.yml"
pg_image=${KF_POSTGRES_IMAGE:-postgres:17.11-alpine}

[[ $# -eq 0 ]] || { echo "usage: $0" >&2; exit 2; }
[[ -f "$app_dir/.env" && -f "$pre_cutover_env" && -f "$external_baseline" && -f "$external_target" && -f "$fingerprint_sql" && -f "$local_compose" && -f "$external_compose" ]] || {
  echo "app configuration, saved pre-cutover env, or Compose files are missing" >&2
  exit 1
}
[[ -d "$state_dir" && -d "$backup_dir" ]] || { echo "private migration/backup directory is missing" >&2; exit 1; }
[[ $(stat -c '%a' "$state_dir") == 700 && $(stat -c '%a' "$pre_cutover_env") == 600 && $(stat -c '%a' "$external_baseline") == 600 && $(stat -c '%a' "$external_target") == 600 ]] || {
  echo "migration directory and saved environment must have modes 0700 and 0600" >&2
  exit 1
}
command -v docker >/dev/null || { echo "Docker is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "Python 3 is required" >&2; exit 1; }
command -v curl >/dev/null || { echo "curl is required" >&2; exit 1; }
command -v flock >/dev/null || { echo "flock is required" >&2; exit 1; }
exec 9>"$app_dir/.ci/deploy.lock"
flock -x 9

local=(docker compose --env-file "$app_dir/.env" --project-name deploy -f "$local_compose")
"${local[@]}" config --quiet

umask 077
secret_dir=$(mktemp -d "$state_dir/.rollback-credentials.XXXXXX")
chmod 0700 "$secret_dir"
pgpass="$secret_dir/pgpass"
cleanup_secret() { rm -rf -- "$secret_dir"; }
trap cleanup_secret EXIT

# Parse only DATABASE_URL, write the password to a private libpq passfile, and prepare a private Compose
# environment that preserves current local settings while enabling the explicitly requested external mode.
IFS=$'\t' read -r external_host external_port external_db external_user < <(
  python3 - "$pre_cutover_env" "$pgpass" "$app_dir/.env" "$secret_dir/compose.env" "$external_target" <<'PY'
import os
import sys
import json
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

env_path, pgpass_path, local_env_path, external_env_path, target_path = map(Path, sys.argv[1:])
database_url = None
database_url_line = None
for raw in env_path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line.startswith("export "):
        line = line[7:].lstrip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    if key.strip() == "DATABASE_URL":
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        database_url = value
        database_url_line = f"DATABASE_URL={raw.split('=', 1)[1].strip()}"
        break
if not database_url:
    raise SystemExit("saved pre-cutover env has no DATABASE_URL")
uri = urlsplit(database_url)
if uri.scheme not in {"postgres", "postgresql"} or not uri.hostname or not uri.username or uri.password is None:
    raise SystemExit("saved DATABASE_URL is not a complete PostgreSQL URI")
query = parse_qs(uri.query)
if query.get("sslmode", [""])[0] != "require":
    raise SystemExit("external PostgreSQL URI must require TLS")
host = uri.hostname
port = uri.port or 5432
database = unquote(uri.path.lstrip("/"))
user = unquote(uri.username)
password = unquote(uri.password)
expected = json.loads(target_path.read_text())
if {"host": host, "port": port, "database": database, "user": user} != expected:
    raise SystemExit("external destination differs from the saved cutover target")
if not database or any(any(ch in item for ch in "\r\n\t") for item in (host, database, user, password)):
    raise SystemExit("external destination does not match the expected Kick Flight database")
def esc(value):
    return value.replace("\\", "\\\\").replace(":", "\\:")
pgpass_path.write_text(":".join((esc(host), str(port), esc(database), esc(user), esc(password))) + "\n", encoding="utf-8")
os.chmod(pgpass_path, 0o600)
kept = []
for raw in local_env_path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line.startswith("export "):
        line = line[7:].lstrip()
    if line and not line.startswith("#") and "=" in line:
        key = line.split("=", 1)[0].strip()
        if key in {"KF_DB_MODE", "DATABASE_URL"}:
            continue
    kept.append(raw)
external_env_path.write_text("\n".join(kept).rstrip() + "\nKF_DB_MODE=external\n" + database_url_line + "\n", encoding="utf-8")
os.chmod(external_env_path, 0o600)
print("\t".join((host, str(port), database, user)))
PY
)
external_env_file="$secret_dir/compose.env"
external=(docker compose --env-file "$external_env_file" --project-name deploy -f "$external_compose")
"${external[@]}" config --quiet
[[ -n "$external_host" && "$external_port" =~ ^[0-9]+$ && -n "$external_db" ]] || {
  echo "could not parse the saved external database target" >&2
  exit 1
}
printf 'External rollback target: %s:%s/%s (login %s)\n' "$external_host" "$external_port" "$external_db" "$external_user"
read -r -p "Type RESTORE $external_host/$external_db to proceed: " confirmation
[[ "$confirmation" == "RESTORE $external_host/$external_db" ]] || {
  echo "rollback cancelled" >&2
  exit 1
}

pg_container=$("${local[@]}" ps -q postgres)
[[ -n "$pg_container" ]] || { echo "local PostgreSQL container is not running" >&2; exit 1; }
local_version=$(docker exec "$pg_container" psql -X --username=kickflight --dbname=kickflight --tuples-only --no-align --command='SHOW server_version')
[[ "$local_version" == 17.11* ]] || { echo "local PostgreSQL version is not the expected 17.11" >&2; exit 1; }
network=$(docker inspect --format '{{range $name, $value := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$pg_container" | sed '/^$/d')
[[ -n "$network" && "$network" != *$'\n'* ]] || { echo "could not determine the private Compose network" >&2; exit 1; }

remote_psql() {
  docker run --rm --network "$network" \
    --volume "$pgpass:/run/secrets/pgpass:ro" \
    --env PGPASSFILE=/run/secrets/pgpass --env PGSSLMODE=require --env PGCONNECT_TIMEOUT=10 \
    "$pg_image" psql --host="$external_host" --port="$external_port" --username="$external_user" \
      --dbname="$external_db" --tuples-only --no-align "$@"
}
external_version=$(remote_psql --command='SHOW server_version')
[[ "$external_version" == 17.11* ]] || { echo "external PostgreSQL version is not the expected 17.11" >&2; exit 1; }

current_fingerprint="$secret_dir/current-fingerprint.json"
fingerprint_external() {
  docker run --rm --network "$network" \
    --volume "$pgpass:/run/secrets/pgpass:ro" --volume "$fingerprint_sql:/fingerprint.sql:ro" \
    --env PGPASSFILE=/run/secrets/pgpass --env PGSSLMODE=require --env PGCONNECT_TIMEOUT=10 \
    "$pg_image" psql --host="$external_host" --port="$external_port" --username="$external_user" \
      --dbname="$external_db" --no-psqlrc --quiet --tuples-only --no-align --file=/fingerprint.sql
}
require_external_baseline() {
  fingerprint_external > "$current_fingerprint"
  if ! cmp -s -- "$external_baseline" "$current_fingerprint"; then
    echo "external DB schema, table data, constraints, indexes, extension, or sequence differs from the cutover baseline; refusing to overwrite it" >&2
    return 1
  fi
  echo "external DB matches the saved cutover fingerprint"
}
require_external_baseline

# Stop the sole writer, preserve both sides, then restore atomically. On pre-restore failure the local API
# is restarted against the unchanged local database. Once restore commits, leave the API stopped on error.
api_stopped=false
external_restore_complete=false
restore_local_api_on_failure() {
  result=$?
  trap - EXIT ERR
  cleanup_secret
  if [[ $result -ne 0 && "$api_stopped" == true && "$external_restore_complete" == false ]]; then
    echo "rollback failed before external restore completed; restarting API on local PostgreSQL" >&2
    "${local[@]}" up -d --no-deps api || true
  elif [[ $result -ne 0 && "$external_restore_complete" == true ]]; then
    echo "external restore committed; API remains stopped to prevent writes to divergent databases" >&2
  fi
  exit "$result"
}
trap restore_local_api_on_failure EXIT ERR

"${local[@]}" stop api
api_stopped=true
"$app_dir/scripts/backup-kickflight-db.sh"
local_dump=$(find "$backup_dir" -maxdepth 1 -type f -name 'kickflight-*.dump' -printf '%T@ %p\n' | sort -nr | head -n 1 | cut -d ' ' -f 2-)
[[ -n "$local_dump" && -s "$local_dump" ]] || { echo "fresh local dump is missing" >&2; exit 1; }

external_dump_tmp=$(mktemp "$backup_dir/.external-before-rollback.XXXXXX")
external_dump="$backup_dir/external-before-rollback-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker run --rm --network "$network" \
  --volume "$pgpass:/run/secrets/pgpass:ro" \
  --env PGPASSFILE=/run/secrets/pgpass --env PGSSLMODE=require --env PGCONNECT_TIMEOUT=10 \
  "$pg_image" pg_dump --host="$external_host" --port="$external_port" --username="$external_user" \
    --dbname="$external_db" --format=custom --no-owner --no-acl > "$external_dump_tmp"
[[ -s "$external_dump_tmp" ]] || { echo "external pre-restore dump is empty" >&2; exit 1; }
docker run --rm --volume "$external_dump_tmp:/backup.dump:ro" "$pg_image" pg_restore --list /backup.dump >/dev/null
chmod 0600 "$external_dump_tmp"
mv -- "$external_dump_tmp" "$external_dump"
require_external_baseline

# Ensure the destination is reachable before we make any local change. Credentials are in the mounted pgpass file.
docker run --rm --network "$network" \
  --volume "$local_dump:/local.dump:ro" --volume "$pgpass:/run/secrets/pgpass:ro" \
  --env PGPASSFILE=/run/secrets/pgpass --env PGSSLMODE=require --env PGCONNECT_TIMEOUT=10 \
  "$pg_image" pg_restore --host="$external_host" --port="$external_port" --username="$external_user" \
    --dbname="$external_db" --clean --if-exists --single-transaction --no-owner --no-acl /local.dump
external_restore_complete=true
local_env_snapshot="$state_dir/local-before-rollback-$(date -u +%Y%m%dT%H%M%SZ).env"
[[ ! -e "$local_env_snapshot" ]] || { echo "local rollback environment snapshot already exists" >&2; exit 1; }
cp -- "$app_dir/.env" "$local_env_snapshot"
chmod 0600 -- "$local_env_snapshot"
root_env_tmp="$app_dir/.env.rollback.$$"
cp -- "$external_env_file" "$root_env_tmp"
chmod 0600 -- "$root_env_tmp"
mv -f -- "$root_env_tmp" "$app_dir/.env"
"${external[@]}" up -d --no-deps api
api_stopped=false
"${external[@]}" restart cdn grpc
ready=false
for attempt in $(seq 1 30); do
  if curl --fail --silent --max-time 5 http://127.0.0.1:18080/health/ready >/dev/null; then
    ready=true
    break
  fi
  sleep 2
done
[[ "$ready" == true ]] || { echo "external API did not become ready; inspect the running API before further writes" >&2; exit 1; }
printf 'Rollback completed. Local dump retained at %s; pre-restore external dump retained at %s\n' "$local_dump" "$external_dump"
