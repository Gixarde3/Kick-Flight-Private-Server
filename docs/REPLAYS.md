# Battle replays (Kicker + Featured tabs)

Server-side implementation of the client's replay feature. The design and the disassembly evidence behind it
are in `handoff/dsh-replay-1/report.md`; this file records what was actually built, the config surface, and
what is still unverified on a device.

Verified vs. not: everything below marked **verified** was checked statically against the pristine
`libil2cpp.so` (RVA == file offset) and against the server tests in
`tests/KickFlight.BootstrapApi.Tests/BattleReplayTests.cs`. Nothing here has been run on the emulator yet
(no APK was built for Part A).

## Flow

```
client (recording on by default)
   │  match ends
   ├─ POST /battle/end            -> server records rule/field/roster + human count, answers replayUploadFlag=true
   │  (custom: POST /customBattle/end -> same recording, response stays field-less; the cave sets the upload flag)
   ├─ POST /battle/upload         -> base64(gzip(archive)) stored, metadata indexed, response {}
   │
   ├─ POST /battleReplay/index    -> Featured (channel 1) + 14 kicker channels (1000+kickerId)
   └─ POST /battleReplay/play     -> { battleReplayUrl, encryptionKey } (32-char key, 10 min)
          GET  battleReplayUrl     -> IV || AES-256-CBC/PKCS7(gzip archive)
```

* Tab 1 ("Replay") is device-local and untouched by the server (owner decision 1).
* Tab 2 (Kicker) is data-driven from `config/masters_battle_replay_channel.json` (type 2, one row per
  kicker) and the index's per-channel replay list (latest `KickerChannelSize`, newest first).
* Tab 3 (Rank in the stock prefab) is repurposed as **Featured**: one type-3 row (id 1) whose list is the
  rotation's top `FeaturedCount` replays by human player count, ties broken newest first. The set is frozen
  per rotation and persisted in `featured.json`, so a restart serves the same set. The tab label is not
  patched (owner decision).
* `appMovieList` stays `[]` (the Pickup tab is out of scope).
* Custom-battle uploads require the Part B client cave (`scripts/re/replay_upload_cave.py`): the stock
  `GameManager.CallbackCustomBattleEndSuccess` never sets `ArchiveData.IsUploadReplayData`.

## Config keys

Section `Replays` (`Replays__X` environment / `Replays:X` config). Defaults are also in
`src/KickFlight.BootstrapApi/appsettings.json`.

| Key | Default | Meaning |
| --- | --- | --- |
| `Replays:Directory` | `.local/replays` | Storage root, resolved with `RepositoryPaths` (repo-relative unless absolute). |
| `Replays:MaxUploadBytes` | 67108864 (64 MiB) | Decoded gzip archive cap. Base64 is rejected above 4/3 of it. |
| `Replays:MaxDecompressedBytes` | 268435456 (256 MiB) | Gunzip cap (zip-bomb guard; the client `frames` cap is 50 MiB). |
| `Replays:KickerChannelSize` | 20 | Latest N replays per kicker channel. |
| `Replays:FeaturedCount` | 20 | K in the Featured set. |
| `Replays:RotationHours` | 3 | Featured recompute/freeze period. |
| `Replays:FeaturedWindowHours` | 6 (2 × rotation) | Only replays received within this window are candidates. |
| `Replays:RetentionDays` | 30 | Age after which a non-Featured replay is pruned (by server receipt time). |
| `Replays:MaxTotalBytes` | 5368709120 (5 GiB) | Total size budget; oldest non-Featured replays are pruned first. |
| `Replays:KeyLifetimeMinutes` | 10 | Lifetime of the per-download `/battleReplay/play` key. |

## Storage layout

```
<Replays:Directory>/
  blobs/<replayId>.bin    uploaded gzip archive, byte-for-byte (the plaintext D2CCodec wraps for playback)
  meta/<replayId>.json    one index row per replay (also the restart-time index source)
  featured.json           frozen Featured rotation { RotationStartUtc, ReplayIds[], ComputedUtc }
```

`replayId` is the battle id (`battle-N` / `custom-...`), or a SHA-256-derived id when it is not
filename-safe. A replay is only indexed once a blob exists.

### Where this lives on the VPS

The deployed tree is replaced by every CI deploy and `.local/` is excluded from the rsync, but `.local` is
mounted **read-only** inside the API container. Each compose file therefore gives the store a dedicated
writable sub-mount, following the `Masters:OverrideDir` / `/opt/kickflight/.local` convention:

| File | Mount | Setting |
| --- | --- | --- |
| `deploy/docker-compose.vps.yml` | `../.local/replays:/srv/replays` | `Replays__Directory=/srv/replays` (host `/opt/kickflight/.local/replays`) |
| `deploy/docker-compose.nas.yml` | `/mnt/Tanuki_1/kickflight/app/.local/replays:/srv/replays` | `Replays__Directory=/srv/replays` |
| `docker-compose.yml` (LAN) | `./.local/replays:/srv/replays` | `Replays__Directory=/srv/replays` |

Running `dotnet run` outside Docker uses the default `.local/replays` directly.

## Masters

Two new tables, registered in `DemoSessionApi.InitializeMasters`:

* `config/masters_battle_replay_channel.json` → `_encryptedMasters["BattleReplayChannel"]`:
  one `{id:1, battleReplayChannelType:3, name:"Featured", ...}` plus one
  `{id:1000+kickerId, battleReplayChannelType:2, name:<kicker>, kickerId:<n>, ...}` per kicker 1..14.
  Field names are `BattleReplayChannelMasterData` (`dump.cs:639875`).
