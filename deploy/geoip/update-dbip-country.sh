#!/bin/sh
set -eu

db_dir=/var/lib/geoip
db_path="$db_dir/dbip-country.mmdb"
marker_path="$db_dir/release"

mkdir -p "$db_dir"

update_database() {
    release=$1
    tmp_dir=$(mktemp -d "$db_dir/.update.XXXXXX")
    trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM

    archive="$tmp_dir/dbip-country.mmdb.gz"
    candidate="$tmp_dir/dbip-country.mmdb"
    url="https://download.db-ip.com/free/dbip-country-lite-${release}.mmdb.gz"

    if ! curl --fail --location --silent --show-error \
        --connect-timeout 20 --max-time 300 --retry 2 \
        "$url" --output "$archive"; then
        echo "DB-IP Lite update for $release failed; keeping the current database." >&2
        rm -rf "$tmp_dir"
        trap - EXIT HUP INT TERM
        return 1
    fi

    if ! gzip -t "$archive" || ! gzip -dc "$archive" > "$candidate"; then
        echo "DB-IP Lite archive for $release was invalid; keeping the current database." >&2
        rm -rf "$tmp_dir"
        trap - EXIT HUP INT TERM
        return 1
    fi

    size=$(wc -c < "$candidate" | tr -d ' ')
    if [ "$size" -lt 1000000 ] || ! mmdblookup --file "$candidate" --ip 1.1.1.1 country iso_code >/dev/null 2>&1; then
        echo "DB-IP Lite database for $release failed validation; keeping the current database." >&2
        rm -rf "$tmp_dir"
        trap - EXIT HUP INT TERM
        return 1
    fi

    # Same-filesystem rename keeps readers on either the old or complete new DB.
    chmod 0644 "$candidate"
    mv -f "$candidate" "$db_path"
    printf '%s\n' "$release" > "$tmp_dir/release"
    mv -f "$tmp_dir/release" "$marker_path"
    rm -rf "$tmp_dir"
    trap - EXIT HUP INT TERM
    echo "Installed DB-IP Lite country database release $release ($size bytes)."
}

while :; do
    release=$(date -u +%Y-%m)
    installed_release=
    if [ -r "$marker_path" ]; then
        installed_release=$(cat "$marker_path")
    fi

    if [ ! -s "$db_path" ] || [ "$installed_release" != "$release" ]; then
        update_database "$release" || true
    fi

    # DB-IP Lite is monthly; check hourly so a failed first download is retried
    # while an existing valid database remains available.
    sleep 3600
done
