#!/bin/sh

set -eu

config_path="${AUTHELIA_CONFIG_PATH:-/config/configuration.yml}"
marker="Model recipe applications (managed by homeserver repo)"

if [ "${RECIPE_AUTHELIA_INNER:-}" != "1" ]; then
    if ! docker inspect authelia >/dev/null 2>&1; then
        echo "authelia does not exist." >&2
        exit 1
    fi

    if [ "$(docker inspect authelia --format '{{.State.Running}}')" != "true" ]; then
        echo "authelia must be running before configuring its access rule." >&2
        exit 1
    fi

    wait_for_health() {
        waited=0
        while [ "$waited" -lt 60 ]; do
            state=$(docker inspect authelia --format '{{.State.Running}}:{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}')
            if [ "$state" = "true:healthy" ]; then
                return 0
            fi

            if [ "${state%%:*}" != "true" ]; then
                return 1
            fi

            sleep 2
            waited=$((waited + 2))
        done

        return 1
    }

    if docker exec authelia grep -Fq "$marker" "$config_path"; then
        docker exec authelia authelia config validate --config "$config_path" >/dev/null
        if wait_for_health; then
            echo "Authelia recipe application rule is already configured."
            exit 0
        fi

        echo "Authelia has the recipe rule but is not healthy; restarting it." >&2
        if docker restart authelia >/dev/null && wait_for_health; then
            echo "Authelia restarted with the existing recipe application rule."
            exit 0
        fi

        echo "Authelia did not become healthy after restart." >&2
        exit 1
    fi

    config_source=$(docker inspect authelia --format '{{range .Mounts}}{{if eq .Destination "/config"}}{{.Source}}{{end}}{{end}}')
    if [ -z "$config_source" ] || [ "${config_source#/}" = "$config_source" ]; then
        echo "Could not resolve Authelia's host config directory." >&2
        exit 1
    fi

    helper_image="alpine:3.22@sha256:14358309a308569c32bdc37e2e0e9694be33a9d99e68afb0f5ff33cc1f695dce"
    backup_name=".configuration.yml.recipe-apps-backup"

    config_helper() {
        docker run --rm \
            -v "$config_source:/config" \
            "$helper_image" sh -c "$1"
    }

    if ! config_helper "test ! -e /config/$backup_name"; then
        echo "Refusing to overwrite existing rollback file: $config_source/$backup_name" >&2
        exit 1
    fi

    config_helper "cp -p /config/configuration.yml /config/$backup_name"

    if ! docker exec -i --user root \
        -e RECIPE_AUTHELIA_INNER=1 \
        -e AUTHELIA_CONFIG_PATH="$config_path" \
        authelia sh -s < "$0"; then
        config_helper "rm -f /config/$backup_name"
        echo "Authelia rule update failed before replacing the live configuration." >&2
        exit 1
    fi

    if docker restart authelia >/dev/null && wait_for_health; then
        config_helper "rm -f /config/$backup_name"
        echo "Authelia restarted with the recipe application rule."
        exit 0
    fi

    echo "Authelia did not become healthy; restoring its previous configuration." >&2
    config_helper "cp -p /config/$backup_name /config/configuration.yml"

    if docker restart authelia >/dev/null && wait_for_health; then
        config_helper "rm -f /config/$backup_name"
        echo "Previous Authelia configuration restored successfully." >&2
    else
        echo "Authelia rollback failed; recovery copy remains at $config_source/$backup_name." >&2
    fi

    exit 1
fi

if grep -Fq "$marker" "$config_path"; then
    authelia config validate --config "$config_path" >/dev/null
    exit 0
fi

tmp_path=$(mktemp /config/.recipe-apps.XXXXXX)
trap 'rm -f "$tmp_path"' EXIT

awk -v marker="$marker" '
  { print }
  /^  rules:$/ {
    print "    ## " marker
    print "    - domain:"
    print "      - gpt-sol.recipe.danteb.com"
    print "      - gemini.recipe.danteb.com"
    print "      - claude.recipe.danteb.com"
    print "      - grok.recipe.danteb.com"
    print "      subject: '\''group:dev'\''"
    print "      policy: two_factor"
    print ""
    inserted = 1
  }
  END {
    if (!inserted) {
      exit 42
    }
  }
' "$config_path" > "$tmp_path"

uid=$(stat -c '%u' "$config_path")
gid=$(stat -c '%g' "$config_path")
mode=$(stat -c '%a' "$config_path")

authelia config validate --config "$tmp_path" >/dev/null
chown "$uid:$gid" "$tmp_path"
chmod "$mode" "$tmp_path"
mv "$tmp_path" "$config_path"
trap - EXIT
