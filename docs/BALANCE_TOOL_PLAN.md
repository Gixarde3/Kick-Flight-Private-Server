# Balance WebUI (`tools/balance/`) — plan (2026-09-20)

Goal: a local web tool to edit the combat master tables in `config/masters_*.json` per kicker and per disc, with the
kicker/disc icon, name and (discs) description, so KS/SS/disc/kicker stats, SS charge and KS cooldowns can be tuned
without touching JSON by hand. The server reads the JSON files at startup, so after saving the user runs
`start-server.bat` (already the normal workflow); the tool must not need the game server.

## Data sources (all relative to the repo root)

| what | file | key |
|---|---|---|
| kicker names | `config/masters_kicker.json` | `id`, `name` |
| kicker stats | `config/masters_kicker_parameter.json` | row per `kickerId`: `maxHp attack defense speed moveSpeedCoefficient moveTurningSpeedCoefficient moveDashSpeedCoefficient groundMoveSpeedCoefficient groundMoveTurningSpeedCoefficient acceleration attackTargetSearchDistance attackTargetSearchAngle dashAttackRange dashAttackSpeedWeight dashAttackTime dashAttackFollowThroughTime footHeight height recoveryBoostPoint recoveryBoostPointGround addMoveSpecialSkillPoint addWeaponAttackSpecialSkillPoint hpCorrection attackCorrection` (+ `skillId`, `weaponType`, `roleType` read-only) |
| kicker passive | `config/masters_kicker_ability.json` | row per `kickerId`: `triggerType time value overlapCount` |
| kicker skill (KS) | `config/masters_skill.json` rows with `id == KickerParameter.skillId` (20001-20014): `description coolTime range speed coefficient` (+ `skillActionType targetAreaType` read-only) |
| KS extras | `config/masters_skill_condition.json`, `masters_skill_trap.json`, `masters_skill_heal.json`, `masters_skill_blow_off.json`, `masters_skill_pull_in.json` rows with `skillId == <KS id>` — show every numeric column editable |
| special skill (SS) | `config/masters_special_skill.json` row per `kickerId`: `duration coefficient range finishTime` |
| SS extras | `config/masters_special_skill_condition.json`, `_trap`, `_hit`, `_collision`, `_bullet`, `_blow_off`, `_pull_in`, `_heal` rows with `specialSkillId == kickerId` — every numeric/bool column editable |
| basic attack | `config/masters_weapon_attack.json`, `_hit`, `_collision`, `_bullet`, `_condition` rows with `kickerId` — numeric columns editable, grouped by `attackCount` |
| discs | `config/masters_disc.json` (131 rows): `name rarityType discType minHp maxHp minAttack maxAttack minCoefficient maxCoefficient minCoolTime maxCoolTime` (+ `skillId`) |
| disc skill | `config/masters_skill.json` row `id == Disc.skillId` (10001-10131): `coolTime range speed coefficient` (+ `skillActionType skillCategoryType targetAreaType` read-only) and the `masters_skill_*` extra rows with that `skillId` |
| disc description | `docs/disc_cards.json`: object keyed by disc id (string) → `name`, `type`, `attribute`, `effect` (EN text), `effect_jp`, `rarity`. Skip the `_about` key. |
| icons | `tools/balance/icons/kicker_<kickerId>.png`, `tools/balance/icons/disc_<discId>.png` (already extracted) |

`masters_translation.json` is not needed.

## Implementation

Scope — create only these files, change nothing else:

