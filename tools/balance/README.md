# Balance WebUI (`tools/balance/`)

A small local web tool to edit the Kick-Flight combat master tables in `config/masters_*.json`
per kicker and per disc, with the kicker/disc icon, name and (discs) description next to the
numbers. Nothing here talks to the game server: the tool edits the JSON files on disk, and the
server picks them up the next time it starts.

## Run it

```
start-balance.bat                         # repo root: starts the server and opens the browser (this PC only)
start-balance.bat lan                     # same, but also reachable from other devices on the LAN (URL is printed)
python tools/balance/server.py            # default port 8765, binds 127.0.0.1 only
python tools/balance/server.py --host 0.0.0.0 --open   # LAN access + open the browser
python tools/balance/server.py --port 8766
```

Then open <http://127.0.0.1:8765/>. Python 3 standard library only — no `pip install`, no
`package.json`, no CDN: the page is one HTML file with vanilla JS/CSS and only ever fetches its
own origin, so it works offline.

**After saving, restart the game server with `start-server.bat` so `config/` is read again.**

## What it edits

Left sidebar: **Kickers** (14) or **Discs** (131), a text filter (name/id; for discs also the
card effect text) and, for discs, rarity and type dropdowns. Every entry shows its icon from
`tools/balance/icons/`.

Kicker panel — one section per source file:

| section | file |
|---|---|
| Stats | `config/masters_kicker_parameter.json` |
| Passive | `config/masters_kicker_ability.json` |
| Passive condition | `config/masters_kicker_ability_condition.json` |
| Passive skill &middot; *id* | when the passive's `value` is a skill id (Jay's bat bomb, 40001): that `config/masters_skill.json` row (`coefficient` = blast damage × ATK) and its `masters_skill_*` rows — `skill_trap`: `duration` = fuse (s), `radius` = blast end radius, `interval` = blast lifetime (s), `effectPath` = explosion SPFX |
| Kicker Skill | `config/masters_skill.json` (row `id == kicker_parameter.skillId`) |
| Kicker Skill extra &middot; *name* | `config/masters_skill_condition.json`, `_trap`, `_heal`, `_blow_off`, `_pull_in`, `_collision`, `_hit` (rows with that `skillId`) |
| Special Skill | `config/masters_special_skill.json` |
| Special Skill extra &middot; *name* | `config/masters_special_skill_condition.json`, `_trap`, `_hit`, `_collision`, `_bullet`, `_blow_off` (rows with `specialSkillId == kickerId`) |
| Basic Attack | `config/masters_weapon_attack.json`, grouped by `attackCount`, plus the matching `_hit` / `_collision` / `_bullet` / `_condition` rows for that kicker and `attackCount` |

Disc panel: the `config/masters_disc.json` row, the card text and rarity/type/attribute from
`docs/disc_cards.json`, then the disc's `config/masters_skill.json` row and its extra
`masters_skill_*` rows.

Numbers render as `<input type="number" step="any">`, booleans as checkboxes, strings as
read-only text. Row-link columns (`id`, `kickerId`, `attackCount`, `skillId`, `specialSkillId`,
`kickerAbilityId`) are shown as read-only chips, as are the skill `description`/`skillType`/
`skillActionType`/`skillCategoryType`/`targetAreaType`/`summonId`/`attributeType`/`seId` columns
and the kicker `roleType`/`weaponType` columns. Booleans under `weapon_attack_*` are read-only
(only the `special_skill_*` extras expose bools as editable), and rows cannot be added or
removed — this tool tunes values.

## Text tab (UI translations)

The third tab edits `config/masters_translation.json`, the Translation master every `LocalizeText` in the UI
prefabs and every `LocalizeManager.GetText(enum)` call resolves its text from (a key without a row shows as an
empty string in the game). The sidebar lists **screens** = the UI prefabs of the APK (`OutGameSettingWindow`,
`MenuWindow`, `DiscSortWindow`, ...), plus "(keys used from code / enums)" for rows no prefab references
(disc type labels `skillCategoryType.*`, status names `conditionType.*`, ...). Selecting a screen shows:

* a **wireframe** of that prefab at 1/3 scale (1080x1920 canvas) with one box per localized text, showing the
  current text (or the key, red border, when there is no row). Positions come from the prefabs' RectTransforms
  (`docs/localize_layout.json`, built by `python scripts/extract_localize_layout.py` from a decoded `base.apk`);
  layout groups / scroll lists are not simulated, so dashed boxes are elements whose static position falls
  outside the canvas. Click a box to jump to its input.
* the list of keys with their element path and an editable text; typing updates the box live. `Save` writes the
  table like any other; restart the game server and relaunch the client to see it.

Keys are never added here: run `python scripts/generate_translations.py` after adding entries to its `TEXTS` (it
also creates rows for every key the client can look up).

## Saving

Edited fields are highlighted, the footer counts them, and **Save** (or `Ctrl+S`) posts each
changed table to `POST /api/table/<name>` as one request per table, in sequence, reporting
success or failure per table. **Revert** reloads everything from `config/`.

Before a file is overwritten the server copies it to `tools/balance/backups/<name>-<yyyymmdd-hhmmss>.json`,
so a previous state can always be restored by hand (or compared with `GET /api/diff/<name>`,
which lists the field-level differences between the file on disk and its newest backup).

Writes are strict: the posted rows must have the same ids, the same key set and the same value
types as the file (`100.0` for an integer field is stored as `100`, booleans stay booleans,
strings stay strings). Anything else is rejected with HTTP 400 and the file is left untouched.

## API

| route | result |
|---|---|
| `GET /api/kickers` | `{id, name, weaponType, roleType, skillId}` per kicker |
| `GET /api/discs` | `{id, name, rarityType, discType, skillId, effect, type, attribute, rarity}` per disc |
| `GET /api/table/<name>` | full array of `config/masters_<name>.json` (404 if the name is not `^[a-z_]+$` or the file is missing) |
| `POST /api/table/<name>` | body `{"rows": [...]}`; validates, backs up, writes `indent=1` + trailing newline, returns `{"ok": true, "written": n}` |
| `GET /api/diff/<name>` | `{"changed": [{id, field, before, after}, ...]}` vs. the newest backup |
| `GET /icons/<file>.png` | the extracted kicker/disc icons |
| `GET /` | `tools/balance/index.html` |

## Notes

* `masters_special_skill_heal.json` and `masters_special_skill_pull_in.json` do not exist in
  `config/`, so those two SS extras are not requested by the page (it never asks for a file that
  is not there); `masters_skill_blow_off.json`, `masters_skill_pull_in.json` and
  `masters_weapon_attack_condition.json` exist but are empty arrays today.
* `docs/disc_cards.json` stores its entries as a list under `cards`; the server reads them by
  `discId` and falls back to empty strings for a disc without a card.
* The tool writes with a trailing newline, so the first save of a file adds one newline at the
  end of the file compared to the generator output.
