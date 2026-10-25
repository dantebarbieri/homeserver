#!/usr/bin/env bash
set -euo pipefail

image="${1:-homepage-inventory:latest}"
docker_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
data="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/etc/searxng"}}{{.Source}}{{end}}{{end}}' searxng)"
[[ -n "$data" && -f "$docker_dir/.env" ]] || { echo "Missing production configuration" >&2; exit 1; }

docker run --rm --network none --read-only --user 0 \
  -v "$docker_dir:/configuration" -v "$data:/settings" \
  --entrypoint node "$image" /app/provision.cjs
password="$(docker run --rm --network none --read-only --user 0 \
  -v "$docker_dir:/configuration:ro" \
  --entrypoint node "$image" /app/provision.cjs --password)"
[[ "$password" =~ ^[A-Za-z0-9_-]{32,128}$ ]] || { echo "Invalid widget credential" >&2; exit 1; }

for source in synapse authelia snapotter; do
  case "$source" in
    synapse) container=synapse_postgres; user=synapse ;;
    authelia) container=authelia_postgres; user=authelia ;;
    snapotter) container=snapotter; user=snapotter ;;
  esac
  if ! {
    cat <<'SQL'
\set ON_ERROR_STOP on
BEGIN;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='homepage_widget')
     AND shobj_description((SELECT oid FROM pg_roles WHERE rolname='homepage_widget'),'pg_authid')
       IS DISTINCT FROM 'homeserver Homepage aggregates' THEN
    RAISE EXCEPTION 'Unrelated database role already exists';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='homepage_widget') THEN
    CREATE ROLE homepage_widget LOGIN;
    COMMENT ON ROLE homepage_widget IS 'homeserver Homepage aggregates';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname='homepage_widget'
    AND obj_description(oid,'pg_namespace') IS DISTINCT FROM 'homeserver Homepage aggregates') THEN
    RAISE EXCEPTION 'Unrelated database schema already exists';
  END IF;
END $$;
SQL
    printf "ALTER ROLE homepage_widget LOGIN PASSWORD '%s' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION CONNECTION LIMIT 8;\n" "$password"
    cat <<'SQL'
ALTER ROLE homepage_widget SET default_transaction_read_only = on;
ALTER ROLE homepage_widget SET statement_timeout = '2s';
ALTER ROLE homepage_widget SET search_path = pg_catalog;
CREATE SCHEMA IF NOT EXISTS homepage_widget;
COMMENT ON SCHEMA homepage_widget IS 'homeserver Homepage aggregates';
REVOKE ALL ON SCHEMA homepage_widget FROM PUBLIC;
SQL
    cat "$docker_dir/dockerfiles/homepage-inventory/views/$source.sql"
    cat <<'SQL'
REVOKE ALL ON homepage_widget.stats FROM PUBLIC;
GRANT USAGE ON SCHEMA homepage_widget TO homepage_widget;
GRANT SELECT ON homepage_widget.stats TO homepage_widget;
COMMIT;
SQL
  } | docker exec -i "$container" psql -U "$user" -d "$source" -X -qAt >/dev/null 2>&1; then
    echo "Aggregate-only access setup failed for $source; no raw database errors printed" >&2
    exit 1
  fi
  echo "$source aggregate-only read access configured"
done
unset password
