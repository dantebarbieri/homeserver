# RAID6 + LVM cache activation, SMART monitoring and RAID health checks.
{ config, pkgs, ... }:

let
  inherit (import ../lib/shared.nix { inherit config pkgs; })
    ntfyUrl ntfyTopic smartdAlert mdadmAlert;
in
{
  # LVM + RAID
  services.lvm.enable = true;
  boot.initrd.services.lvm.enable = true;

  # Installs thin-provisioning-tools and rewrites the global/*_check_executable
  # paths in lvm.conf. Despite the "thin" name this also supplies cache_check —
  # without it LVM looks for /usr/sbin/cache_check, which does not exist on
  # NixOS, and silently skips cache metadata validation on every activation of
  # the lvmcache-backed lv_data.
  services.lvm.boot.thin.enable = true;

  boot.swraid.enable = true;
  boot.swraid.mdadmConf = builtins.concatStringsSep "\n" [
    "ARRAY /dev/md0 metadata=1.2 spares=1 name=homeserver:0 UUID=a13e736d:e8805790:1e2d65a6:c4f6b3d2"
    "PROGRAM ${mdadmAlert}"
  ];

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
    # The kernel keeps scrubbing if systemd stops this monitoring process.
    restartIfChanged = false;
    unitConfig.OnFailure = "ntfy-failure@%n.service";
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

      ACTION=$(cat "$SYNC")
      case "$ACTION" in
        idle) echo check > "$SYNC" ;;
        check) echo "Monitoring existing parity check on /dev/$MD" ;;
        *)
          echo "Cannot start a parity check while /dev/$MD is performing $ACTION" >&2
          exit 1
          ;;
      esac

      # Wait for the kernel to actually start the operation.
      STARTED=0
      for _ in $(seq 1 30); do
        ACTION=$(cat "$SYNC")
        case "$ACTION" in
          check) STARTED=1; break ;;
          idle) ;;
          *)
            echo "Unexpected RAID action while waiting for check: $ACTION" >&2
            exit 1
            ;;
        esac
        sleep 1
      done
      if [ "$STARTED" -ne 1 ]; then
        echo "Parity check did not start within 30 seconds on /dev/$MD" >&2
        exit 1
      fi

      # Block until the scrub finishes — can take >24h on the full array.
      while true; do
        ACTION=$(cat "$SYNC")
        case "$ACTION" in
          idle) break ;;
          check) ;;
          *)
            echo "Parity check replaced by unexpected RAID action: $ACTION" >&2
            exit 1
            ;;
        esac
        sleep 60
      done

      # Hold the sentinel a bit longer so RebuildFinished is suppressed.
      sleep 30

      COUNT=$(cat "$MISMATCH")
      if ! [[ "$COUNT" =~ ^[0-9]+$ ]]; then
        echo "Invalid mismatch count for /dev/$MD: $COUNT" >&2
        exit 1
      fi
      if [ "$COUNT" = "0" ]; then
        curl --fail-with-body --show-error --silent --max-time 30 \
          -H "Title: RAID Scrub Clean on ${config.networking.hostName}" \
          -H "Priority: low" \
          -H "Tags: white_check_mark,computer" \
          -d "Weekly parity check complete on /dev/$MD — mismatch_cnt=0" \
          "${ntfyUrl}/${ntfyTopic}"
      else
        curl --fail-with-body --show-error --silent --max-time 30 \
          -H "Title: RAID Scrub Found Mismatches on ${config.networking.hostName}" \
          -H "Priority: high" \
          -H "Tags: warning,computer" \
          -d "Parity check on /dev/$MD finished with mismatch_cnt=$COUNT — investigate" \
          "${ntfyUrl}/${ntfyTopic}"
        exit 1
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

  # vg_redundant spans /dev/md0 (RAID6) + /dev/nvme1n1p1 (lvmcache PV), and
  # lv_data is a cached LV (cache_pool_data_cpool over lv_data_corig).
  #
  # LVM's udev rules autoactivate via `systemd-run --unit lvm-activate-<vg>`,
  # a *transient* unit. Because the VG spans two PVs that appear at different
  # times (NVMe enumerates before the SATA array finishes assembling), the rule
  # fires twice. The second invocation reuses the same unit name, so systemd
  # signals the first one mid-activation — LVM logs "Interrupted..." and exits
  # 5 after having activated the cache sub-LVs but not the parent. lv_data then
  # cannot activate ("prohibited while ..._cmeta is active"), /data fails to
  # mount, and boot drops to emergency mode.
  #
  # A `systemd.services."lvm-activate-vg_redundant"` override cannot fix this:
  # the transient unit wins at runtime, so the ordering is never applied.
  # Instead, autoactivation is disabled for this VG and activation is driven
  # explicitly here, ordered after md0 assembly and before data.mount.
  #
  # Requires one-time out-of-band state on the server (persisted in the VG's
  # own metadata, not in this file):
  #     sudo vgchange --setautoactivation n vg_redundant
  #
  # DefaultDependencies=no is mandatory: this unit is ordered Before= a
  # local-fs mount, and the implicit After=basic.target would otherwise form a
  # dependency cycle (basic → sysinit → local-fs → data.mount → this unit).
  systemd.services.activate-vg-redundant = {
    description = "Activate vg_redundant (RAID6 + lvmcache) for /data";

    unitConfig.DefaultDependencies = false;
    conflicts  = [ "shutdown.target" ];
    after      = [ "dev-md0.device" ];
    wants      = [ "dev-md0.device" ];
    before     = [ "data.mount" "shutdown.target" ];
    requiredBy = [ "data.mount" ];

    path = with pkgs; [ lvm2.bin gnugrep coreutils ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };

    script = ''
      # md0 may exist as a device before LVM has scanned it as a PV.
      for _ in $(seq 1 60); do
        if pvs --noheadings -o vg_name /dev/md0 2>/dev/null \
            | grep -q vg_redundant; then
          break
        fi
        sleep 1
      done

      if ! pvs --noheadings -o vg_name /dev/md0 2>/dev/null \
          | grep -q vg_redundant; then
        echo "ERROR: /dev/md0 not recognized as PV in vg_redundant after 60s" >&2
        exit 1
      fi

      # Clear any partial activation left by a stray event before activating,
      # otherwise the cached lv_data refuses to assemble over live sub-LVs.
      vgchange -an vg_redundant || true
      vgchange -ay vg_redundant
    '';
  };
}
