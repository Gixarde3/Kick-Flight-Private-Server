# Generated kicker skin thumbnails

Generated thumbnail PNGs live in `assets/generated/skin-thumbnails/`; each has a
durable original under `source/` and a provenance record in `provenance.json`.
The normalized PNGs are transparent RGBA at 200×162. Their asset names follow
`thumbnail_pc_<kickerId 3 digits>_<costumeId 3 digits>.png`.

The builder emits four independent AssetBundles per skin because the client uses
four routes with different Sprite and Texture2D dimensions:

| Route | Texture size | Image fit |
|---|---:|---|
| `ui/kicker` | 116×77 | Contain, preserving the full portrait |
| `ui/kicker/oblique` | 200×162 | Contain, preserving the full portrait |
| `ui/kicker/circle` | 76×76 | Center cover under a circular alpha mask |
| `ui/kicker/r20` | 132×132 | Center cover on opaque white underlay, with a 20 px rounded-corner mask |

Each bundle keeps its route's Sprite, Texture2D, and AssetBundle serialization,
uses a full-rectangle Sprite mesh so costume headwear does not inherit the donor
portrait's trimmed mesh, and rewrites the texture, Sprite, AssetBundle, container,
and CAB identities. Textures are saved as inline RGBA32 (`m_TextureFormat=4`, one
mip, no external stream). A round-trip through UnityPy validates dimensions,
alpha, PPtrs, names, and container paths.
Each Octo entry keeps its allocated ID and uses a unique six-character ASCII
alphanumeric `objectName`, matching the format used by existing resources.
The durable 200×162 source PNGs remain transparent. Only the `r20` texture adds
an opaque white backing beneath the portrait to match the existing rounded card;
the direct, oblique, and circle textures retain their transparent backgrounds.

With all 11 final PNGs present, the canonical catalog builder runs the weapon
fallback and thumbnail generators before reading `title-minimum.json`. The
thumbnail generator creates 44 bundles in
`content/resources/ui-kicker-skin-thumbnails/`, adds their entries, and advances
the revision to at least 32 while preserving newer revisions. It does not call
the catalog builder, so standalone bundle generation cannot recurse. Run the
canonical command to regenerate the catalog and fixtures:

```bash
.local/assets-venv/bin/python scripts/build-title-resource-catalog.py
```

Until then, prototype selected complete inputs without touching the catalog:

```bash
.local/assets-venv/bin/python scripts/build-kicker-skin-thumbnail-bundles.py \
  --only 001_022 002_022 003_022
```

Selected builds go to `.local/missing-icons/search/built-bundles/`. The full run
stops before writing if any final PNG is missing or not 200×162 with alpha.

The 11 logical target keys are:

```text
thumbnail_pc_001_022  thumbnail_pc_002_022  thumbnail_pc_003_022
thumbnail_pc_003_052  thumbnail_pc_006_022  thumbnail_pc_008_052
thumbnail_pc_011_051  thumbnail_pc_012_022  thumbnail_pc_014_002
thumbnail_pc_014_003  thumbnail_pc_014_051
```
