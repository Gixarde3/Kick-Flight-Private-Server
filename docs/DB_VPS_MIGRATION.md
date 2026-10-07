# Player database migration to the VPS

Migration date: 2026-10-07. This report records the pre-cutover assessment and restore rehearsal; update the
cutover and live verification section after the production switch completes.

## Starting point

The API used PostgreSQL 17.11 from an external provider through `PlayerStore__DatabaseUrl`.
`PlayerStore__ConnectionString` was empty. The source database was about 8.66 MiB, had only the built-in
`plpgsql` extension, and contained about 2,525 rows across four tables. The VPS inventory at assessment was
2 vCPUs, 7.7 GiB RAM, and about 22 GiB free disk.

The API store uses Npgsql and PostgreSQL-specific SQL. SQLite remains the separate store for balance-panel
users and sessions; it is not part of this migration.

## Restore rehearsal

A consistent external `pg_dump` snapshot was restored to PostgreSQL 17.11-alpine before cutover. The snapshot
was 164,966 bytes. Comparison passed for four tables and all 2,525 rows: table counts and per-row JSON MD5
hashes matched. The schema had seven constraints, six indexes, no identity columns, and one sequence;
`player_id_seq` matched at `last_value=1,002,214` and `is_called=true`. Column definitions, player IDs,
sessions, and the `plpgsql` extension matched.

The live cutover and end-to-end service checks will be recorded here after they complete.

## Runtime topology

The API uses `deploy/docker-compose.vps.yml`; PostgreSQL 17.11-alpine uses the persistent Docker volume
`postgres-data` on the private Compose `backend` network. Port 5432 is not published. The application login
is `kickflight` and is configured as a database owner without superuser or role/database-creation privileges.
The root `.env` holds `KF_DB_PASSWORD` and a separate `KF_PG_SUPERUSER_PASSWORD`; both remain outside Git.

Daily dumps are stored under `/opt/kickflight/.local/db-migration-20261007/backups/`, with 14-day retention,
private directory/file modes `0700`/`0600`, and a systemd timer at 02:15 UTC. A same-VPS backup does not
protect against loss of the VPS; maintain an encrypted off-host copy for disaster recovery.

For rollback after local writes, run the guarded and versioned
`/opt/kickflight/scripts/rollback-kickflight-db-to-external.sh`. It checks the external database against the
private `external-baseline.json` cutover fingerprint (including schema, table rows, constraints, indexes,
extensions, and sequences), stops the API writer, saves a fresh local dump and a pre-restore external dump,
restores local state in one transaction, and only then starts the API with the saved pre-cutover configuration.
It aborts without overwriting the target if the external DB drifted after the cut. Switching the Compose
profile alone would discard writes made after cutover.
