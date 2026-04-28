# Edit this configuration file to define what should be installed on
# your system. Help is available in the configuration.nix(5) man page, on
# https://search.nixos.org/options and in the NixOS manual (`nixos-help`).

{ config, lib, pkgs, ... }:

let
  # ─── ntfy push-notification infrastructure ───────────────────────────────
  # Your self-hosted ntfy instance (Docker container "ntfy").
  # Subscribe on your phone — see NTFY-PHONE-SETUP.md
  ntfyUrl   = "https://ntfy.danteb.com";
  ntfyTopic = "homeserver-alerts";

  # General-purpose CLI helper (available in $PATH as `ntfy-notify`)
  #   Usage: ntfy-notify "Title" "Message body" [priority] [tags]
  ntfyNotify = pkgs.writeShellScriptBin "ntfy-notify" ''
    TITLE="''${1:-Homeserver Alert}"
    MESSAGE="''${2:-No details provided}"
    PRIORITY="''${3:-default}"
    TAGS="''${4:-}"
    ${pkgs.curl}/bin/curl -s \
      -H "Title: $TITLE" \
      -H "Priority: $PRIORITY" \
      -H "Tags: $TAGS" \
      -d "$MESSAGE" \
      "${ntfyUrl}/${ntfyTopic}"
  '';

  # smartd alert handler (called via -M exec; receives SMARTD_* env vars)
  smartdAlert = pkgs.writeShellScript "smartd-ntfy" ''
    ${pkgs.curl}/bin/curl -s \
      -H "Title: SMART: $SMARTD_FAILTYPE on ${config.networking.hostName}" \
      -H "Priority: high" \
      -H "Tags: warning,computer" \
      -d "Device: $SMARTD_DEVICE — Type: $SMARTD_DEVICETYPE — $SMARTD_MESSAGE" \
      "${ntfyUrl}/${ntfyTopic}"
  '';

  # mdadm event handler (PROGRAM directive; args: event device [component])
  mdadmAlert = pkgs.writeShellScript "mdadm-ntfy" ''
    EVENT="$1"
    MD_DEVICE="$2"
    COMPONENT="''${3:-none}"

    case "$EVENT" in
      Fail*|Degrade*|SparesMissing)
        PRIORITY="urgent"
        TAGS="rotating_light,computer"
        ;;
      Rebuild*|RebuildFinished)
        # Scheduled mdadm-scrub holds /run/mdadm-scrub for its full duration
        # (RuntimeDirectory=), so check/repair events are reliably suppressed.
        if [ -d /run/mdadm-scrub ]; then
          exit 0
        fi
        # Backup filter for manual `echo check/repair` outside the service.
        MD_NAME="''${MD_DEVICE##*/}"
        SYNC_ACTION=$(cat "/sys/block/$MD_NAME/md/sync_action" 2>/dev/null || echo "unknown")
        if [ "$SYNC_ACTION" = "check" ] || [ "$SYNC_ACTION" = "repair" ]; then
          exit 0
        fi
        PRIORITY="high"
        TAGS="construction,computer"
        ;;
      *)
        PRIORITY="default"
        TAGS="information_source,computer"
        ;;
    esac

    ${pkgs.curl}/bin/curl -s \
      -H "Title: RAID $EVENT on ${config.networking.hostName}" \
      -H "Priority: $PRIORITY" \
      -H "Tags: $TAGS" \
      -d "Array: $MD_DEVICE | Component: $COMPONENT" \
      "${ntfyUrl}/${ntfyTopic}"
  '';

