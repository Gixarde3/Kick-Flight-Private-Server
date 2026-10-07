#!/usr/bin/env bash
set -Eeuo pipefail

app_dir=${KF_APP_DIR:-/opt/kickflight}
backup_dir=${KF_DB_BACKUP_DIR:-$app_dir/.local/db-migration-20261007/backups}
retention_days=${KF_DB_BACKUP_RETENTION_DAYS:-14}
compose_file="$app_dir/deploy/docker-compose.vps.yml"
env_file="$app_dir/.env"

[[ -d "$app_dir" && -f "$compose_file" && -f "$env_file" ]] || {
  echo "Kick Flight app, Compose file, or environment file is missing" >&2
  exit 1
}
[[ "$retention_days" =~ ^[1-9][0-9]*$ ]] || { echo "invalid backup retention" >&2; exit 2; }
command -v docker >/dev/null || { echo "Docker is required" >&2; exit 1; }

install -d -m 0700 -- "$backup_dir"
umask 077
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
final="$backup_dir/kickflight-$timestamp.dump"
[[ ! -e "$final" ]] || final="$backup_dir/kickflight-$timestamp-$$.dump"
tmp=$(mktemp "$backup_dir/.kickflight-$timestamp.XXXXXX")
cleanup() { rm -f -- "$tmp"; }
trap cleanup EXIT

compose=(docker compose --env-file "$env_file" --project-name deploy -f "$compose_file")
"${compose[@]}" config --quiet
"${compose[@]}" exec -T postgres pg_dump --username=kickflight --dbname=kickflight --format=custom --no-owner --no-acl > "$tmp"
[[ -s "$tmp" ]] || { echo "pg_dump produced an empty backup" >&2; exit 1; }
docker run --rm -v "$tmp:/backup.dump:ro" postgres:17.11-alpine pg_restore --list /backup.dump >/dev/null
chmod 0600 -- "$tmp"
mv -- "$tmp" "$final"

find "$backup_dir" -maxdepth 1 -type f -name 'kickflight-*.dump' -mmin "+$((retention_days * 1440))" -delete
printf 'PostgreSQL backup created: %s\n' "$final"