* `config/masters_movie_category.json` → `_encryptedMasters["MovieCategory"]` (empty `[]`).

**Why those key names (verified):** the download name is the client's master class name without the
`Master` suffix. `MasterBase.get_ClassName` (RVA `0x1798DF4`) is a tail call to `Object.GetType()` followed
by `Type.get_Name` through the vtable (`ldp x2, x1, [x8, #0x198]`), i.e. it returns the concrete class name
(`BattleReplayChannelMaster`). Every master the server already serves follows the same convention
(`KickerParameterMaster` ↔ `KickerParameter`, `BattleRuleScaffoldMaster` ↔ …); the two properties are
`MasterManager.get_BattleReplayChannelMaster` (`dump.cs:526484`) and `get_MovieCategoryMaster`
(`dump.cs:526492`), so the keys are `BattleReplayChannel` and `MovieCategory`. **Not verified on device**:
the boot log is the final confirmation.

The `BattleReplayChannelInfo` ctor (`0x188D81C`, report §3.2) iterates the master rows and matches them to
`battleReplayChannelList` entries by `battleReplayChannelId`; that is why the index always serves all 15
channels, ids `1` and `1001..1014`.

## Uploaded archive format

The client's `replay.zip` is **not** a ZIP. Verified from disassembly:

* `ReplayUtility.ZipFiles` (RVA `0x1868578`) builds a `object[]{ length, name }` pair per file, calls
  `ReplayValue.SerializeObjects` (RVA `0x1868B84` → core `0x186AE3C` → `SerializeObject` `0x186AF18`), then
  `Stream.CopyTo`s the raw file bytes after it.
* `ReplayUtility.WriteDecompressedReplayData` (RVA `0x18698C4`) is the reader: for every member it calls
  `ReplayValue.DeserializeUInt` (RVA `0x18696FC`) then `DeserializeString` (RVA `0x18697E0`) then reads
  exactly `length` raw bytes.
* `DeserializeUInt` first calls `ReplayValue.ReadValueType` (RVA `0x186D50C`) and requires `TYPE_UINT = 2`;
  `ReadUInt` (RVA `0x186D6BC`) reads 4 bytes and `CustomBitConverter.ToUInt32` (RVA `0x17D4614`) copies them
  through `PutBytes` (RVA `0x17D40E8`, a forward byte copy) into a native `uint`, i.e. **little-endian**.
* `DeserializeString` requires `TYPE_STRING = 6`; `ReadString` (RVA `0x186DA6C`) reads an `int32` length with
  `ReadInt` (RVA `0x186D5D0`, same little-endian 4-byte read) and decodes `Encoding.UTF8.GetString(bytes, 0,
  length)`.
* `ReplayUtility.GetReplayWorkZipData` (`0x1868C04`) gzips the result with `D2CManager.GZipCompressFromBytes`
  (`0x1A6F9FC`), and `UploadReplayDataAsync` (`0x18A8AA0`) base64s it into `BattleUploadRequestData.uploadFile`.

So each member is:

```
[02] uint32-le length   [06] int32-le nameLen   name(UTF8)   raw bytes[length]
```

and the upload body is `base64( gzip( member... ) )` inside the D2C-encrypted JSON. `BattleReplayService.ParseArchive`
implements exactly this (unknown members such as `frames` are skipped but still validated).

The stored blob is the uploaded gzip bytes unchanged; playback plaintext is that same gzip.

## Playback contract (from the client)

`ReplaySelectCellView.<DownloadAndPlayReplayData>d__43.MoveNext` (`0x1789D04`) does
`NetworkManager.GetFromDataBinary(body, encryptionKey)` where `key = UTF8(encryptionKey)` and
`body[0..16)` is the IV. `D2CCodec.Encode` is the same AES-256-CBC/PKCS7 `IV || ciphertext`, so
`/battleReplay/blob/{keyId}` returns `D2CCodec.Encode(blob, UTF8(key), randomIV)`. The key must be exactly
32 bytes; `CreatePlayKey` emits 32 ASCII hex chars.

## What is verified / unverified

Verified by tests (`BattleReplayTests`, 9 tests):

* archive parser round-trip and rejection of a wrong type tag;
* human counting from `_isAi` / `_aiFlag` and the battle-end fallback snapshot;
* duplicate battleId keeps the first upload;
* Featured top-K by human count, frozen within a rotation, recomputed after it, restart-persistent;
* kicker channel filtering and newest-first order;
* `/battle/end` returns `replayUploadFlag: true` and keeps the reward fields;
* `/battleReplay/index` shape (15 channels, DTO field names, costume row ids) and
  `/battleReplay/play` → blob decrypts with the returned key back to the uploaded bytes;
* custom-battle end is recorded and `/battle/upload` fills rule/field from the archive.

Unverified / to check on a device:

* the master key names (`BattleReplayChannel`, `MovieCategory`) actually bind to `MasterManager`;
* the Kicker/Featured tabs render and playback enters the replay scene (report §7 list);
* whether `ReplayPlayFile.IsValid` accepts replays from another build (the index serves
  `applicationVersion` from the upload header verbatim);
* whether the Featured set should include custom battles (it does now that Part B uploads them);
* large-match upload timing / gzip ratio against the 64 MiB cap.
