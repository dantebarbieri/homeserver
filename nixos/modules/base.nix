# Boot, kernel hardening, Nix settings, locale and privilege escalation.
{ ... }:

{
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

  # Time / locale / console
  time.timeZone = "America/Chicago";
  i18n.defaultLocale = "en_US.UTF-8";
  console = {
    font = "Lat2-Terminus16";
    keyMap = "us";
  };

  # Flakes
  nix.settings.experimental-features = [ "nix-command" "flakes" ];

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
}
