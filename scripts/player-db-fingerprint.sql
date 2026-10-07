\set ON_ERROR_STOP on
SET TIME ZONE 'UTC';

-- External poolers may recycle a backend session after the previous psql client exits.
DROP TABLE IF EXISTS pg_temp._kf_table_fingerprints;
DROP TABLE IF EXISTS pg_temp._kf_sequence_fingerprints;
CREATE TEMP TABLE _kf_table_fingerprints (
  schema_name text NOT NULL,
  table_name text NOT NULL,
  row_count bigint NOT NULL,
  row_md5 text NOT NULL
);
CREATE TEMP TABLE _kf_sequence_fingerprints (
  schema_name text NOT NULL,
  sequence_name text NOT NULL,
  last_value text,
  is_called boolean
);

DO $fingerprint$
DECLARE
  item record;
  rows bigint;
  digest text;
  seq_value text;
  seq_called boolean;
BEGIN
  FOR item IN
    SELECT table_schema, table_name
      FROM information_schema.tables
     WHERE table_type = 'BASE TABLE'
       AND table_schema NOT IN ('pg_catalog', 'information_schema')
       AND table_schema NOT LIKE 'pg_temp_%'
       AND table_schema NOT LIKE 'pg_toast%'
     ORDER BY table_schema, table_name
  LOOP
    EXECUTE format(
      'SELECT count(*), md5(coalesce(string_agg(row_json, E''\n'' ORDER BY row_json), '''')) '
      'FROM (SELECT to_jsonb(t)::text AS row_json FROM %I.%I AS t) AS rows',
      item.table_schema, item.table_name
    ) INTO rows, digest;
    INSERT INTO _kf_table_fingerprints VALUES (item.table_schema, item.table_name, rows, digest);
  END LOOP;

  FOR item IN
    SELECT schemaname, sequencename
     FROM pg_catalog.pg_sequences
     WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
       AND schemaname NOT LIKE 'pg_temp_%'
       AND schemaname NOT LIKE 'pg_toast%'
     ORDER BY schemaname, sequencename
  LOOP
    EXECUTE format('SELECT last_value::text, is_called FROM %I.%I', item.schemaname, item.sequencename)
      INTO seq_value, seq_called;
    INSERT INTO _kf_sequence_fingerprints VALUES
      (item.schemaname, item.sequencename, seq_value, seq_called);
  END LOOP;
END
$fingerprint$;

SELECT jsonb_build_object(
  'server_version_num', current_setting('server_version_num'),
  'extensions', coalesce((
    SELECT jsonb_agg(jsonb_build_object('name', extname, 'version', extversion) ORDER BY extname)
      FROM pg_catalog.pg_extension
  ), '[]'::jsonb),
  'columns', coalesce((
    SELECT jsonb_agg(jsonb_build_object(
      'schema', table_schema, 'table', table_name, 'column', column_name,
      'ordinal', ordinal_position, 'type', data_type, 'udt', udt_name,
      'nullable', is_nullable, 'default', column_default,
      'identity', is_identity, 'generated', is_generated,
      'char_length', character_maximum_length, 'numeric_precision', numeric_precision,
      'numeric_scale', numeric_scale
    ) ORDER BY table_schema, table_name, ordinal_position)
      FROM information_schema.columns
     WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
       AND table_schema NOT LIKE 'pg_temp_%'
       AND table_schema NOT LIKE 'pg_toast%'
  ), '[]'::jsonb),
  'constraints', coalesce((
    SELECT jsonb_agg(jsonb_build_object(
      'schema', ns.nspname, 'table', cls.relname, 'name', con.conname,
      'type', con.contype, 'definition', pg_get_constraintdef(con.oid, true)
    ) ORDER BY ns.nspname, cls.relname, con.conname)
      FROM pg_catalog.pg_constraint AS con
      JOIN pg_catalog.pg_class AS cls ON cls.oid = con.conrelid
      JOIN pg_catalog.pg_namespace AS ns ON ns.oid = cls.relnamespace
     WHERE ns.nspname NOT IN ('pg_catalog', 'information_schema')
       AND ns.nspname NOT LIKE 'pg_temp_%'
       AND ns.nspname NOT LIKE 'pg_toast%'
  ), '[]'::jsonb),
  'indexes', coalesce((
    SELECT jsonb_agg(jsonb_build_object(
      'schema', schemaname, 'table', tablename, 'name', indexname, 'definition', indexdef
    ) ORDER BY schemaname, tablename, indexname)
      FROM pg_catalog.pg_indexes
     WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
       AND schemaname NOT LIKE 'pg_temp_%'
       AND schemaname NOT LIKE 'pg_toast%'
  ), '[]'::jsonb),
  'tables', coalesce((
    SELECT jsonb_agg(jsonb_build_object(
      'schema', schema_name, 'name', table_name, 'rows', row_count, 'row_md5', row_md5
    ) ORDER BY schema_name, table_name)
      FROM _kf_table_fingerprints
  ), '[]'::jsonb),
  'sequences', coalesce((
    SELECT jsonb_agg(jsonb_build_object(
      'schema', schema_name, 'name', sequence_name,
      'last_value', last_value, 'is_called', is_called
    ) ORDER BY schema_name, sequence_name)
      FROM _kf_sequence_fingerprints
  ), '[]'::jsonb)
)::text;
