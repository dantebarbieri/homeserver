#!/usr/bin/env bash
# Derives homeserver's custom Prowlarr definitions from the upstream ones
# Prowlarr keeps refreshing, and replaces only those that changed. The daily
# update runs it; run it from docker/ after editing prowlarr/*.awk.
#   bash scripts/setup-prowlarr-definitions.sh [--dry-run]
# A definition whose upstream no longer has the expected structure is left
# as installed and the script fails. See docs/PROWLARR.md.
set -euo pipefail

dry_run=no
case "${1-}" in
    "") ;;
    --dry-run) dry_run=yes ;;
    *) echo "usage: $0 [--dry-run]" >&2; exit 2 ;;
esac

programs=$(dirname "$0")/../prowlarr
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
status=0
changed=no

# custom definition:upstream definition it is derived from
for pair in internetarchive-homeserver:internetarchive nyaasi-anime-homeserver:nyaasi; do
    name=${pair%%:*}
    upstream=${pair#*:}
    if ! docker exec prowlarr awk "$(cat "$programs/$name.awk")" \
            "/config/Definitions/$upstream.yml" > "$work/derived"; then
        echo "$name: could not derive it from $upstream.yml; kept the installed copy" >&2
        status=1
        continue
    fi
    docker exec prowlarr cat "/config/Definitions/Custom/$name.yml" \
        > "$work/installed" 2>/dev/null || : > "$work/installed"
    if cmp -s "$work/installed" "$work/derived"; then
        echo "$name: up to date"
        continue
    fi
    diff -u --label "installed $name.yml" --label "derived $name.yml" \
        "$work/installed" "$work/derived" || true
    if [ "$dry_run" = yes ]; then
        echo "$name: would update"
        continue
    fi
    docker exec -i prowlarr sh -c '
        set -eu
        custom=/config/Definitions/Custom
        mkdir -p "$custom"
        temporary=$(mktemp "$custom/.$1.XXXXXX")
        trap '\''rm -f "$temporary"'\'' EXIT
        cat > "$temporary"
        chmod 644 "$temporary"
        chown "$(stat -c %u:%g "/config/Definitions/$2.yml")" "$temporary"
        mv "$temporary" "$custom/$1.yml"
    ' sh "$name" "$upstream" < "$work/derived"
    echo "$name: updated"
    changed=yes
done

# Prowlarr caches parsed definitions until its definition update task runs.
if [ "$changed" = yes ] && ! docker exec prowlarr sh -c '
        key=$(sed -n "s:.*<ApiKey>\(.*\)</ApiKey>.*:\1:p" /config/config.xml)
        curl -fsS -o /dev/null -m 60 -H "X-Api-Key: $key" \
            -H "Content-Type: application/json" \
            -d "{\"name\":\"IndexerDefinitionUpdate\"}" \
            http://localhost:9696/api/v1/command
    '; then
    echo "Could not ask Prowlarr to reload definitions; it will on its next definition update or restart" >&2
    status=1
fi
exit "$status"
