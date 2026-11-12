{ pkgs }:

let
  jobs = pkgs.writeText "safe-reboot-test-jobs.json" (builtins.toJSON {
    services = [ ];
    timers = [ "backup.timer" ];
  });
  worker = pkgs.writeText "safe-reboot-test-worker.py" ''
    import importlib.util
    from pathlib import Path
    import sys

    spec = importlib.util.spec_from_file_location("safe_reboot", "${../safe-reboot.py}")
    reboot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reboot)
    # Only the homeserver-specific prerequisites are mocked, never logind or reboot.
    reboot.raid_blockers = lambda: []
    reboot.verify_live_restore = lambda: None
    reboot.verify_backup_health = lambda: None
    reboot.WIKI_BACKUPS = Path("/run/wiki-backups")
    sys.exit(reboot.main(sys.argv[1:]))
  '';
  check = pkgs.writeShellScriptBin "safe-reboot-check" ''
    exec ${pkgs.python3}/bin/python3 ${worker} ${jobs} --check
  '';
in
pkgs.testers.runNixOSTest {
  name = "safe-reboot-logind";

  nodes.machine = {
    users.users.operator.isNormalUser = true;
    services.getty.autologinUser = "operator";
    environment.systemPackages = [ check ];
    security.polkit.enable = true;
    security.polkit.extraConfig = ''
      polkit.addRule(function(action, subject) {
        if (subject.user === "operator" &&
            action.id === "org.freedesktop.login1.inhibit-block-shutdown")
          return polkit.Result.YES;
      });
    '';
    systemd.tmpfiles.rules = [
      "f /run/lock/homeserver-compose.lock 0644 root root -"
      "d /run/wiki-backups 0700 root root -"
    ];
    systemd.services.backup.serviceConfig = {
      Type = "oneshot";
      ExecStart = "${pkgs.coreutils}/bin/true";
    };
    systemd.timers.backup = {
      wantedBy = [ "timers.target" ];
      timerConfig.OnActiveSec = "1d";
    };
    systemd.services."inhibitor@" = {
      serviceConfig.User = "operator";
      serviceConfig.ExecStart = "${pkgs.systemd}/bin/systemd-inhibit --what=shutdown --mode=%i --who=regression --why=regression ${pkgs.coreutils}/bin/sleep infinity";
    };
    systemd.services.root-inhibitor.serviceConfig.ExecStart =
      "${pkgs.systemd}/bin/systemd-inhibit --what=shutdown --mode=block --who=regression --why=regression ${pkgs.coreutils}/bin/sleep infinity";
    systemd.services.root-weak-inhibitor.serviceConfig.ExecStart =
      "${pkgs.systemd}/bin/systemd-inhibit --what=shutdown --mode=block-weak --who=regression-weak --why=regression ${pkgs.coreutils}/bin/sleep infinity";
    systemd.services.safe-reboot = {
      path = [ pkgs.systemd ];
      serviceConfig = {
        Type = "exec";
        ExecStart = "${pkgs.python3}/bin/python3 ${worker} ${jobs} --worker";
        ExecStopPost = "${pkgs.python3}/bin/python3 ${worker} ${jobs} --cleanup";
        RuntimeDirectory = "safe-reboot";
        RuntimeDirectoryPreserve = true;
      };
    };
  };

  testScript = ''
    start_all()
    machine.wait_for_unit("systemd-logind.service")
    machine.wait_for_unit("backup.timer")
    machine.wait_until_succeeds("loginctl list-sessions --no-legend | grep operator")
    boot_id = machine.succeed("cat /proc/sys/kernel/random/boot_id").strip()

    with subtest("dry run passes with the operator logged in and no inhibitors"):
        machine.succeed("loginctl list-sessions --no-legend | grep operator")
        assert "No reboot blockers detected." in machine.succeed("safe-reboot-check")

    for unit in ("root-inhibitor", "inhibitor@block", "inhibitor@block-weak"):
        with subtest(f"root service respects {unit} and restores timers"):
            machine.succeed(f"systemctl start {unit}.service")
            machine.wait_until_succeeds(
                "systemd-inhibit --list --no-pager | grep regression", timeout=30
            )
            report = machine.fail("safe-reboot-check")
            assert "Would refuse to reboot: logind shutdown inhibitor by regression" in report, report
            machine.succeed("systemctl start safe-reboot.service")
            machine.wait_until_succeeds("systemctl is-failed safe-reboot.service", timeout=30)
            invocation = machine.succeed(
                "systemctl show safe-reboot.service --property=InvocationID --value"
            ).strip()
            machine.succeed(
                f"journalctl _SYSTEMD_INVOCATION_ID={invocation} --no-pager | "
                "grep 'Operation denied due to active block inhibitor'"
            )
            machine.wait_for_unit("backup.timer")
            machine.succeed("test ! -e /run/safe-reboot")
            assert machine.succeed("cat /proc/sys/kernel/random/boot_id").strip() == boot_id
            machine.succeed(
                f"systemctl stop {unit}.service; "
                "systemctl reset-failed safe-reboot.service"
            )

    with subtest("logged-in operator and a root block-weak inhibitor do not block the reboot"):
        machine.succeed("loginctl list-sessions --no-legend | grep operator")
        machine.succeed("systemctl start root-weak-inhibitor.service")
        machine.wait_until_succeeds(
            "systemd-inhibit --list --no-pager | grep regression-weak", timeout=30
        )
        assert "No reboot blockers detected." in machine.succeed("safe-reboot-check")
        machine.succeed("systemctl start safe-reboot.service")
        machine.wait_for_shutdown()
        machine.start()
        machine.wait_for_unit("multi-user.target")
        assert machine.succeed("cat /proc/sys/kernel/random/boot_id").strip() != boot_id
  '';
}
