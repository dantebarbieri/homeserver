#!/bin/sh

ntfy_curl() {
  local token token_file http_status status
  token_file="${NTFY_TOKEN_FILE:-/srv/docker/data/ntfy/secrets/publisher-token}"
  if ! token=$(cat "$token_file"); then
    echo "Cannot read ntfy publisher token" >&2
    return 1
  fi
  case "$token" in
    tk_?*) ;;
    *) echo "Invalid ntfy publisher token" >&2; return 1 ;;
  esac
  case "$token" in
    *[!a-zA-Z0-9_]*) echo "Invalid ntfy publisher token" >&2; return 1 ;;
  esac
  if http_status=$(printf 'header = "Authorization: Bearer %s"\n' "$token" |
    curl --config - --output /dev/null --write-out '%{http_code}' "$@"); then
    case "$http_status" in
      2[0-9][0-9]) return 0 ;;
      *) echo "ntfy returned a non-success HTTP status" >&2; return 1 ;;
    esac
  else
    status=$?
    return "$status"
  fi
}
