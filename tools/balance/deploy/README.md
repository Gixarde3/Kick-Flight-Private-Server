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

Port: the WebUI listens on **127.0.0.1:8765** on the VPS and is reached through an SSH tunnel, so it
is never exposed. `KF_BALANCE_PASSWORD` in `/etc/kickflight-balance.env` adds HTTP basic auth if that
policy ever changes.

## Files

| file | action |
|---|---|
| `tools/balance/server.py`, `index.html`, `icons/` | delivered by CI to `/opt/kickflight/tools/balance/` |
| `tools/balance/deploy/kickflight-balance.service` | install as `/etc/systemd/system/kickflight-balance.service` |
| `tools/balance/deploy/kickflight-balance.env.example` | copy to `/etc/kickflight-balance.env` (mode `0600`) |
| `docs/disc_cards.json`, `docs/localize_layout.json` | optional (card text / Text tab); also delivered by CI |

CI only rsyncs when a deployed component changed. A `src/` change sets `api=true` (and therefore
`deploy=true`), which delivers `tools/balance/` too, because the whole tree is synced. A change under
`tools/` alone would **not** trigger a deploy, so land the C# override layer together with the tool.

## Steps

```bash
VPS=kickflight
APP=/opt/kickflight

# 0. Merge the branch to main. The CI deploy delivers src/ (rebuilds+restarts deploy-api-1) and the
#    whole tree, including tools/balance/, then runs its /health/ready smoke check.

# 1. Install the unit and the env file (once; later pushes only refresh server.py/index.html).
scp tools/balance/deploy/kickflight-balance.service "$VPS:/tmp/kickflight-balance.service"
scp tools/balance/deploy/kickflight-balance.env.example "$VPS:/tmp/kickflight-balance.env"
ssh "$VPS" "sudo -n install -m 644 /tmp/kickflight-balance.service /etc/systemd/system/kickflight-balance.service && \
            sudo -n install -m 600 /tmp/kickflight-balance.env /etc/kickflight-balance.env && \
            rm -f /tmp/kickflight-balance.service /tmp/kickflight-balance.env && \
            sudo -n systemctl daemon-reload && sudo -n systemctl enable --now kickflight-balance"

# 2. Verify on the host.
ssh "$VPS" "systemctl status --no-pager kickflight-balance | head -15; \
            curl -s -o /dev/null -w 'webui: %{http_code}\n' http://127.0.0.1:8765/"

# 3. Open it from the workstation (keep the tunnel while editing).
ssh -N -L 8765:127.0.0.1:8765 "$VPS"
#    then browse http://127.0.0.1:8765/

# 4. Edit, then click "Restart API to apply" (or, equivalently, on the host):
ssh "$VPS" "docker restart deploy-api-1"
#    and confirm /health/ready:
ssh "$VPS" "docker exec deploy-api-1 curl -fsS http://127.0.0.1:8080/health/ready"

# 5. Maintenance toggle (WebUI Maintenance tab, or directly):
ssh "$VPS" "docker exec -i deploy-api-1 curl -sS -X POST \
    http://127.0.0.1:8080/admin/maintenance -H 'Content-Type: application/json' -d '{\"mode\":\"hard\"}'"
```

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
