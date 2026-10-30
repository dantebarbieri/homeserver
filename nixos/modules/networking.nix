# Bonded NICs, systemd-networkd, DNS and the host firewall.
{ ... }:

{
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
      miimon = "100";
    };
  };

  # networkd ignores the legacy bond driverOptions.primary setting.
  systemd.network.networks."40-enp66s0f1".networkConfig.PrimarySlave = true;

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
}
