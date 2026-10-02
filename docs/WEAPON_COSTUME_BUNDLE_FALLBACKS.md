# Weapon bundles for kicker costumes

`ResourceUtil.GetWeaponPath` requests `weapon/wp_<kicker>/wp_<kicker>_<costume>_<prop>.unity3d` for low models and adds 100 to the costume id for high models. Several of the 118 costume rows have no captured weapon bundle. A missing load leaves `Weapon.ModelCtr` null; `HighPlayerCharacter.SetCastShadow` then dereferences it.

Do not map a missing logical name to a donor's `objectName`. The client loads more than one weapon bundle in the same session, and Unity identifies the native serialized file by its CAB name. If two Octo names resolve to the same CAB, the second load can report that another file with the same name is already loaded; on costume changes this can lead to a null weapon controller.

## Generate independent fallbacks

The generator preserves every captured costume bundle. For each missing route it reads the canonical same-kicker, same-prop donor, makes a separate Octo bundle, and gives the copy its own logical `AssetBundle.m_Name`, container key, CAB name, Octo objectName, and Octo ID. It renames self-CAB `.resS` paths in `Texture2D`/`Mesh` stream data and copies the resource stream byte-for-byte. External archive references that point to a shared CAB stay unchanged; self references that name the copied CAB are rebased. The cloned root prefab, object graph, PPtrs, and any Animator references remain intact.

Original donor files are read-only. Outputs are written under `.local/weapon-costume-fallbacks/`; their `sourcePath` values are repo-local so the catalog builder and server can read them. A clean setup must have the captured donor bundles at the `sourcePath` locations in the sibling `Kick-Flight-Assets` checkout and UnityPy 1.25.3 in `.local/assets-venv`.

The default catalog builder invokes `scripts/add_weapon_costume_aliases.py` before it reads `title-minimum.json` or any clone `sourcePath`. It uses the current interpreter if that interpreter imports UnityPy 1.25.3, otherwise it selects `.local/assets-venv/bin/python` (or the Windows equivalent). It stops with an actionable error if neither interpreter or any captured donor is available. The fallback generator never calls the catalog builder, so generation has one direction and cannot recurse. It skips identical output writes, which makes repeated catalog builds idempotent.

Run:

```sh
.local/assets-venv/bin/python scripts/add_weapon_costume_aliases.py --check
.local/assets-venv/bin/python scripts/build-title-resource-catalog.py
```

The first command is optional for a normal catalog build; the builder runs generation automatically. `--check` verifies the already materialized local bundles without writing them.

The generator pins revision 31 and `fromRevisions` 0 through 31. The catalog builder writes ADD for a fresh `from=0` database, UPDATE for existing `from=1..30` databases, and an empty current delta at `from=31`. Re-running the generator is deterministic and refreshes the local clones from the original captured sources.

Validation:

```sh
.local/assets-venv/bin/python -m unittest tests/test_weapon_costume_aliases.py -v
.local/assets-venv/bin/python scripts/add_weapon_costume_aliases.py --check
```

The checks cover all 314 low/high weapon routes, all 35 independent fallback bundles, unique names/IDs/CABs, same-kicker/prop donor selection, UnityPy root/container and Animator PPtrs, preload references, and copied `.resS` ranges. They also compare deterministic rebuild outputs and verify the revision 31 fixture shape.

## Applying a costume in the client

In **Kicker > Custom**, tapping a costume card selects it and updates the preview. The costume is saved when leaving the kicker display; the bottom-right **Equip** button belongs to the gear flow and does not save the costume. For runtime verification, select the costume card, leave the kicker display, and confirm the `/kicker/change` request and updated state.
