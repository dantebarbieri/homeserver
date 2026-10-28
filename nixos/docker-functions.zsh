# Docker Compose convenience functions
# Sourced by NixOS interactiveShellInit (programs.zsh) — see configuration.nix
# All functions cd to the compose directory in a subshell so the caller's cwd is unaffected.

# Show image info for a service (repo, tag, digest, created date)
# Usage: dci bazarr
dci() (
  cd /srv/docker/compose || return 1

  if [[ -z "$1" ]]; then
    echo "Usage: dci <service>" >&2
    return 1
  fi

  docker compose images "$1"
  echo ""
  docker inspect --format '{{.Config.Image}}
Created:  {{.Created}}
ID:       {{.Image}}' \
    "$(docker compose ps -q "$1")"
)

# Exec a command in a running service container
# Usage: dce bazarr ls /config
#        dce bazarr cat /config/config.xml
#        dce postgres psql -U myuser mydb
dce() (
  cd /srv/docker/compose || return 1

  if [[ -z "$1" ]] || [[ -z "$2" ]]; then
    echo "Usage: dce <service> <command ...>" >&2
    return 1
  fi

  local svc="$1"
  shift
  docker compose exec "$svc" "$@"
)

# Drop into an interactive shell inside a service container
# Tries bash, then sh as fallback (covers alpine/minimal images)
# Usage: dcs bazarr
dcs() (
  cd /srv/docker/compose || return 1

  if [[ -z "$1" ]]; then
    echo "Usage: dcs <service>" >&2
    return 1
  fi

  # Try shells in preference order; exec replaces the subshell on success
  for shell in /bin/bash /bin/sh; do
    docker compose exec "$1" "$shell" 2>/dev/null && return 0
  done

  echo "No usable shell found in $1" >&2
  return 1
)

# View logs — follows with timestamps, optional --since filter
# Usage: dcl bazarr whisperasr          (all logs, following)
#        dcl -s 30m bazarr whisperasr   (last 30 min, following)
#        dcl -s 2h bazarr               (last 2 hours, following)
dcl() (
  cd /srv/docker/compose || return 1

  local since=""
  if [[ "$1" == "-s" ]]; then
    since="$2"
    shift 2
  fi

  if [[ -n "$since" ]]; then
    docker compose logs -f -t --since "$since" "$@"
  else
    docker compose logs -f -t "$@"
  fi
)

# Restart services — recreates containers to pick up any changes
# Usage: dcr bazarr whisperasr
dcr() (
  cd /srv/docker/compose || return 1

  local guarded=no result=0
  if (( $# == 0 )) || (( ${@[(Ie)tdarr]} )); then
    bash scripts/tdarr-update-guard.sh prepare || return $?
    trap 'bash scripts/tdarr-update-guard.sh release' EXIT
    guarded=yes
  fi
  docker compose up -d --force-recreate "$@" || result=$?
  if [[ "$guarded" == yes ]]; then
    bash scripts/tdarr-update-guard.sh release || result=$?
    trap - EXIT
  fi
  return $result
)

# Build local images without letting one broken Dockerfile hold back the rest
# of the stack. If the combined build fails, rebuild one service at a time and
# leave the ones that still fail in $failed_builds for the caller.
_dc_build() {
  failed_builds=()
  docker compose build --pull && return 0

  print -u2 "Image build failed; rebuilding services one at a time to isolate it."
  local services svc
  services=$(docker compose config --services) || return 1
  for svc in ${(f)services}; do
    docker compose build --pull "$svc" || failed_builds+=("$svc")
  done
}

# `docker compose up -d` for every service except those in $failed_builds,
# which keep running their previous container.
_dc_up() {
  local services guard_status=0 result=0
  local -a deploy held
  held=("${failed_builds[@]}")
  bash scripts/tdarr-update-guard.sh prepare || guard_status=$?
  if (( guard_status )); then
    held+=(tdarr)
    if (( guard_status != 75 )); then
      print -u2 "Tdarr update guard failed; its running container will be preserved."
      failed_builds+=(tdarr)
    fi
  else
    trap 'bash scripts/tdarr-update-guard.sh release' EXIT
  fi
  services=$(docker compose config --services) || return 1
  deploy=(${(f)services})
  deploy=(${deploy:|held})
  if (( ${#held} )); then
    print -u2 "Holding back: ${held[*]}; deploying everything else."
  fi
  if (( ${#deploy} )); then
    docker compose up -d "$@" "${deploy[@]}" || result=$?
  fi
  if (( guard_status == 0 )); then
    bash scripts/tdarr-update-guard.sh release || result=$?
    trap - EXIT
  fi
  return $result
}

_dc_report_failed_builds() {
  (( ${#failed_builds} == 0 )) && return 0
  print -u2 "These services kept their previous image because it failed to build: ${failed_builds[*]}"
  return 1
}

# Quick update — pull changes, rebuild only what changed, minimal downtime
dcu() (
  cd /srv/docker/compose || return 1

  git pull --recurse-submodules || return 1

  docker compose pull --ignore-buildable || return 1
  _dc_build || return 1
  _dc_up --remove-orphans || return 1

  # Light cleanup — only dangling images and unused networks
  docker image prune -f
  docker network prune -f

  _dc_report_failed_builds
)

# Full update — pull, rebuild, then tear down and restart everything
dcupdate() (
  cd /srv/docker/compose || return 1

  git pull --recurse-submodules || return 1
  git push || return 1

  # Fetch and build everything before tearing anything down, so a registry or
  # build failure leaves the running stack untouched.
  docker compose pull --ignore-buildable || return 1
  _dc_build || return 1

  local tdarr_running
  tdarr_running=$(docker ps --filter 'name=^/tdarr$' --format '{{.Names}}') || return 1
  if (( ${#failed_builds} )) || [[ -n "$tdarr_running" ]]; then
    # A teardown would also stop the services whose image failed to build, so
    # fall back to an in-place update that leaves them on their old image.
    print -u2 "Skipping the full teardown to preserve held images or running Tdarr jobs."
    _dc_up --remove-orphans || return 1
  else
    docker compose down --remove-orphans || return 1
    docker compose up -d || return 1
  fi

  # Heavy cleanup — unused images, networks, and build cache. Keep retained
  # MirkLurk wiki releases: they are rollback/forensic images, not cache.
  docker image prune -af --filter "label!=org.opencontainers.image.source=https://github.com/dantebarbieri/mirklurk-wiki"
  docker network prune -f
  docker builder prune -af

  _dc_report_failed_builds
)
