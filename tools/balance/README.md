# Balance WebUI (`tools/balance/`)

A small local web tool to edit the Kick-Flight combat master tables (`masters_*.json`) per kicker and
per disc, with the kicker/disc icon, name and (discs) description next to the numbers, plus
Maintenance and "Restart API to apply" panels that drive the deployed API. One HTML file with
vanilla JS/CSS, a Python 3 standard-library server, no `pip install`, no `package.json`, no CDN.

## Where the masters actually live

The game server does **not** read masters from Postgres. `DemoSessionApi` is a singleton
(`src/KickFlight.BootstrapApi/Program.cs`) that reads `config/masters_*.json` once and caches the
encrypted copy in `_encryptedMasters`; changing a master needs an API restart. Postgres carries only
player state (`players`, `sessions`, `player_ranks`, `schema_meta`). The tool edits *master files*,
never the DB.

Saving never writes to `config/`. It writes a per-table override file, and the API's **master
override layer** (`MasterOverrides`, `Masters:OverrideDir` / `Masters__OverrideDir`) uses that file
instead of the base `config/masters_<table>.json` when it exists:

| directory | default | deployed (VPS) | role |
|---|---|---|---|
| base | this checkout's `config/` | `/opt/kickflight/config` | shipped, overwritten by the CI deploy |
| override | `.local/masters-overrides/` | `/opt/kickflight/.local/masters-overrides` | tuned values, **survive the deploy** |
| backups | `tools/balance/backups/` | `/opt/kickflight/.local/balance-backups` | one copy per overwritten file |

The API logs one line at startup listing the overridden tables, and `MasterVersion` (the client's
master hash) changes automatically, so clients pick the tuned values up after the restart. Masters
that are inline C# constants (`Field`, `BattleRank`, `Guardian`, ...) have no file and are not
overridable. `KF_BALANCE_MASTERS_DIR` is accepted as an alias of `KF_BALANCE_BASE_DIR`.

## Run it

```
start-balance.bat                         # repo root: starts the server and opens the browser (this PC only)
start-balance.bat lan                     # same, but also reachable from other devices on the LAN (URL is printed)
python tools/balance/server.py            # default port 8765, binds 127.0.0.1 only
python tools/balance/server.py --override-dir ~/kf-overrides --open
```

Then open <http://127.0.0.1:8765/> and sign in with an account inserted by an operator.

**After saving, click "Restart API to apply"** (locally `start-server.bat`; on the VPS the button
runs `docker restart deploy-api-1` and polls `/health/ready`). There is no hot reload.

## Environment (deployed use)

