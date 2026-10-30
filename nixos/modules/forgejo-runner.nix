# Host-mode Forgejo Actions runner for WorldForge.
{ config, lib, pkgs, ... }:

{
  # Forgejo Actions host-mode runner (for WorldForge Snakemake pipeline).
  # Runs alongside the dockerized runner in docker/compose.git.yml — that
  # one handles `ubuntu-*:docker://catthehacker/...` jobs, this one handles
  # the `worldforge-host` label for jobs that need `nix develop`.
  #
  # Unit: forgejo-runner-worldforge.service. State and $HOME:
  # /var/lib/forgejo-runner/worldforge. The runner (named
  # `homeserver-worldforge` in Forgejo; the name lives only in Forgejo now)
  # connects with a UUID (its public identity, like a username) and a token
  # (its password). The token file holds only the raw token — no `TOKEN=`
  # prefix — and is passed in via systemd LoadCredential.
  #
  # Bootstrap (fresh install only — the existing runner is migrated by
  # forgejo-runner-worldforge-migrate below):
  #   1. In Forgejo: Site Administration → Actions → Runners → Create new
  #      runner (name: homeserver-worldforge). Copy the UUID and token.
  #   2. Put the UUID in `server.connections.default.uuid` below and write
  #      the token:
  #        sudo install -m 0600 -o root -g root /dev/stdin \
  #          /var/lib/forgejo-runner-worldforge.token <<<'<token>'
  #   3. nixos-rebuild switch
  services.forgejo-runner.instances.worldforge = {
    enable = true;
    settings = {
      runner.labels = [ "worldforge-host:host" ];
      server.connections.default = {
        url = "https://git.danteb.com";
        uuid = "41876b63-7fd6-4566-9013-97d555380c4e";
      };
    };
    secrets.server.connections.default.token_url = "/var/lib/forgejo-runner-worldforge.token";
    hostPackages = with pkgs; [
      bash
      coreutils
      curl
      wget
      gnused
      gawk
      git
      git-lfs
      nodejs
      openssh
      rsync
      gnutar
      gzip
      jq
      nix
      just
      uv
      cacert
    ];
  };

  # The nixpkgs module sets DynamicUser=true on the runner service. systemd
  # then mounts /var/lib/private as a noexec tmpfs and bind-mounts the real
  # StateDirectory through it. act-runner resolves canonical paths to
  # /var/lib/private/forgejo-runner/... and dlopen() of any manylinux .so on
  # that mount fails with "failed to map segment from shared object" because
  # mmap(PROT_EXEC) returns EACCES on a noexec mount. The module now adds
  # ExecPaths= for host runners, but we keep the proven fix: disable
  # DynamicUser and use a real system user so StateDirectory lives directly
  # on the root filesystem (rw, exec) with no noexec mount in the chain.
  users.groups.forgejo-runner = { };
  users.users.forgejo-runner = {
    isSystemUser = true;
    group = "forgejo-runner";
    home = "/var/lib/forgejo-runner";
    createHome = false;  # systemd's StateDirectory handles creation
  };
  systemd.services.forgejo-runner-worldforge.serviceConfig = {
    DynamicUser = lib.mkForce false;
    User = "forgejo-runner";
    Group = "forgejo-runner";
  };

  # One-time migration from the retired services.gitea-actions-runner
  # instance (gitea-runner-worldforge.service, /var/lib/gitea-runner/worldforge).
  # Runs as root before the runner while the old `.runner` registration file
  # exists, and is skipped once it is gone:
  #   - replaces the `TOKEN=<registration token>` in the token file with the
  #     runner token from `.runner`, so the runner keeps its Forgejo identity
  #     (no re-registration);
  #   - moves the old state (act/uv/nix caches) to the new StateDirectory
  #     (systemd re-owns it for the forgejo-runner user on start);
  #   - deletes `.runner`, `.labels` and `.token-hash`. forgejo-runner refuses
  #     to start when a `.runner` file coexists with server.connections.
  # Safe to delete once /var/lib/gitea-runner is gone on the server.
  systemd.services.forgejo-runner-worldforge-migrate =
    let
      instance = config.services.forgejo-runner.instances.worldforge;
      uuid = instance.settings.server.connections.default.uuid;
      tokenFile = instance.secrets.server.connections.default.token_url;
      oldDir = "/var/lib/gitea-runner/worldforge";
      newDir = "/var/lib/forgejo-runner/worldforge";
    in
    {
      description = "Migrate gitea-actions-runner state to forgejo-runner-worldforge";
      requiredBy = [ "forgejo-runner-worldforge.service" ];
      before = [ "forgejo-runner-worldforge.service" ];
      unitConfig.ConditionPathExists = "${oldDir}/.runner";
      serviceConfig.Type = "oneshot";
      path = with pkgs; [ coreutils jq ];
      script = ''
        registered=$(jq -er .uuid ${oldDir}/.runner)
        if [ "$registered" != ${lib.escapeShellArg uuid} ]; then
          echo "${oldDir}/.runner has UUID $registered, expected ${uuid}" >&2
          exit 1
        fi

        umask 077
        tmp=$(mktemp ${tokenFile}.XXXXXX)
        trap 'rm -f "$tmp"' EXIT
        jq -er .token ${oldDir}/.runner > "$tmp"
        mv "$tmp" ${tokenFile}

        mkdir -p ${dirOf newDir}
        mv -T ${oldDir} ${newDir}
        rm -f ${newDir}/.runner ${newDir}/.labels ${newDir}/.token-hash
        rmdir --ignore-fail-on-non-empty ${dirOf oldDir}
      '';
    };
}
