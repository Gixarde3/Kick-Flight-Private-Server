# Deploying the balance WebUI on the production VPS

Production host (verified read-only): `ssh kickflight` (`ubuntu@kick-flight-fenix.us.ci`), app
directory `/opt/kickflight`, compose project `deploy` using
`deploy/docker-compose.vps.external-db.yml`, containers `deploy-api-1`, `deploy-cdn-1`,
`deploy-caddy-1`, `deploy-photon-1`, `deploy-grpc-1`, `deploy-geoip-db-1`. The API listens on
`:8080` only inside its container and `:18081` is the gRPC/nginx side; `:18080` is public through
CDN/Caddy.

Two facts drive this plan:

* **Masters are files, not a database.** `DemoSessionApi` reads `masters_*.json` once at startup; a
  change is applied by restarting the API (`docker restart deploy-api-1`). Postgres holds only player
  state.
* **The API reads the override dir from the persistent `.local/` mount.** `/opt/kickflight/.local`
  is mounted at `/srv/repo/.local` (read-only) and `/opt/kickflight/config` at `/srv/repo/config`
  (read-only). With `KF_REPO_ROOT=/srv/repo`, the default `Masters:OverrideDir`
  (`.local/masters-overrides`) resolves to exactly `/opt/kickflight/.local/masters-overrides` on the
  host. CI excludes `.local/` from the rsync, so tuned overrides survive every deploy; `config/`
  does not.

The WebUI listens only on **127.0.0.1:8765**. Caddy routes the HTTPS prefix
`https://kick-flight-fenix.us.ci/balance/` to that loopback service and keeps the prefix intact.
All other paths continue to the existing API/CDN on port 18080. Port 8765 is never public. The app
requires a manually inserted account in its private panel SQLite database and a private JWT signing
key. These authentication changes affect only the panel database; they do not migrate or change the
game API's PostgreSQL database or its deployment services.

## Files

| file | action |
|---|---|
| `tools/balance/server.py`, `auth.py`, `password_hash.py`, `login.html`, `index.html`, `icons/` | delivered by CI to `/opt/kickflight/tools/balance/` |
| `tools/balance/deploy/kickflight-balance.service` | install as `/etc/systemd/system/kickflight-balance.service` |
| `tools/balance/deploy/kickflight-balance.env.example` | copy to `/etc/kickflight-balance.env` (mode `0600`) |
| `deploy/caddy/Caddyfile` | delivered with the compose project; routes `/balance` to the local UI |
| `docs/disc_cards.json`, `docs/localize_layout.json` | optional (card text / Text tab); also delivered by CI |

CI only rsyncs when a deployed component changed. A `src/` change sets `api=true` (and therefore
`deploy=true`), which delivers `tools/balance/` too, because the whole tree is synced. Changes under
`tools/balance/` or the balance JWT deploy helpers trigger the panel deployment directly.

## Steps

```bash
VPS=kickflight
APP=/opt/kickflight

# 0. Merge the branch to main. The CI deploy delivers src/ (rebuilds+restarts deploy-api-1) and the
#    whole tree, including tools/balance/, then runs its /health/ready smoke check.

# 1. Install the unit and the env file (once; later pushes refresh the application files).
scp tools/balance/deploy/kickflight-balance.service "$VPS:/tmp/kickflight-balance.service"
scp tools/balance/deploy/kickflight-balance.env.example "$VPS:/tmp/kickflight-balance.env"
ssh "$VPS" "sudo -n install -m 644 /tmp/kickflight-balance.service /etc/systemd/system/kickflight-balance.service && \
            sudo -n install -m 600 /tmp/kickflight-balance.env /etc/kickflight-balance.env && \
            rm -f /tmp/kickflight-balance.service /tmp/kickflight-balance.env && \
sudo -n systemctl daemon-reload && sudo -n systemctl enable kickflight-balance"

# Create the independent 256-bit signing key after CI has delivered the helper and before
# starting the service. This fails if the key exists and never prints or overwrites the key.
ssh "$VPS" "cd /opt/kickflight && sudo -u ubuntu python3 tools/balance/generate_jwt_secret.py \
    --path /opt/kickflight/.local/balance-auth/jwt-secret"

# Start after the key exists.
ssh "$VPS" "sudo -n systemctl restart kickflight-balance"

# 2. Verify the private listener and public login page.
ssh "$VPS" "systemctl status --no-pager kickflight-balance | head -15; \
            curl -s -o /dev/null -w 'login: %{http_code}\n' http://127.0.0.1:8765/balance/login; \
            curl -s -o /dev/null -w 'public: %{http_code}\n' https://kick-flight-fenix.us.ci/balance/login"

# 3. Open https://kick-flight-fenix.us.ci/balance/ in a browser.

# 4. Edit, then click "Restart API to apply" (or, equivalently, on the host):
ssh "$VPS" "docker restart deploy-api-1"
#    and confirm /health/ready:
ssh "$VPS" "docker exec deploy-api-1 curl -fsS http://127.0.0.1:8080/health/ready"

# 5. Maintenance toggle (WebUI Maintenance tab, or directly):
ssh "$VPS" "docker exec -i deploy-api-1 curl -sS -X POST \
    http://127.0.0.1:8080/admin/maintenance -H 'Content-Type: application/json' -d '{\"mode\":\"hard\"}'"
```

## Create the first operator account

The service starts with an empty user table and denies all logins until an operator adds an account.
After the first service start, generate the password hash interactively and insert it manually:

```bash
ssh -t "$VPS" "cd /opt/kickflight && sudo -u ubuntu python3 tools/balance/password_hash.py"
ssh -t "$VPS" "sudo -n -u ubuntu python3 -c 'import sqlite3
import time
import unicodedata

username = unicodedata.normalize(\"NFKC\", input(\"Username: \")).strip().casefold()
assert username, \"username cannot be empty\"
password_hash = input(\"PBKDF2 hash from the helper: \")
db = sqlite3.connect(\"/opt/kickflight/.local/balance-auth/auth.sqlite3\")
db.execute(\"INSERT INTO users(username, password_hash, created_at) VALUES (?, ?, ?)\",
           (username, password_hash, int(time.time())))
db.commit()
db.close()'"
```

Use the actual hash from the helper at the Python prompt; do not place the password or hash in a
command-line argument, shell history, or a deployment secret file. The app intentionally has no
signup, user-management route, or account-creation CLI.

## Committing overrides back to git

Overrides live in `/opt/kickflight/.local/masters-overrides/masters_<table>.json` and are git-ignored
on the host. **Export overrides** in the UI downloads a zip of exactly those files. To make a tuned
set the shipped default:

```bash
unzip masters-overrides.zip -d /tmp/kf-overrides
cp /tmp/kf-overrides/masters_*.json config/            # in the checkout
git add config/ && git commit -m "config: tuned masters from the VPS balance UI"
# The push rebuilds the API (config/ sets api+full) and ships the new base files.
```

After that the override files can be reverted in the UI table by table; the base files already carry
the tuned values.

## Rollback

```bash
ssh "$VPS" "sudo -n systemctl disable --now kickflight-balance"
```

Restore an edited table from its backup in `/opt/kickflight/.local/balance-backups/` (or revert it in
the UI), then restart the API. Removing the whole override directory restores the shipped masters.
