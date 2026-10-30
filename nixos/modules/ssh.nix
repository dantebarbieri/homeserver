# SSH server and brute-force protection.
{ ... }:

{
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
}