* `tools/balance/server.py` — Python 3, standard library only (`http.server`, `json`, `pathlib`). No pip
  dependencies. Serves `tools/balance/index.html`, the icons folder, and a JSON API:
  * `GET /api/kickers` → list of `{id, name, weaponType, roleType, skillId}` merged from `masters_kicker` + `masters_kicker_parameter`.
  * `GET /api/discs` → list of `{id, name, rarityType, discType, skillId, effect, type, attribute}` merged from `masters_disc` + `docs/disc_cards.json` (missing card → empty strings).
  * `GET /api/table/<name>` → the full array of `config/masters_<name>.json` (name validated against `^[a-z_]+$`, file must exist).
  * `POST /api/table/<name>` with body `{"rows": [...]}` → validates every row keeps the same keys and value types as the current row with the same `id` (numbers stay numbers, ints stay ints — a value such as `100.0` for an int field is accepted and stored as `100`; bools stay bools; strings unchanged), writes the file back with `json.dump(rows, f, ensure_ascii=False, indent=1)` and a trailing newline, writes a timestamped backup to `tools/balance/backups/<name>-<yyyymmdd-hhmmss>.json` before overwriting, and returns `{"ok": true, "written": n}`. Reject with 400 and a message on any validation failure; never write a partial file.
  * `GET /api/diff/<name>` → for convenience returns the current rows vs. the most recent backup for that table (`{"changed": [ {id, field, before, after} ... ]}`), empty list if no backup.
  * Default port 8765; `--port` flag; prints the URL on start. Bind 127.0.0.1 only.
* `tools/balance/index.html` — single file, vanilla JS + CSS, no CDN, no frameworks (the tool must work offline).
  * Left sidebar: two tabs **Kickers** / **Discs**, a text filter box (matches name/id, for discs also the effect
    text), and for discs a rarity and a `type` dropdown filter. Each list entry shows the icon (48 px), name and id.
  * Main panel for a selected kicker: header with icon + name + role/weapon; sections **Stats** (kicker_parameter
    row), **Passive** (kicker_ability row), **Kicker Skill** (skill row + each extra table that has rows for it),
    **Special Skill** (special_skill row + extras), **Basic Attack** (weapon_attack rows by attackCount with their
    hit/collision/bullet/condition rows). Every numeric field is an `<input type=number step=any>`, bools a checkbox,
    strings shown read-only. Group headings name the source file.
  * Main panel for a selected disc: icon, name, rarity/type/attribute, the effect text, then **Disc** (disc row) and
    **Skill** (skill row + extras).
  * A sticky footer: "Unsaved changes: N", **Save** (POSTs every dirty table, one request per table, in sequence;
    shows per-table result), **Revert** (reloads from the API), and a note "restart the game server
    (`start-server.bat`) to apply". Highlight dirty inputs. Ctrl+S saves.
  * Keep all table data in memory as loaded from `/api/table/...`; edits mutate those arrays; Save sends whole arrays.
* `tools/balance/README.md` — how to run (`python tools/balance/server.py`), what it edits, the restart note, where
  backups go.

Out of scope: editing translation/name strings, adding/removing rows, the generator scripts, the C# server, any
file outside `tools/balance/`. Do not add build tooling, package.json, or frameworks.

## Acceptance checklist

- [ ] `python tools/balance/server.py` starts on 127.0.0.1:8765 with no third-party imports; `GET /api/kickers` returns 14 entries with names from `masters_kicker.json`; `GET /api/discs` returns 131 entries with `effect` filled from `docs/disc_cards.json`.
- [ ] `GET /api/table/skill` returns the 147 rows of `config/masters_skill.json`; a name outside `^[a-z_]+$` or a missing file returns 404.
- [ ] `POST /api/table/special_skill` with one changed `duration` rewrites the file (1-space indent, trailing newline, ids/keys/types unchanged, ints stay ints) and creates a backup under `tools/balance/backups/`; a row with a changed key set or a string where a number was returns 400 and leaves the file untouched.
- [ ] `index.html` lists kickers and discs with icons from `tools/balance/icons/`, filters by text/rarity/type, and the kicker panel shows Stats, Passive, Kicker Skill, Special Skill and Basic Attack sections populated from the right rows (`skillId` link for KS, `kickerId` for SS/weapon rows); the disc panel shows the disc row, its skill row, the extra skill rows and the effect text.
- [ ] Editing fields marks them dirty, the footer counts them, Save posts only dirty tables and reports success/failure per table, Revert reloads; no console errors.
- [ ] No files outside `tools/balance/`, no dependencies, no TODO/stub code, no fetches to any host but the tool's own origin.
