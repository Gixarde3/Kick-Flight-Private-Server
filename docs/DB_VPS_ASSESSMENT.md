# Player database portability and VPS capacity

Assessment recorded 2026-10-07. This is a read-only investigation and migration recommendation; no database schema or data was changed.

## Current VPS facts

- The API is configured with `PlayerStore__DatabaseUrl`; the value was not printed or copied into this report. It selects `PostgresPlayerStore`, so production player state is in PostgreSQL rather than the JSON fallback.
- A sanitized query through the running API container reported PostgreSQL 17.11 (`server_version_num=170011`), current database size 9,084,928 bytes (about 8.66 MiB), and only the built-in `plpgsql` extension. No player rows were queried.
- The VPS inventory at inspection was 2 vCPUs, 7.7 GiB RAM with about 6.4 GiB available, and about 22 GiB free disk. This is ample headroom for the current small database and a private PostgreSQL service, subject to continued monitoring and a persistent-volume capacity check.
- The active deployment uses `deploy/docker-compose.vps.external-db.yml`; the repository also has a VPS PostgreSQL service definition in `deploy/docker-compose.vps.yml`. The external profile intentionally omits that local PostgreSQL service.

## What SQLite would require

The application uses no PostgreSQL arrays, custom enums, JSON operators, or non-core extensions. The `state` document is serialized and loaded as a whole, so it does not depend on PostgreSQL JSON querying. The actual portability work is in the store implementation, not in the shape of player data:

- The code is coupled to Npgsql and PostgreSQL SQL: `jsonb` casts, `bytea`, `timestamptz`, `nextval`, `pg_advisory_lock` / `pg_advisory_unlock`, `$n` parameters, `now()`, and `INSERT ... ON CONFLICT ... RETURNING`.
- SQLite could store the state document as `TEXT`, session keys as `BLOB`, and timestamps as UTC epoch integers. Its UPSERT syntax supports `ON CONFLICT`; generated player IDs and the cross-process migration lock would still need an explicit design. Foreign keys must be enabled on every SQLite connection (`PRAGMA foreign_keys=ON`).
- The current migrations are PostgreSQL-specific and run at API startup. A SQLite port must preserve the device-identity uniqueness guarantee under concurrent requests and simultaneous API starts, and must test file permissions, backups, restore, and lock contention on the VPS filesystem.

Primary references: [PostgreSQL 17 data types](https://www.postgresql.org/docs/17/datatype.html), [PostgreSQL sequences](https://www.postgresql.org/docs/17/functions-sequence.html), [PostgreSQL advisory locks](https://www.postgresql.org/docs/17/explicit-locking.html#ADVISORY-LOCKS), [Npgsql JSON mapping](https://www.npgsql.org/doc/types/json.html), [SQLite UPSERT](https://www.sqlite.org/lang_upsert.html), [SQLite foreign keys](https://www.sqlite.org/foreignkeys.html), and [SQLite WAL concurrency](https://www.sqlite.org/wal.html).

## Recommendation

Run PostgreSQL on the same VPS instead of porting the player store to SQLite. This keeps Npgsql, the schema, migrations, session persistence, and startup locking intact; it also removes the dependency on the expiring external database. The observed database is small and the VPS has substantial available memory. Keep PostgreSQL private to the compose network, persist its data outside ephemeral container storage, and retain encrypted off-VPS backups.

This recommendation is for the game's shared player state. SQLite remains suitable for the balance panel's local user/session file: that tool uses Python's built-in SQLite library, needs no database daemon, and its state is independent of the game API database.

Before cutover, take and verify an external `pg_dump`, provision the local PostgreSQL volume, restore the dump, and check `schema_meta`, player/session/rank row counts, the `player_id_seq` high-water mark, and API readiness against the restored database. Then switch the API to the local connection string and validate identity/session persistence with a returning client. Keep the external database available as rollback until the local service has passed that check and a fresh backup has been verified. No migration or cutover was performed during this assessment.