| variable | meaning |
|---|---|
| `KF_BALANCE_BASE_DIR` | base directory holding `masters_*.json` (default: this checkout's `config/`; alias `KF_BALANCE_MASTERS_DIR`) |
| `KF_BALANCE_OVERRIDE_DIR` | where saves are written and overrides read from (default: `.local/masters-overrides/`) |
| `KF_BALANCE_BACKUP_DIR` | where each replaced file is copied (default: `tools/balance/backups/`) |
| `KF_BALANCE_HOST` / `KF_BALANCE_PORT` | bind interface / port (default `127.0.0.1` / `8765`) |
| `KF_BALANCE_AUTH_DB` | required SQLite file for manually inserted users and server-side sessions (default: `.local/balance-auth/auth.sqlite3`); an empty user table denies sign-in |
| `KF_BALANCE_BASE_PATH` | mount prefix when served below a path such as `/balance` (default: empty) |
| `KF_BALANCE_ALLOWED_ORIGINS` | comma-separated exact HTTPS origins accepted through the TLS proxy |
| `KF_BALANCE_TRUSTED_PROXIES` | immediate proxy IPs allowed to supply `X-Real-IP` for login throttling |
| `KF_BALANCE_API_CONTAINER` | container the apply/maintenance defaults target (default `deploy-api-1`) |
| `KF_BALANCE_APPLY_CMD` | shell command that restarts the API (default `docker restart deploy-api-1`) |
| `KF_BALANCE_HEALTH_CMD` | shell command that must exit 0 when the API is ready (default `docker exec deploy-api-1 curl -fsS http://127.0.0.1:8080/health/ready`) |
| `KF_BALANCE_HEALTH_URL` | URL used to build the default health command (default `http://127.0.0.1:8080/health/ready`) |
| `KF_BALANCE_APPLY_TIMEOUT` / `KF_BALANCE_HEALTH_INTERVAL` | readiness poll budget in seconds / interval (default `120` / `2`) |
| `KF_BALANCE_ADMIN_URL` | full URL of `/admin/maintenance`; when set the tool calls it directly |
| `KF_BALANCE_ADMIN_CONTAINER` | container the default maintenance command `docker exec`s into (default `deploy-api-1`) |
| `KF_BALANCE_ADMIN_INTERNAL_URL` | URL curl uses inside that container (default `http://127.0.0.1:8080/admin/maintenance`) |
| `KF_BALANCE_ADMIN_CMD` / `KF_BALANCE_ADMIN_SET_CMD` | escape hatches: full shell commands whose stdout is the JSON status |
| `KF_BALANCE_ALLOWED_HOSTS` | extra comma-separated `Host` values accepted alongside `127.0.0.1:<port>`, `localhost:<port>` and `[::1]:<port>` (needed when binding to a LAN address or sitting behind a proxy) |

### Accounts and sessions

Authentication is mandatory and there is no signup or user-administration route. No account is
seeded at startup. The SQLite database contains a `users(username,password_hash,created_at)` table
and hashed opaque sessions; the application stores neither plaintext passwords nor session tokens.
Passwords use PBKDF2-HMAC-SHA256 with a per-password random salt and 600,000 iterations. Sessions
expire after eight hours and logout revokes the server-side record.

Initialize the service once so it creates the private database, then generate a hash interactively:

```bash
cd /opt/kickflight
sudo -u ubuntu python3 tools/balance/password_hash.py
```

Insert one row into the `users(username, password_hash, created_at)` table with a
parameterized SQLite statement as the service user, using the normalized username and hash
from the helper. Do not put the password or hash in shell arguments or history. Production
provisioning steps are in `tools/balance/deploy/README.md`.

For local development, use the same process with the default database at
`.local/balance-auth/auth.sqlite3`. The helper prompts for the password and prints only its derived
hash; it cannot create, list, or delete accounts.

Every UI/API route, export and static icon requires a valid session. The login endpoint is the only
unauthenticated API route. Login is rate-limited; the session cookie is Secure, HttpOnly,
SameSite=Strict, scoped to the configured base path, and has no Domain attribute. State-changing
requests require JSON and an allowed Origin. Requests also require an allowed Host to block DNS
rebinding.

## What it edits

Left sidebar: **Kickers** (14), **Discs**, **Text** and **Maintenance**. A text filter and, for discs,
rarity/type dropdowns. Every entry shows its icon from `tools/balance/icons/`.

Kicker panel — one section per source table (Stats, Passive, Passive condition, passive/kicker/special
skill and their extras, Basic Attack). Disc panel — the `Disc` row, the card text from
`docs/disc_cards.json`, the `Skill` row and every `SkillCondition` / `SkillHeal` / `SkillBlowOff` /
`SkillPullIn` / `SkillTrap` / `SkillCollision` / `SkillHit` row of that skill.

Numbers render as `<input type="number" step="any">`, booleans as checkboxes, strings as read-only
text. Row-link columns (`id`, `kickerId`, `attackCount`, `skillId`, `specialSkillId`,
`kickerAbilityId`) and the documented read-only columns are shown as read-only chips.

Every section whose table has an override file shows an **override** badge and a **Revert to base**
button. Reverting deletes the override file (after backing it up) so the base `config/` file applies
again; like a save, it needs the API restart. **Export overrides** downloads a zip of every override
file (`masters_*.json`), ready to copy into `config/` and commit when a tuned set should become the
shipped default.

## Adding and deleting effect rows

Most TRAP/effect discs have no row in one or more effect tables. For the effect tables the section
header carries **+ Add row** and every row carries **Delete row**:

| table | columns (new rows get the generator's neutral preset) |
|---|---|
| `masters_skill_condition.json` | `conditionType`, `duration`, `interval`, `effectValue`, `triggerType` — default AttackRate ×1.2 for 10 s on hit |
| `masters_skill_heal.json` | `skillHealType`, `coefficient` — default 30 % MaxHP |
| `masters_skill_blow_off.json` | `distance`, `speed`, `rigorTime`, `directionType` — default slam (Down) |
| `masters_skill_pull_in.json` | `distance`, `speed` |
| `masters_skill_trap.json` | `trapType`, `duration`, `radius`, `effectValue`, `interval`, `executeSeId`, `effectPath`, `screenEffectPath` |
| `masters_skill_collision.json` / `_hit.json` | guardian beam only (same shape as the generator) |

The new row's `id` is `max(existing ids) + 1` in that table, so it never collides, and the link
column (`skillId`; `specialSkillId` for special-skill extras) is filled with the skill being edited.
Column semantics are in `docs/COMBAT_MASTERS_FILL_IN.md`; the presets mirror
`scripts/generate_combat_masters.py`. The schema and defaults come from `GET /api/effect-schema`, so
the browser and the server agree.

Writes are strict: the posted rows must have the id/key set/type the effective file has. Added and
deleted rows are accepted **only** in the tables above; every other table must round-trip exactly
(same ids, same keys, same types). A `100.0` in an integer column is stored as `100`; a wrong type, a
duplicate id, an unknown/extra key or an add/delete on a core table is rejected with HTTP 400 and
nothing is written.

Before an override file is overwritten (or deleted by a revert) the server copies the file that was
in effect - the override if there was one, else the base `config/` file - to the backup dir as
`<name>-<yyyymmdd-hhmmss>.json`; `GET /api/diff/<name>` lists the field-level differences against the
newest backup.

## Apply tab (footer)

The footer tracks override files newer than the running API container's start time
(`docker inspect .State.StartedAt`) and shows "pending changes not yet applied". **Restart API to
apply** asks for confirmation with an explicit warning that live matches are dropped, runs
`KF_BALANCE_APPLY_CMD`, then polls `KF_BALANCE_HEALTH_CMD` until it succeeds or the timeout expires,
and reports the probe result. It never restarts by itself.

## Maintenance tab

Selecting **Maintenance** shows the current mode (`off` / `warning` / `hard`), the notice title and
message and buttons **Off**, **Soft (notice)** and **Hard (503)**. It proxies the game server's
`GET|POST /admin/maintenance` (`MaintenanceState`): `warning` adds one notice to `/home/index`,
`hard` answers 503 to every non-exempt POST and stops matchmaking, and both take an optional
title/message.

That endpoint only answers its own loopback and the API's HTTP port is never published, so the default
command runs curl **inside the API container**:

```
docker exec -i deploy-api-1 curl -sS -X POST \
    http://127.0.0.1:8080/admin/maintenance -H "Content-Type: application/json" -d @-
```

For a native/dev API on the same host set `KF_BALANCE_ADMIN_URL` instead. If the container has no
HTTP client, point `KF_BALANCE_ADMIN_CMD` / `KF_BALANCE_ADMIN_SET_CMD` at another loopback path.

## API

| route | result |
|---|---|
| `GET /api/kickers` | `{id, name, weaponType, roleType, skillId}` per kicker (override-aware) |
| `GET /api/discs` | `{id, name, rarityType, discType, skillId, effect, type, attribute, rarity}` per disc (override-aware) |
| `GET /api/effect-schema` | `{tables: {name: {fields: {col: type}, defaults: {...}}}}` |
| `GET /api/tables` | `[{name, source, overridden, base, overrideMtime, baseMtime}, ...]` |
| `GET /api/table/<name>` | full effective array: override file if present, else `config/masters_<name>.json` |
| `POST /api/table/<name>` | body `{"rows": [...]}`; validates, backs up, writes the **override** file, returns `{ok, written, override}` |
| `POST /api/table/<name>/revert` | deletes the override (backup first), returns `{ok, reverted, source}` |
| `GET /api/overrides/export` | zip download of every override file |
| `GET /api/apply` | `{pending, overrides, apiStartedAt, apiStartedAtIso, container, applyCmd, health}` |
| `POST /api/apply` | runs the restart command, polls health, returns `{ok, command, output, health, elapsedSeconds, pending}` |
| `GET /api/diff/<name>` | `{"changed": [{id, field, before, after}, ...]}` vs. the newest backup |
| `GET /api/maintenance` | current `{mode, title, message, noticeId, changedAtUtc}` (proxied) |
| `POST /api/maintenance` | body `{"mode": "off"\|"warning"\|"hard", "title"?, "message"?}` (proxied) |
| `GET /icons/<file>.png` | the extracted kicker/disc icons |
| `GET /` | `tools/balance/index.html` |

Every route (including static files), exports and state-changing actions require an authenticated
session. `GET /login` and `POST /api/login` are the only public UI/API routes.

## Deploy on the VPS

See `tools/balance/deploy/README.md` and `deploy/VPS.md`. Short version: the CI deploy delivers
`tools/balance/` to `/opt/kickflight/tools/balance`, and the `kickflight-balance` systemd unit runs
`python3 /opt/kickflight/tools/balance/server.py` on `127.0.0.1:8765` with
`/etc/kickflight-balance.env`. Public access is through
<https://kick-flight-fenix.us.ci/balance/>; the loopback port is not exposed publicly.

## Notes

* `masters_special_skill_heal.json` and `masters_special_skill_pull_in.json` do not exist in
  `config/`, so those two SS extras are not requested by the page (it never asks for a file that is
  not there).
* `docs/disc_cards.json` stores its entries as a list under `cards`; the server reads them by
  `discId` and falls back to empty strings for a disc without a card.
* The CI deploy rsyncs the repo over `/opt/kickflight` and excludes `.local/` and `.env`, so override
  files and backups there survive every push. `config/` edits do not: use the override dir.
