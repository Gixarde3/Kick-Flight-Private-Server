#!/bin/sh
set -eu

db=/var/lib/geoip/dbip-country.mmdb
runtime_conf=/etc/nginx/geoip-runtime.conf
enabled_marker=/run/geoip-enabled

database_valid() {
    [ -s "$db" ] && mmdblookup --file "$db" --ip 1.1.1.1 country iso_code >/dev/null 2>&1
}

activate_geoip() {
    candidate="$runtime_conf.new"
    cp /etc/nginx/geoip-enabled.conf "$candidate"
    mv -f "$candidate" "$runtime_conf"
    if nginx -t && nginx -s reload; then
        touch "$enabled_marker"
        echo "DB-IP country lookup enabled."
    else
        cp /etc/nginx/geoip-disabled.conf "$candidate"
        mv -f "$candidate" "$runtime_conf"
        echo "GeoIP activation failed; browser-language fallback remains active." >&2
    fi
}

if database_valid; then
    cp /etc/nginx/geoip-enabled.conf "$runtime_conf"
    touch "$enabled_marker"
else
    cp /etc/nginx/geoip-disabled.conf "$runtime_conf"
    echo "DB-IP country database unavailable; starting Nginx with browser-language fallback." >&2
fi

nginx -t
"$@" &
nginx_pid=$!

shutdown() {
    kill -TERM "$nginx_pid" 2>/dev/null || true
    wait "$nginx_pid" 2>/dev/null || true
    exit 0
}
trap shutdown TERM INT

# If the first DB-IP download failed, continue serving the site and enable
# country detection as soon as a validated database appears in the shared volume.
while kill -0 "$nginx_pid" 2>/dev/null; do
    if [ ! -e "$enabled_marker" ] && database_valid; then
        activate_geoip
    fi
    sleep 10 &
    wait "$!" || true
done

wait "$nginx_pid"