in
{
  imports = [ ./hardware-configuration.nix ];

  # Boot
  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;
  boot.loader.systemd-boot.configurationLimit = 5;

  # Use default kernel (follows NixOS channel).
  # If NVIDIA breaks on a kernel update, temporarily pin to the previous LTS:
  #   boot.kernelPackages = pkgs.linuxPackages_6_12;
  # Check NVIDIA compatibility at: https://www.nvidia.com/en-us/drivers/unix/

  # Kernel hardening (CIS / KSPP recommendations)
  boot.kernel.sysctl = {
    "kernel.sysrq" = 0;                     # Disable Magic SysRq key (no physical keyboard on headless server)
    "kernel.kptr_restrict" = 2;              # Hide kernel pointers from all users (hardens KASLR)
    "kernel.dmesg_restrict" = 1;             # Restrict dmesg to CAP_SYSLOG
    "kernel.yama.ptrace_scope" = 2;          # Restrict ptrace to CAP_SYS_PTRACE
    "net.core.bpf_jit_harden" = 2;          # Harden BPF JIT compiler
    "kernel.unprivileged_bpf_disabled" = 1;  # Disable unprivileged BPF
  };

  # Unfree + NVIDIA EULA
  nixpkgs.config.allowUnfree = true;
  nixpkgs.config.nvidia.acceptLicense = true;

  # Hostname
  networking.hostName = "homeserver";

  # We will define addresses in systemd-networkd (no global DHCP)
  networking.useDHCP = false;

  # Disable NetworkManager and its dispatcher hacks
  networking.networkmanager.enable = false;

  # Switch to systemd-networkd + resolved
  networking.useNetworkd = true;
  services.resolved.enable = true;
  services.resolved.settings.Resolve.DNSStubListener = "no";  # free port 53 for AdGuard Home

  # Bond: enp66s0f0 + enp66s0f1 → bond0 (active-backup)
  # The ASUS GT-BE98 Pro does NOT support LACP on its 2.5G LAN ports,
  # so we use active-backup (mode 1) for fault tolerance. enp66s0f1 is
  # the primary (known-good) link; enp66s0f0 is the failover.
  networking.bonds.bond0 = {
    interfaces = [ "enp66s0f0" "enp66s0f1" ];
    driverOptions = {
      mode = "active-backup";
      primary = "enp66s0f1";
      miimon = "100";
    };
  };

  networking.interfaces.bond0 = {
    useDHCP = false;
    macAddress = "9c:6b:00:45:2b:c2";  # Match enp66s0f1 so IPv6 EUI-64 stays stable
    ipv4.addresses = [
      { address = "192.168.50.100"; prefixLength = 24; }
    ];
    tempAddress = "disabled";  # Use stable EUI-64 IPv6 (no rotating privacy addresses)
  };

  # default gateway + DNS
  networking.defaultGateway = {
    address = "192.168.50.1";
    interface = "bond0";
  };
  networking.nameservers   = [ "127.0.0.1" "1.1.1.1" "8.8.8.8" ];  # AdGuard Home (local), with public fallbacks

  # Firewall — NixOS enables the firewall by default and blocks all inbound
  # except SSH. Open ports for services exposed via Docker port mappings and
  # host-networked containers (coturn). Port 28 (SSH) is auto-opened by
  # services.openssh; Docker's userland-proxy handles container→host mapping
  # but the kernel firewall still drops inbound packets before they reach it.
  networking.firewall = {
    allowedTCPPorts = [
      53      # DNS → AdGuard Home
      80      # HTTP → Nginx Proxy Manager
      443     # HTTPS → Nginx Proxy Manager
      22      # endlessh SSH honeypot
      2222    # Forgejo Git SSH
      32400   # Plex direct access
      8324    # Plex companion
      32469   # Plex DLNA
      3478    # Coturn TURN (host-networked)
      5349    # Coturn TURNS TLS (host-networked)
      7881    # LiveKit ICE/TCP fallback
      8888    # Satisfactory TCP
    ];
    allowedUDPPorts = [
      53      # DNS → AdGuard Home
      1900    # Plex SSDP/DLNA discovery
      3478    # Coturn TURN (host-networked)
      5205    # Hytale
      7778    # Satisfactory
      32410 32412 32413 32414  # Plex GDM discovery
      51820   # WireGuard VPN (wg-easy)
    ];
    allowedTCPPortRanges = [
      { from = 36676; to = 36677; }  # Minecraft servers
    ];
    allowedUDPPortRanges = [
      { from = 7882;  to = 7913;  }  # LiveKit WebRTC UDP mux
      { from = 36676; to = 36677; }  # Minecraft servers
      { from = 49152; to = 49999; }  # Coturn relay port range
    ];
  };

  # Make boot wait for bond0 to be online before starting network services
  systemd.network.wait-online = {
    enable = true;
    extraArgs = [ "--interface=bond0" ];
  };

  # Time / locale / console
  time.timeZone = "America/Chicago";
  i18n.defaultLocale = "en_US.UTF-8";
  console = {
    font = "Lat2-Terminus16";
    keyMap = "us";
  };

  # LVM + RAID
  services.lvm.enable = true;
  boot.initrd.services.lvm.enable = true;

  boot.swraid.enable = true;
  boot.swraid.mdadmConf = builtins.concatStringsSep "\n" [
    "ARRAY /dev/md0 metadata=1.2 spares=1 name=homeserver:0 UUID=a13e736d:e8805790:1e2d65a6:c4f6b3d2"
    "PROGRAM ${mdadmAlert}"
  ];

  # Flakes
  nix.settings.experimental-features = [ "nix-command" "flakes" ];

  # User
  users = {
    defaultUserShell = pkgs.zsh;
    users.danteb = {
      initialPassword = "changeme123!";
      isNormalUser = true;
      extraGroups = [ "docker" "wheel" ];
      openssh.authorizedKeys.keys = [
        "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBH5PB799wDZ5lqHUn0HDnEudAaUk9ihMYk2/vE7O8ZZ+ykEEycFa1BFxVP4EnIe9J9jyD9GVYs2vgngMNFEmeAE=" # Dante's iPhone (Termius)
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGSElIxTg8VbjbB3O2WVMvZJYfP4GBzg5uzJSaKKu12f dantevbarbieri@gmail.com" # Dante's MacBook Pro
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPdijU1XLbXrh1yMq7RtrLrIaTtWibnMAFcxTfFm1Y+g dantevbarbieri@gmail.com"
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEd1FMM7tj/1D8AIKc0ESGKLYx4Q6vEbDx8HxQAVD/IB REDMOND\dbarbieri@DESKTOP-PFQPS83" # Dante Work PC
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINH0/WsgjiI/Q3tlBsWudx9L3cApJOFxYl1lQP7Dd6/f Dante@DESKTOP-DD5K2PO" # Dante's old Windows PC (DESKTOP-DD5K2PO)
      ];
      packages = with pkgs; [
        tree
      ];
    };
  };

  programs.git = {
    enable = true;
    config = {
      commit.gpgsign = true;
      gpg.format = "ssh";
      init.defaultBranch = "main";
      push.autoSetupRemote = true;
      user = {
        email = "dantevbarbieri@gmail.com";
        name  = "dantebarbieri";
        signingkey = "~/.ssh/id_ed25519.pub";
      };
    };
  };

  programs.neovim = {
    enable = true;
    defaultEditor = true;
    vimAlias = true;
    viAlias = true;
  };
  programs.zsh = {
    enable = true;
    enableCompletion = false;  # zimfw handles completion via its own module
    interactiveShellInit = ''
      # ── zimfw: auto-download plugin manager if missing ──
      ZIM_HOME="$HOME/.zim"
      if [[ ! -e "$ZIM_HOME/zimfw.zsh" ]]; then
        ${pkgs.curl}/bin/curl -fsSL --create-dirs -o "$ZIM_HOME/zimfw.zsh" \
          https://github.com/zimfw/zimfw/releases/latest/download/zimfw.zsh
      fi

      # ── any-nix-shell: stay in ZSH inside nix-shell / nix develop ──
      ${pkgs.any-nix-shell}/bin/any-nix-shell zsh --info-right | source /dev/stdin

      # ── Nix convenience functions (nsp, nss, nwp) ──
      source ${./nix-functions.zsh}

      # ── Docker Compose convenience functions ──
      source ${./docker-functions.zsh}

      # ── fastfetch: system info on initial shell only (not nix shell subshells) ──
      [[ $SHLVL -eq 1 ]] && fastfetch

      # ── khal: show today's calendar events on login ──
      if [[ $SHLVL -eq 1 ]] && command -v khal &>/dev/null; then
        local _khal_out
        _khal_out="$(khal list --day-format "" --format "{start-end-time-style} {title}{repeat-symbol}{alarm-symbol}" today today 2>/dev/null)"
        if [[ -n "$_khal_out" ]]; then
          echo ""
          echo "\e[1;34m📅 Today's events:\e[0m"
          echo "$_khal_out"
          echo ""
        fi
      fi
    '';
    shellAliases = {
      ns = "nix shell";
      nr = "nix run";
    };
  };

  # List packages installed in system profile.
  # You can use https://search.nixos.org/ to find more packages (and options).
  environment = {
    systemPackages = (with pkgs; [
      # NOTE: neovim is NOT listed here — programs.neovim.enable adds the wrapped
      # package (finalPackage) automatically. Listing pkgs.neovim again would
      # install the *unwrapped* copy alongside it.
      # Ref: https://github.com/NixOS/nixpkgs/blob/master/nixos/modules/programs/neovim.nix

      # Kickstart.nvim external dependencies
      # Ref: https://github.com/nvim-lua/kickstart.nvim#install-external-dependencies
      gnumake          # provides `make`
      unzip
      gcc              # C compiler — needed to compile tree-sitter parsers
      ripgrep          # fast grep — used by Telescope live_grep
      fd               # fast find — used by Telescope find_files
      tree-sitter      # tree-sitter CLI — parser generator / grammar compiler
      # Clipboard: on a headless/SSH server, Neovim 0.10+ uses OSC 52 escape
      # sequences natively — no xclip/xsel/X11 needed on the server side.
      # Ref: https://neovim.io/doc/user/provider.html#clipboard-osc52
      # Nerd Font: install on your local (SSH client) machine, not here.
      # kickstart.nvim has vim.g.have_nerd_font = true in init.lua.

      bat
      curl
      wget
      zoxide
      fastfetch
      any-nix-shell
      # Storage tooling
      mdadm lvm2 dosfstools xfsprogs parted smartmontools
      # Docker
      docker-compose
      # Backup
      rclone
      # Mail (aerc + contact sync)
      aerc khard khal vdirsyncer
      w3m              # HTML-to-text — used by aerc's built-in html filter
      pass             # password store — credential backend for aerc & vdirsyncer
      # Typing practice
      gtypist toipe
    ]) ++ [ ntfyNotify ];
    variables = {
      LESSOPEN = "| ${pkgs.bat}/bin/bat --color=always --style=plain --paging=never %s";
      LESS = "-R";
      MANROFFOPT = "-c";
      MANPAGER = "sh -c 'col -bx | bat -l man -p'";
    };
  };

  programs.gnupg.agent.enable = true;
  programs.ssh.startAgent = true;
  programs.nix-index.enable = true;   # nix-locate — find which package provides a binary
  programs.command-not-found.enable = false;  # mutually exclusive with nix-index shell integrations

  services.openssh = {
    enable = true;
    ports = [ 28 ];
    settings = {
      PermitRootLogin = "no";
      PasswordAuthentication = false;
      KbdInteractiveAuthentication = false;
    };
  };

  # fail2ban — rate-limits brute-force SSH attempts on port 28
  # Complements endlessh (honeypot on port 22) and key-only auth as defense-in-depth
  services.fail2ban = {
    enable = true;
    maxretry = 5;
    bantime = "1h";
    bantime-increment.enable = true;
    jails = {
      sshd = {
        settings = {
          filter = "sshd";
          port = "28";
          maxretry = 3;
          findtime = "10m";
        };
      };
    };
  };

  # SMART drive monitoring → ntfy alerts
  services.smartd = {
    enable = true;
    autodetect = true;
    defaults.autodetected = "-a -o on -S on -n standby,q -s (S/../.././02|L/../../6/03) -W 4,45,55 -m root -M exec ${smartdAlert}";
    # NVMe drives run hotter than HDDs (normal at 50-60°C, throttle at 70-85°C).
    # Explicit entries are processed before DEVICESCAN, which then skips them.
    devices = [
      { device = "/dev/nvme0"; options = "-a -o on -S on -n standby,q -s (S/../.././02|L/../../6/03) -W 4,60,70 -m root -M exec ${smartdAlert}"; }
      { device = "/dev/nvme1"; options = "-a -o on -S on -n standby,q -s (S/../.././02|L/../../6/03) -W 4,60,70 -m root -M exec ${smartdAlert}"; }
    ];
    notifications.wall.enable = false;
  };

  # vdirsyncer contact sync (every 15 min)
  systemd.services.vdirsyncer-sync = {
    description = "Sync iCloud contacts and calendars via vdirsyncer";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    serviceConfig = {
      Type = "oneshot";
      User = "danteb";
    };
    path = with pkgs; [ vdirsyncer pass gnupg ];
    script = ''
      vdirsyncer sync icloud_contacts icloud_calendars google_calendars
    '';
  };

  systemd.timers.vdirsyncer-sync = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*:0/15";
      Persistent = true;
    };
  };

  # nix-index — weekly database rebuild for nix-locate / nwp
  systemd.services.nix-index-update = {
    description = "Rebuild nix-index database for nix-locate";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    serviceConfig = {
      Type = "oneshot";
      User = "danteb";
    };
    path = with pkgs; [ nix-index ];
    script = ''
      nix-index
    '';
  };

  systemd.timers.nix-index-update = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "weekly";
      Persistent = true;
    };
  };

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
    path = [ pkgs.docker pkgs.git pkgs.openssh pkgs.bash pkgs.coreutils ];
    environment = {
      GIT_SSH_COMMAND = "ssh -i /root/.ssh/docker-compose-deploy -o StrictHostKeyChecking=accept-new";
    };
    serviceConfig = {
      Type = "oneshot";
      WorkingDirectory = "/srv/homeserver";
    };
    script = ''
      git -c safe.directory=/srv/homeserver pull && \
      chown -R danteb:docker .git && \
      cd docker && \
      docker compose pull --ignore-buildable && \
      docker compose build --pull && \
      docker compose up -d --remove-orphans && \
      docker compose up -d --force-recreate homepage && \
      docker image prune -f && \
      docker network prune -f
    '';
  };

  systemd.timers.docker-compose-update = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* 04:00:00";
      Persistent = true;
      RandomizedDelaySec = "5m";
    };
  };

  # NixOS auto-upgrade (daily at 04:30, after Docker update at 04:00)
  # Downloads and builds new system closure but does NOT auto-reboot.
  # Manually reboot or run `nixos-rebuild switch` to activate.
  system.autoUpgrade = {
    enable = true;
    dates = "04:30";
    allowReboot = false;
  };

  # ── Drive health monitoring (RAID + LVM → ntfy) ───────────────────────────

  # Periodic check — catches issues that event handlers might miss
  systemd.services.drive-health-check = {
    description = "Periodic RAID and LVM health check with ntfy alerts";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    serviceConfig = {
      Type = "oneshot";
      Nice = 19;
      IOSchedulingClass = "idle";
    };
    path = with pkgs; [ mdadm lvm2 curl coreutils gnugrep gawk ];
    script = ''
      # ── mdadm RAID health ──
      if [ -f /proc/mdstat ]; then
        MDSTAT=$(cat /proc/mdstat)

        # Degraded array (underscore = missing/failed drive)
        if echo "$MDSTAT" | grep -qE '\[.*_.*\]'; then
          curl -s \
            -H "Title: RAID Degraded on ${config.networking.hostName}" \
            -H "Priority: urgent" \
            -H "Tags: rotating_light,computer" \
            -d "$(echo "$MDSTAT" | grep -A2 '^md')" \
            "${ntfyUrl}/${ntfyTopic}"
        fi

        # Active rebuild / resync
        if echo "$MDSTAT" | grep -qiE 'recovery|resync|reshape'; then
          curl -s \
            -H "Title: RAID Rebuild on ${config.networking.hostName}" \
            -H "Priority: high" \
            -H "Tags: construction,computer" \
            -d "$(echo "$MDSTAT" | grep -A3 '^md')" \
            "${ntfyUrl}/${ntfyTopic}"
        fi
      fi

      # ── LVM volume health ──
      LVM_BAD=$(lvs --noheadings -o lv_name,vg_name,lv_health_status 2>/dev/null \
                | awk 'NF>=3 && $3 != ""')
      if [ -n "$LVM_BAD" ]; then
        curl -s \
          -H "Title: LVM Health Issue on ${config.networking.hostName}" \
          -H "Priority: urgent" \
          -H "Tags: rotating_light,computer" \
          -d "Unhealthy LVM volumes: $LVM_BAD" \
          "${ntfyUrl}/${ntfyTopic}"
      fi

      # ── Missing LVM physical volumes ──
      PV_MISSING=$(pvs --noheadings 2>&1 | grep -i 'missing\|unknown' || true)
      if [ -n "$PV_MISSING" ]; then
        curl -s \
          -H "Title: LVM PV Missing on ${config.networking.hostName}" \
          -H "Priority: urgent" \
          -H "Tags: rotating_light,computer" \
          -d "$PV_MISSING" \
          "${ntfyUrl}/${ntfyTopic}"
      fi
    '';
  };

  systemd.timers.drive-health-check = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* 00/6:00:00";  # every 6 hours
      Persistent = true;
      RandomizedDelaySec = "5m";
    };
  };

  # Weekly RAID scrub — verifies data parity consistency.
  # The service blocks until the kernel finishes the check; RuntimeDirectory=
  # creates /run/mdadm-scrub for that duration, which mdadmAlert uses as a
  # sentinel to suppress the otherwise-noisy Rebuild{Started,Finished} events.
  systemd.services.mdadm-scrub = {
    description = "RAID array data scrub (parity consistency check)";
    serviceConfig = {
      Type = "oneshot";
      Nice = 19;
      IOSchedulingClass = "idle";
      RuntimeDirectory = "mdadm-scrub";
      TimeoutStartSec = "infinity";
    };
    path = with pkgs; [ curl coreutils ];
    script = ''
      MD=md0
      SYNC=/sys/block/$MD/md/sync_action
      MISMATCH=/sys/block/$MD/md/mismatch_cnt

      echo check > "$SYNC"

      # Wait for the kernel to actually start the operation.
      for _ in $(seq 1 30); do
        [ "$(cat "$SYNC")" != "idle" ] && break
        sleep 1
      done

      # Block until the scrub finishes — can take >24h on the full array.
      while [ "$(cat "$SYNC")" != "idle" ]; do
        sleep 60
      done

      # Hold the sentinel a bit longer so RebuildFinished is suppressed.
      sleep 30

      COUNT=$(cat "$MISMATCH" 2>/dev/null || echo "?")
      if [ "$COUNT" = "0" ]; then
        curl -s \
          -H "Title: RAID Scrub Clean on ${config.networking.hostName}" \
          -H "Priority: low" \
          -H "Tags: white_check_mark,computer" \
          -d "Weekly parity check complete on /dev/$MD — mismatch_cnt=0" \
          "${ntfyUrl}/${ntfyTopic}"
      else
        curl -s \
          -H "Title: RAID Scrub Found Mismatches on ${config.networking.hostName}" \
          -H "Priority: high" \
          -H "Tags: warning,computer" \
          -d "Parity check on /dev/$MD finished with mismatch_cnt=$COUNT — investigate" \
          "${ntfyUrl}/${ntfyTopic}"
      fi
    '';
  };

  systemd.timers.mdadm-scrub = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "Sun *-*-* 02:00:00";
      Persistent = true;
    };
  };

  # ── Generic ntfy failure handler ──────────────────────────────────────────
  # Wired via `unitConfig.OnFailure = "ntfy-failure@%n.service"` on units
  # whose normal failure path (an in-script curl) won't fire — e.g. when the
  # service is SIGTERM'd by TimeoutStartSec= or OOM-killed. Without this,
  # a timeout looks identical to a clean run from ntfy's perspective.
  systemd.services."ntfy-failure@" = {
    description = "ntfy alert for failed unit %i";
    scriptArgs = "%i";
    serviceConfig.Type = "oneshot";
    script = ''
      UNIT="$1"
      ${pkgs.curl}/bin/curl -s \
        -H "Title: $UNIT FAILED on ${config.networking.hostName}" \
        -H "Priority: high" \
        -H "Tags: warning,floppy_disk" \
        -d "systemd unit $UNIT exited abnormally (timeout, OOM, or non-zero exit). Inspect: journalctl -u $UNIT" \
        "${ntfyUrl}/${ntfyTopic}"
    '';
  };

  # ── Backup automation (Postgres dumps + Vaultwarden + rclone offsite) ─────

  systemd.services.postgres-backup = {
    description = "Dump all Postgres databases and copy Vaultwarden data";
    after = [ "docker.service" "network-online.target" ];
    requires = [ "docker.service" ];
    wants = [ "network-online.target" ];
    unitConfig.OnFailure = "ntfy-failure@%n.service";
    path = with pkgs; [ docker coreutils gzip curl gnutar findutils ];
    serviceConfig = {
      Type = "oneshot";
      Nice = 19;
      IOSchedulingClass = "idle";
    };
    script = ''
      set -uo pipefail

      BACKUP_ROOT="/data/automated-backups"
      PG_DIR="$BACKUP_ROOT/postgres"
      VW_DIR="$BACKUP_ROOT/vaultwarden"
      DATE=$(date +%Y-%m-%d)
      DOW=$(date +%u)  # 1=Monday, 7=Sunday

      mkdir -p "$PG_DIR/daily" "$PG_DIR/weekly" "$VW_DIR"

      FAILED=""
      SUCCEEDED=""

      # Format: "container:user:database"
      DATABASES="
        immich_postgres:postgres:immich
        authelia_postgres:authelia:authelia
        synapse_postgres:synapse:synapse
        nextcloud_postgres:nextcloud:nextcloud
        forgejo_postgres:forgejo:forgejo
        suwayomi_postgres:suwayomi:suwayomi_db
      "

      for entry in $DATABASES; do
        CONTAINER=$(echo "$entry" | cut -d: -f1)
        USER=$(echo "$entry" | cut -d: -f2)
        DB=$(echo "$entry" | cut -d: -f3)
        DUMP_FILE="$PG_DIR/daily/''${CONTAINER}-''${DATE}.sql.gz"

        if docker exec "$CONTAINER" pg_dump -U "$USER" "$DB" 2>/dev/null | gzip > "$DUMP_FILE"; then
          # Verify non-empty (gzip header alone is ~20 bytes)
          if [ "$(stat -c%s "$DUMP_FILE" 2>/dev/null || echo 0)" -gt 100 ]; then
            SUCCEEDED="$SUCCEEDED $CONTAINER"
          else
            FAILED="$FAILED $CONTAINER(empty)"
            rm -f "$DUMP_FILE"
          fi
        else
          FAILED="$FAILED $CONTAINER"
          rm -f "$DUMP_FILE"
        fi
      done

      # Weekly rotation: copy Sunday's dumps
      if [ "$DOW" = "7" ]; then
        for f in "$PG_DIR/daily/"*-"$DATE".sql.gz; do
          [ -f "$f" ] && cp "$f" "$PG_DIR/weekly/"
        done
      fi

      # Retention: 7 daily, 4 weekly
      find "$PG_DIR/daily" -name "*.sql.gz" -mtime +7 -delete
      find "$PG_DIR/weekly" -name "*.sql.gz" -mtime +28 -delete

      # Vaultwarden backup (SQLite WAL-mode safe for file copy)
      VW_FAILED=""
      if docker cp vaultwarden:/data/. "$VW_DIR/" 2>/dev/null; then
        VW_STATUS="ok"
      else
        VW_FAILED="vaultwarden"
      fi

      # ntfy notification
      SUCCEEDED=$(echo "$SUCCEEDED" | xargs)
      FAILED=$(echo "$FAILED $VW_FAILED" | xargs)

      # Silent on success — only alert on per-database / Vaultwarden failures.
      # Timeouts / SIGTERM / OOM kills are caught separately by unitConfig.OnFailure.
      if [ -n "$FAILED" ]; then
        curl -s \
          -H "Title: Backup FAILED on ${config.networking.hostName}" \
          -H "Priority: high" \
          -H "Tags: warning,floppy_disk" \
          -d "FAILED: $FAILED | Succeeded: $SUCCEEDED" \
          "${ntfyUrl}/${ntfyTopic}"
      fi
    '';
  };

  systemd.timers.postgres-backup = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* 03:00:00";
      Persistent = true;
      RandomizedDelaySec = "5m";
    };
  };

  systemd.services.rclone-offsite-daily = {
    description = "Daily rclone sync of backups, configs, and active data to Google Drive";
    after = [ "postgres-backup.service" "network-online.target" ];
    wants = [ "network-online.target" ];
    unitConfig.OnFailure = "ntfy-failure@%n.service";
    serviceConfig = {
      Type = "oneshot";
      Nice = 19;
      IOSchedulingClass = "idle";
      TimeoutStartSec = "8h";
    };
    environment.RCLONE_CONFIG = "/root/.config/rclone/rclone.conf";
    path = with pkgs; [ rclone curl coreutils ];
    script = ''
      set -uo pipefail

      REMOTE="gdrive-crypt:homeserver-backups"
      FAILED=""

      # Database dumps + Vaultwarden
      if ! rclone sync /data/automated-backups/ "$REMOTE/automated-backups/" \
          --transfers 4 --checkers 8 --log-level NOTICE 2>&1; then
        FAILED="$FAILED automated-backups"
      fi

      # Nextcloud user files
      if ! rclone sync /data/nextcloud/ "$REMOTE/nextcloud/" \
          --transfers 4 --checkers 8 --log-level NOTICE 2>&1; then
        FAILED="$FAILED nextcloud"
      fi

      # Selective /srv/docker/data (service configs, ~4.5 GB)
      if ! rclone sync /srv/docker/data/ "$REMOTE/docker-data/" \
          --exclude "plex/**" \
          --exclude "jellyfin/**" \
          --exclude "satisfactory-server/**" \
          --exclude "syncthing/**" \
          --exclude "tdarr/logs/**" \
          --exclude "nextcloud/html/**" \
          --exclude "nginxproxymanager/data/logs/**" \
          --exclude "prometheus/**" \
          --exclude "loki/**" \
          --exclude "alloy/**" \
          --transfers 4 --checkers 8 --log-level NOTICE 2>&1; then
        FAILED="$FAILED docker-data"
      fi

      FAILED=$(echo "$FAILED" | xargs)

      # Silent on success — only alert on rclone-level failures. Timeouts /
      # SIGTERM / OOM kills are caught separately by unitConfig.OnFailure.
      if [ -n "$FAILED" ]; then
        curl -s \
          -H "Title: Daily offsite sync FAILED on ${config.networking.hostName}" \
          -H "Priority: high" \
          -H "Tags: warning,cloud" \
          -d "Failed sync targets: $FAILED" \
          "${ntfyUrl}/${ntfyTopic}"
      fi
    '';
  };

  systemd.timers.rclone-offsite-daily = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* 03:30:00";
      Persistent = true;
      RandomizedDelaySec = "5m";
    };
  };

  systemd.services.rclone-offsite-weekly = {
    description = "Weekly rclone sync of large static media to Google Drive";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    unitConfig.OnFailure = "ntfy-failure@%n.service";
    serviceConfig = {
      Type = "oneshot";
      Nice = 19;
      IOSchedulingClass = "idle";
      TimeoutStartSec = "24h";
    };
    environment.RCLONE_CONFIG = "/root/.config/rclone/rclone.conf";
    path = with pkgs; [ rclone curl coreutils ];
    script = ''
      set -uo pipefail

      REMOTE="gdrive-crypt:homeserver-backups"
      FAILED=""

      # Home videos (374 GB, rare changes)
      if ! rclone sync /data/shared/media/other/ "$REMOTE/media/home-videos/" \
          --transfers 4 --checkers 8 --log-level NOTICE 2>&1; then
        FAILED="$FAILED home-videos"
      fi

      # Videotape digitization (179 GB, static)
      if ! rclone sync /data/Segu-raw/ "$REMOTE/media/segu-raw/" \
          --transfers 4 --checkers 8 --log-level NOTICE 2>&1; then
        FAILED="$FAILED segu-raw"
      fi

      # FCP edits + travel vlog (25 GB, static)
      if ! rclone sync /data/backups/ "$REMOTE/media/fcp-backups/" \
          --transfers 4 --checkers 8 --log-level NOTICE 2>&1; then
        FAILED="$FAILED fcp-backups"
      fi

      FAILED=$(echo "$FAILED" | xargs)

      # Silent on success — only alert on rclone-level failures. Timeouts /
      # SIGTERM / OOM kills are caught separately by unitConfig.OnFailure.
      if [ -n "$FAILED" ]; then
        curl -s \
          -H "Title: Weekly offsite sync FAILED on ${config.networking.hostName}" \
          -H "Priority: high" \
          -H "Tags: warning,cloud" \
          -d "Failed sync targets: $FAILED" \
          "${ntfyUrl}/${ntfyTopic}"
      fi
    '';
  };

  systemd.timers.rclone-offsite-weekly = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "Sun *-*-* 05:00:00";
      Persistent = true;
      RandomizedDelaySec = "15m";
    };
  };

  # Overture Maps monthly refresh — public retention is 60 days, so a
  # pinned release will silently break in two months without an updater.
  # The script discovers the latest tag via the STAC catalog and syncs
  # the places + divisions themes.
  systemd.services.overture-refresh = {
    description = "Sync the latest Overture Maps places + divisions release";
    after = [ "network-online.target" ];
    wants = [ "network-online.target" ];
    path = with pkgs; [ curl python3 awscli2 coreutils ];
    environment = {
      OPENCLAW_V3_BASE = "/data/openclaw-v3";
      OVERTURE_THEMES = "places,divisions";
      NTFY_URL = ntfyUrl;
      NTFY_TOPIC = ntfyTopic;
    };
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "/srv/homeserver/docker/scripts/overture-refresh.sh";
      User = "root";
      TimeoutStartSec = "8h";
    };
  };

  systemd.timers.overture-refresh = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "monthly";
      Persistent = true;
      RandomizedDelaySec = "30m";
    };
  };

  # NVIDIA (RTX 2070 SUPER — production driver, headless with persistenced)
  services.xserver.videoDrivers = [ "nvidia" ];  # driver registration only, does not enable X11
  hardware = {
    graphics.enable = true;
    nvidia = {
      modesetting.enable = true;
      open = true;
      nvidiaPersistenced = true;  # keeps GPU initialized without X/Wayland (headless)
      nvidiaSettings = false;
      package = config.boot.kernelPackages.nvidiaPackages.production;
    };
    nvidia-container-toolkit.enable = true;
  };

  # Prevent nixos-rebuild switch from failing due to in-use NVIDIA modules.
  # During --upgrade the new driver is on disk but old modules are in memory;
  # restarting these services before a reboot causes version-mismatch failures.
  systemd.services.nvidia-persistenced.restartIfChanged = false;
  systemd.services.nvidia-container-toolkit-cdi-generator.restartIfChanged = false;

  # sudo-rs — memory-safe Rust sudo with credential caching + asterisk feedback
  security = {
    sudo-rs = {
      enable = true;
      extraRules = [{
        groups = [ "wheel" ];
        commands = [{
          command = "ALL";
          options = [ "SETENV" ];  # allow `sudo -E` to preserve env (like doas keepEnv)
        }];
      }];
    };
    sudo.enable = false;
  };

  # This option defines the first version of NixOS you have installed on this particular machine,
  # and is used to maintain compatibility with application data (e.g. databases) created on older NixOS versions.
  #
  # Most users should NEVER change this value after the initial install, for any reason,
  # even if you've upgraded your system to a new NixOS release.
  #
  # This value does NOT affect the Nixpkgs version your packages and OS are pulled from,
  # so changing it will NOT upgrade your system - see https://nixos.org/manual/nixos/stable/#sec-upgrading for how
  # to actually do that.
  #
  # This value being lower than the current NixOS release does NOT mean your system is
  # out of date, out of support, or vulnerable.
  #
  # Do NOT change this value unless you have manually inspected all the changes it would make to your configuration,
  # and migrated your data accordingly.
  #
  # For more information, see `man configuration.nix` or https://nixos.org/manual/nixos/stable/options#opt-system.stateVersion .
  system.stateVersion = "25.11"; # Did you read the comment?

}

