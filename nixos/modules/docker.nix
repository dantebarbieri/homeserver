# Docker daemon and the daily Docker Compose updater.
{ config, lib, pkgs, ... }:

let
  inherit (import ../lib/shared.nix { inherit config pkgs; })
    mirklurkDeploymentCondition;
in
{
  # Docker
  virtualisation.docker = {
    enable = true;
    daemon.settings = {
      features = { cdi = true; };
      fixed-cidr-v6 = "fd00::/80";
      ip6tables = true;  # IPv6 NAT — masquerade ULA to host's public GUA, like IPv4
      ipv6 = true;
      live-restore = true;
      userland-proxy = true;
    };
  };

  # live-restore can retain file bind mounts pointing at the replaced daemon socket.
  systemd.services.docker-socket-consumers = {
    description = "Reconnect running Docker socket consumers after daemon startup";
    wantedBy = [ "docker.service" ];
    after = [ "docker.service" ];
    requires = [ "docker.service" ];
    partOf = [ "docker.service" ];
    unitConfig.OnFailure = "ntfy-failure@%n.service";
    path = with pkgs; [ docker util-linux coreutils ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      WorkingDirectory = "/srv/homeserver/docker";
      TimeoutStartSec = "30min";
    };
    script = ''
      ${pkgs.bash}/bin/bash ${../../docker/scripts/reconcile-docker-socket-consumers.sh}
    '';
  };

  # Docker Compose auto-update (daily at 4 AM)

  # Auto-generate deploy key if it doesn't exist
  system.activationScripts.docker-compose-deploy-key = lib.stringAfter [ "users" ] ''
    KEY="/root/.ssh/docker-compose-deploy"
    if [ ! -f "$KEY" ]; then
      mkdir -p /root/.ssh
      chmod 700 /root/.ssh
      ${pkgs.openssh}/bin/ssh-keygen -t ed25519 -f "$KEY" -N "" -C "docker-compose-deploy@${config.networking.hostName}"
      chmod 600 "$KEY"
      chmod 644 "$KEY.pub"
      echo "Deploy key generated. Add the following public key to GitHub as a read-only deploy key:"
      cat "$KEY.pub"
    fi
  '';

  systemd.services.docker-compose-update = {
    description = "Pull and update Docker Compose containers";
    after = [ "docker.service" "network-online.target" ];
    requires = [ "docker.service" ];
    wants = [ "network-online.target" ];
    unitConfig.OnFailure = "ntfy-failure@%n.service";
    unitConfig.ConditionPathExists = mirklurkDeploymentCondition;
    path = [ pkgs.docker pkgs.git pkgs.openssh pkgs.bash pkgs.coreutils pkgs.diffutils pkgs.findutils pkgs.util-linux ];
    environment = {
      GIT_SSH_COMMAND = "ssh -i /root/.ssh/docker-compose-deploy -o StrictHostKeyChecking=accept-new";
    };
    serviceConfig = {
      Type = "oneshot";
      WorkingDirectory = "/srv/homeserver";
    };
    # Most images here intentionally float on :latest so security and feature
    # updates land without manual intervention. The tradeoff is that a bad
    # upstream release is invisible to git — no tracked file changed, so
    # `git revert` cannot undo it. The pre-update snapshot below closes that
    # gap: it records the exact image digest every container was running
    # *before* the pull, so a rollback is a lookup instead of archaeology.
    #
    # To roll a service back:
    #   grep <service> /srv/docker/image-snapshots/<date>.tsv
    #   # set `image: <repo>@<sha256:...>` in the compose file, then `up -d`
    # Note the local copy of the old image is usually gone by then — `pull`
    # moves the tag and `image prune -f` reaps the now-dangling layer — so the
    # digest is re-fetched from the registry. Containers listed as
    # <locally-built> need no entry here: they rebuild from the repo, which
    # git already versions.
    #
    # The MirkLurk wiki frontend sits in Compose profile `mirklurk-release`, so
    # the pull/build/up below never starts or recreates it; only
    # mirklurk-release.py (and mirklurk-auto-update) moves its image.
    script = ''
      exec 9>/run/lock/homeserver-compose.lock
      flock 9

      SNAPSHOT_DIR=/srv/docker/image-snapshots
      mkdir -p "$SNAPSHOT_DIR"
      SNAPSHOT="$SNAPSHOT_DIR/$(date +%Y-%m-%d-%H%M%S).tsv"

      {
        printf 'container\timage_ref\trepo_digest\n'
        for cid in $(docker ps -q); do
          name=$(docker inspect --format '{{.Name}}' "$cid" | tr -d /)
          # .Config.Image is the mutable tag the container was started from;
          # it is only a label. Resolve the digest from .Image — the immutable
          # image ID actually backing the container — because the tag may have
          # already moved (a pull that landed but whose recreate failed). That
          # is exactly the state a rollback is needed in, so reading the tag
          # here would record the wrong version and defeat the whole snapshot.
          img_ref=$(docker inspect --format '{{.Config.Image}}' "$cid")
          img_id=$(docker inspect --format '{{.Image}}' "$cid")
          digest=$(docker image inspect --format \
            '{{if .RepoDigests}}{{index .RepoDigests 0}}{{else}}<locally-built>{{end}}' \
            "$img_id" 2>/dev/null || echo '<unknown>')
          printf '%s\t%s\t%s\n' "$name" "$img_ref" "$digest"
        done
      } > "$SNAPSHOT"

      echo "Pre-update image snapshot written to $SNAPSHOT"

      # Keep two weeks of snapshots — enough to cover a vacation.
      find "$SNAPSHOT_DIR" -name '*.tsv' -type f -mtime +14 -delete

      # Finish Git maintenance before chown traverses transient lock files.
      before=$(git -c safe.directory=/srv/homeserver rev-parse HEAD)
      git -c safe.directory=/srv/homeserver \
          -c maintenance.autoDetach=false -c gc.autoDetach=false pull --ff-only
      chown -R danteb:docker .git
      # The pull runs as root, so everything it creates is root-owned and a
      # later manual `git pull` as danteb fails with "Permission denied".
      # Hand back only what this pull changed, plus the directories holding
      # it; the rest of the tree (e.g. files containers write) is untouched.
      git -c safe.directory=/srv/homeserver diff --name-only -z "$before" HEAD |
        while IFS= read -r -d "" path; do
          while [ "$path" != . ]; do
            if [ -e "$path" ] || [ -L "$path" ]; then
              chown -h danteb:docker "$path"
            fi
            path=$(dirname "$path")
          done
        done
      cd docker
      services=$(docker compose config --services)

      pulled=no
      for attempt in 1 2 3; do
        if docker compose --parallel 4 pull --ignore-buildable; then
          pulled=yes
          break
        fi
        if [ "$attempt" -lt 3 ]; then
          delay=$((attempt * 60))
          echo "Image pull attempt $attempt failed; retrying in $delay seconds." >&2
          sleep "$delay"
        fi
      done

      # Pulled images are isolated like built ones below. A registry throttling
      # one image (ghcr.io has answered the multi-GB immich CUDA layers with
      # `toomanyrequests` on every parallel attempt) must not hold back every
      # other update. Each service is retried alone, without parallel load; one
      # that still fails keeps its current image and container, and the unit
      # fails at the end so ntfy-failure@ reports it.
      failed_pulls=()
      if [ "$pulled" = no ]; then
        echo "Image pull failed after 3 attempts; pulling services one at a time to isolate it." >&2
        for svc in $services; do
          docker compose pull --ignore-buildable "$svc" || failed_pulls+=("$svc")
        done
      fi

      # Locally built images are isolated from each other and from the rest of
      # the stack. If one fails to build, every other service still deploys,
      # the broken service keeps running its previous container, and the unit
      # still fails at the end so ntfy-failure@ reports it. A failed combined
      # build is retried per service to find the culprit.
      failed_builds=()
      if ! docker compose build --pull; then
        echo "Image build failed; rebuilding services one at a time to isolate it." >&2
        for svc in $services; do
          docker compose build --pull "$svc" || failed_builds+=("$svc")
        done
      fi

      held=("''${failed_pulls[@]}" "''${failed_builds[@]}")
      tdarr_guard_ready=no
      tdarr_guard_status=0
      bash scripts/tdarr-update-guard.sh prepare || tdarr_guard_status=$?
      if [ "$tdarr_guard_status" -eq 0 ]; then
        tdarr_guard_ready=yes
        trap 'bash scripts/tdarr-update-guard.sh release' EXIT
      else
        held+=(tdarr)
        if [ "$tdarr_guard_status" -ne 75 ]; then
          echo "Tdarr update guard failed; keeping its running container." >&2
          failed_builds+=(tdarr)
        fi
      fi
      if [ "''${#held[@]}" -eq 0 ]; then
        docker compose up -d --remove-orphans
      else
        echo "Holding back ''${held[*]}; deploying everything else." >&2
        deploy=()
        for svc in $services; do
          case " ''${held[*]} " in
            *" $svc "*) ;;
            *) deploy+=("$svc") ;;
          esac
        done
        if [ "''${#deploy[@]}" -ne 0 ]; then
          docker compose up -d --remove-orphans "''${deploy[@]}"
        fi
      fi
      if [ "$tdarr_guard_ready" = yes ]; then
        bash scripts/tdarr-update-guard.sh release
        trap - EXIT
      fi
      # Re-derive the custom Prowlarr definitions from the upstream ones Prowlarr
      # refreshes itself (docker/docs/PROWLARR.md). An unexpected upstream keeps
      # the installed copy and fails the unit for review.
      prowlarr_definitions=ok
      bash scripts/setup-prowlarr-definitions.sh || prowlarr_definitions=failed
      docker compose up -d --force-recreate homepage
      docker image prune -f
      docker network prune -f

      if [ "''${#failed_pulls[@]}" -ne 0 ]; then
        echo "Update finished, but these services kept their previous image because it failed to pull: ''${failed_pulls[*]}" >&2
      fi
      if [ "''${#failed_builds[@]}" -ne 0 ]; then
        echo "Update finished, but these services kept their previous image because it failed to build: ''${failed_builds[*]}" >&2
      fi
      if [ "$prowlarr_definitions" = failed ]; then
        echo "Update finished, but Prowlarr's custom definitions need review (docker/docs/PROWLARR.md)." >&2
      fi
      if [ "''${#failed_pulls[@]}" -ne 0 ] || [ "''${#failed_builds[@]}" -ne 0 ] ||
        [ "$prowlarr_definitions" = failed ]; then
        exit 1
      fi
    '';
  };

  systemd.timers.docker-compose-update = {
    wantedBy = [ "timers.target" ];
    unitConfig.ConditionPathExists = mirklurkDeploymentCondition;
    timerConfig = {
      OnCalendar = "*-*-* 04:00:00";
      Persistent = true;
      RandomizedDelaySec = "5m";
    };
  };
}
