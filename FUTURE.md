# Homeserver Future Roadmap

A prioritized roadmap of improvements, new services, hardening, and refinements across the entire homeserver monorepo. Generated from a comprehensive review of all configuration files as of 2026-04-01.

---

## Table of Contents

- [Priority 1: Backup Automation](#priority-1-backup-automation)
- [Priority 2: Monitoring Stack](#priority-2-monitoring-stack)
- [Priority 3: VPN Server for Remote Access](#priority-3-vpn-server-for-remote-access)
- [~~Priority 4: NixOS Kernel Hardening~~](#priority-4-nixos-kernel-hardening) ✅ Done
- [Priority 5: Uptime Monitoring & External Status Page](#priority-5-uptime-monitoring--external-status-page)
- [Priority 6: Docker Container Hardening](#priority-6-docker-container-hardening)
- [Priority 7: Paperless-ngx](#priority-7-paperless-ngx)
- [~~Priority 8: NixOS Auto-Upgrade~~](#priority-8-nixos-auto-upgrade) ✅ Done
- [~~Priority 9: Recyclarr CI Validation~~](#priority-9-recyclarr-ci-validation) ✅ Done
- [Priority 10: Homepage Dashboard Updates](#priority-10-homepage-dashboard-updates)
- [Priority 11: Mail Config Improvements](#priority-11-mail-config-improvements)
- [Priority 12: Additional Services](#priority-12-additional-services)
- [~~Priority 13: fail2ban for SSH~~](#priority-13-fail2ban-for-ssh) ✅ Done

---

## Priority 1: Backup Automation

**The single biggest gap in the setup.** Five Postgres instances (Authelia, Synapse, Nextcloud, Suwayomi, Immich), the Vaultwarden vault, irreplaceable media, and all service configs under `/srv/docker/data` have no automated backup.

### RAID storage breakdown (2026-04-01, 47 TB total)

| Path | Size | Replaceable? | Backup? |
|------|------|-------------|---------|
| `/data/shared/media/tv` | 20 TB | Yes (Sonarr) | No — RAID6 only |
| `/data/shared/media/movies` | 13 TB | Yes (Radarr) | No — RAID6 only |
| `/data/shared/media/anime` | 5.5 TB | Yes (Sonarr) | No — RAID6 only |
| `/data/shared/torrents` | 5.6 TB | Yes (re-download) | No — RAID6 only |
| `/data/immich/` | 1.2 TB | Yes (Google Photos + iCloud Photos) | No — already backed up externally |
| `/data/shared/media/indian` | 821 GB | Yes (Radarr/Sonarr) | No — RAID6 only |
| `/data/shared/media/other` | **374 GB** | **No — home videos** | **Yes** |
| `/data/Segu-raw/` | **179 GB** | **No — raw videotape digitization** | **Yes** |
| `/data/shared/reading` | 107 GB | Yes (Suwayomi/Komga) | No — RAID6 only |
| `/data/backups/` | **25 GB** | **No — FCP edits + travel vlog footage** | **Yes** |
| `/data/nextcloud/` | **220 MB** | **No — personal files** | **Yes** |

### What actually needs off-server backup

| Data | Size | Frequency of change |
|------|------|-------------------|
| `/data/shared/media/other` (home videos) | 374 GB | Rare (new videos occasionally) |
| `/data/Segu-raw/` (videotape digitization) | 179 GB | Static (one-time digitization) |
| `/data/backups/` (FCP edits + travel vlog) | 25 GB | Static |
| `/data/nextcloud/` (user files) | 220 MB | Active |
| Database dumps (Postgres compressed) | ~29 MB | Daily |
| Vaultwarden vault (SQLite) | Tiny | Active |
| `/srv/docker/data/authelia/` (config + secrets) | 168 KB | Rare |
| **Total** | **~578 GB** | |

### Measured database sizes (2026-04-01)

| Instance | Volume size | Compressed dump |
|----------|-------------|-----------------|
| `compose_pgdata` (Authelia + Synapse + Suwayomi) | 346 MB | ~0.1 MB |
| `compose_nextcloud-pgdata` | 71 MB | ~0.6 MB |
| Immich Postgres | (in compose_pgdata or own volume) | ~28 MB |
| `compose_yipitdata-pgdata` (temporary) | 64 MB | — |
| **Total compressed dumps** | | **~29 MB** |

With 7 daily + 4 weekly retention = ~320 MB for database dump history.

### Off-server storage: Google Drive via rclone ($0 additional cost)

You already pay for increased Google Drive storage. **578 GB fits within your existing quota** — no additional cost. Use `rclone` with a `crypt` wrapper so everything is encrypted at rest.

iCloud is not viable for this — there's no reliable CLI for iCloud Drive on Linux. If Google Drive ever runs out of space, Backblaze B2 is the fallback at $0.005/GB/mo (~$3/mo for 578 GB).

### What to implement

1. **Postgres dump timer** — NixOS systemd service + timer that runs `pg_dump` for each Postgres container via `docker exec`, stores dumps under `/data/backups/postgres/` with date-stamped filenames, rotates old dumps (keep 7 daily + 4 weekly), and sends ntfy alerts on success/failure.

2. **Vaultwarden backup** — Vaultwarden is SQLite-backed. Copy `/data` volume contents alongside Postgres dumps. The named volume `vw-data` can be accessed via `docker run --rm -v vw-data:/data alpine cp ...` or by mounting it in the backup script.

3. **Off-server shipping via rclone** — NixOS systemd timer that runs after the dump timer completes. Two sync jobs:
   - **Daily (small/active data):** `rclone sync` for database dumps, Vaultwarden vault, Nextcloud files, Authelia config → `gdrive-encrypted:homeserver-backups/daily/`
   - **Weekly (large/static media):** `rclone sync` for home videos (`/data/shared/media/other`), Segu-raw, FCP backups → `gdrive-encrypted:homeserver-backups/media/`
   
   The weekly job uses `rclone sync` which only uploads changed/new files — after the initial upload of ~578 GB, subsequent runs transfer only deltas. The static content (Segu-raw, FCP footage) won't re-upload after the first sync.

   Use `rclone crypt` remote wrapper so all data is encrypted at rest on Google Drive.

4. **Immich photos** — Already backed up via Google Photos and iCloud Photos. No additional backup needed. RAID6 provides local redundancy.

5. **Replaceable media (44 TB)** — Movies, TV, anime, torrents, reading. RAID6 protects against 2 simultaneous drive failures. If catastrophic loss occurs, Sonarr/Radarr/qBit can re-download everything. No cloud backup — cost-prohibitive and unnecessary.

### Files to modify

- `nixos/configuration.nix` — Add `postgres-backup`, `rclone-offsite-daily`, and `rclone-offsite-weekly` systemd services + timers (follows existing pattern from `drive-health-check`). Add `rclone` to `environment.systemPackages`.
- Server-side: run `rclone config` once to set up the Google Drive remote + crypt wrapper (interactive OAuth flow, must be done manually on the server)

### Verification

- **Postgres dumps:** Run `systemctl start postgres-backup` manually; confirm dump files appear in `/data/backups/postgres/` with correct sizes:
  - `immich_postgres-*.sql.gz` should be ~28 MB
  - `nextcloud_postgres-*.sql.gz` should be ~0.6 MB
  - Others should be small but non-zero
- **Failure alerting:** Stop a Postgres container, run backup, confirm ntfy sends a failure alert naming the specific container
- **Restore test (database):** `gunzip < /data/backups/postgres/immich_postgres-latest.sql.gz | docker exec -i immich_postgres psql -U immich immich_restore` — verify data exists in restored DB
- **rclone encryption:** `rclone ls gdrive-encrypted:homeserver-backups/daily/` should show encrypted backup files. `rclone cat` a small file to verify decryption works. Check Google Drive web UI to confirm files appear encrypted (random filenames, not readable).
- **rclone initial upload:** The first weekly sync will upload ~578 GB. Monitor progress with `rclone sync --progress ...`. At typical residential upload speeds (10-20 Mbps), expect 3-6 days for initial upload. Subsequent syncs should complete in minutes (only deltas).
- **Full restore test:** Make a change in Nextcloud, wait for daily backup, restore from the Google Drive copy to a temp location (`rclone copy gdrive-encrypted:homeserver-backups/daily/nextcloud/ /tmp/restore-test/`), verify the change is present.
- **Media restore test:** Pick one file from `/data/shared/media/other`, delete it locally, restore from Google Drive, verify integrity (`md5sum` before/after should match).
- Schedule a monthly calendar reminder to test a full restore of at least one database and one media file

---

## Priority 2: Monitoring Stack

Currently only Dashdot (system stats) and ntfy (alerts) exist. No historical metrics, no per-container resource tracking, no log aggregation, no trend detection.

### What to implement

1. **Prometheus** — Scrapes metrics from Docker containers, node-exporter (system stats), and service-specific exporters
2. **Grafana** — Visualization dashboards for CPU/memory/disk/network per container, RAID health, GPU utilization, and historical trends
3. **Loki + Promtail** — Centralized log aggregation. Promtail ships Docker JSON logs to Loki; Grafana queries them. Replaces the need to `docker logs` individual containers.
4. **node-exporter** — Exposes NixOS host metrics (CPU, memory, disk I/O, network, filesystem) to Prometheus
5. **cAdvisor** — Exposes per-container resource usage metrics to Prometheus

### Architecture

Create `docker/compose.monitoring.yml` with all five services on a dedicated `monitoring` internal network. Grafana also joins `proxy` for web access. Prometheus scrapes cAdvisor, node-exporter, and any services with built-in Prometheus endpoints (Authelia, Synapse, Nextcloud, AdGuard all support `/metrics`).

### Authentication & exposure

| Service | Publicly exposed? | Auth approach |
|---------|-------------------|---------------|
| **Grafana** | Yes (`grafana.danteb.com`) | Built-in auth (local accounts, RBAC) — solid, no Authelia needed |
| **Prometheus** | No — internal only | No built-in web auth. Do not expose publicly. Grafana queries it over the `monitoring` network. |
| **Loki** | No — internal only | No built-in web auth. Grafana queries it over the `monitoring` network. |
| **cAdvisor** | No — internal only | No built-in web auth. Prometheus scrapes it internally. |
| **node-exporter** | No — internal only | No built-in web auth. Prometheus scrapes it internally. |

Only Grafana joins the `proxy` network. Prometheus, Loki, cAdvisor, and node-exporter stay on the internal `monitoring` network only — they have no authentication and must never be exposed publicly.

**Security note:** Loki aggregates all Docker container logs, which may contain sensitive data (environment variables in error messages, request paths, user activity, stack traces). Ensure Grafana is configured with a strong admin password and anonymous access disabled. This is handled by Grafana's own auth — not a reason to add Authelia on top.

### Files to modify

- New `docker/compose.monitoring.yml` — Prometheus, Grafana, Loki, Promtail, node-exporter, cAdvisor
- `docker/docker-compose.yml` — Add to `include:` list
- `docker/sample.env` — Add `HOMEPAGE_VAR_GRAFANA_USER`, `HOMEPAGE_VAR_GRAFANA_PASS` (if adding widget)
- `docker/compose.dashboards.yml` — Pass through Grafana env vars to Homepage
- `homepage/services.yaml` — Add Grafana to dashboard (see Priority 10)
- `nixos/configuration.nix` — No changes needed (Prometheus runs in Docker, not NixOS)

### Verification

- `docker compose -f compose.monitoring.yml up -d` — all containers should start and pass health checks
- Access Grafana at `https://grafana.danteb.com` — default admin login should work
- Prometheus targets page (`https://grafana.danteb.com` or direct Prometheus UI) should show all scrape targets as "UP"
- Verify Loki data: in Grafana, add Loki as a data source → Explore → query `{container_name="plex"}` → should show recent logs
- Verify Prometheus data: in Grafana, add Prometheus data source → Explore → query `container_memory_usage_bytes` → should show per-container memory
- Import community dashboards: Docker monitoring (#1860), Node Exporter Full (#1860), Loki logs (#13639)
- Send a test ntfy alert and confirm it appears in Loki logs within 30 seconds

---

## Priority 3: VPN Server for Remote Access

Currently no way to access the homeserver remotely except SSH on port 28. A VPN server allows secure access to all services (including internal-only ones) from phone/laptop on untrusted networks.

### Option A: WireGuard in Docker (recommended)

Run as a Docker container using `wg-easy` (web management UI for peer/client management). Keeps all service logic in Docker for portability — if you ever migrate off NixOS, the VPN moves with the compose stack.

- Image: `ghcr.io/wg-easy/wg-easy:latest`
- Add to `docker/compose.core.yml` or `docker/compose.utilities.yml`
- Join `proxy` network for the web UI (has built-in password auth — no Authelia needed for the management UI, but consider Authelia since it's a VPN management portal)
- Requires UDP port 51820 opened on NixOS firewall + router (IPv4 port forward + IPv6 firewall rule)
- Environment variables: `WG_HOST` (public hostname/IP), `PASSWORD_HASH` (for web UI), `WG_DEFAULT_DNS` (optional, point to local DNS)

### Option B: Tailscale (alternative — NixOS-native)

NixOS has a first-class module. Zero-config, NAT traversal, MagicDNS. No port forwarding needed. However, this ties the VPN to NixOS rather than Docker, making it less portable.

```nix
services.tailscale.enable = true;
```

After `nixos-rebuild switch`, run `sudo tailscale up` to authenticate. Install Tailscale on phone/laptop. All devices see each other on a private `100.x.x.x` mesh.

### Files to modify

- **WireGuard (recommended)**: New entry in `docker/compose.core.yml` or `docker/compose.utilities.yml`, `docker/sample.env` for `WG_HOST` and password hash, `networking.firewall.allowedUDPPorts` in `configuration.nix` (add 51820), router IPv4 port forwarding for UDP 51820, and router IPv6 firewall rule for UDP 51820
- **Tailscale**: `nixos/configuration.nix` — Add `services.tailscale.enable = true;` and `networking.firewall.trustedInterfaces = [ "tailscale0" ];`

### Verification

- **WireGuard**: Access `https://vpn.danteb.com` (or chosen subdomain), log in to wg-easy UI, create a client config. Import on phone. Disconnect from home WiFi, use cellular. Access `https://jellyfin.danteb.com` — should work via the tunnel. Run `curl ifconfig.me` on the client to confirm traffic routes through the VPN.
- **Tailscale**: After `sudo tailscale up`, run `tailscale status` to confirm the server appears. From another Tailscale device, `ping 100.x.x.x` (the server's Tailscale IP). Access `http://100.x.x.x:8096` (Jellyfin) to confirm internal services are reachable.
- For either: test from a non-home network (cellular, coffee shop WiFi) to confirm remote access works

---

## ~~Priority 4: NixOS Kernel Hardening~~ ✅ Done

Quick win, low risk. No kernel parameters are currently set beyond defaults.

### What to add

```nix
boot.kernel.sysctl = {
  "kernel.sysrq" = 0;                    # Disable magic SysRq key
  "kernel.kptr_restrict" = 2;            # Hide kernel pointers from all users
  "kernel.dmesg_restrict" = 1;           # Restrict dmesg to CAP_SYSLOG
  "kernel.yama.ptrace_scope" = 2;        # Restrict ptrace to CAP_SYS_PTRACE
  "net.core.bpf_jit_harden" = 2;        # Harden BPF JIT compiler
  "kernel.unprivileged_bpf_disabled" = 1; # Disable unprivileged BPF
};
```

### What each setting does

All settings are real Linux kernel sysctls and the values follow CIS benchmark / KSPP hardening recommendations. None will break Docker containers — containers don't use SysRq, don't read `/proc/kallsyms`, and typically don't need `ptrace` or unprivileged BPF.

| Setting | Value | Explanation |
|---------|-------|-------------|
| `kernel.sysrq` | `0` | **Disables the Magic SysRq key.** SysRq lets you send commands directly to the kernel via a keyboard combo (force reboot, sync disks, kill all processes, etc.). On a headless server with no physical keyboard, there's no legitimate use — but an attacker with console access (e.g., via IPMI/BMC) could abuse it to reboot or crash the system. |
| `kernel.kptr_restrict` | `2` | **Hides kernel pointer addresses from ALL users, including root.** `/proc/kallsyms` and similar interfaces normally expose the memory addresses of kernel functions. Attackers need these to bypass KASLR (Kernel Address Space Layout Randomization) — knowing where kernel code lives in memory is the first step in most kernel exploits. Value `2` = hidden from everyone; `1` = hidden from non-root only. |
| `kernel.dmesg_restrict` | `1` | **Restricts `dmesg` to processes with `CAP_SYSLOG`.** The kernel ring buffer (`dmesg`) logs hardware info, driver details, memory addresses, and boot messages — useful for reconnaissance. `CAP_SYSLOG` is a Linux capability specifically for reading syslog/dmesg. Normal users and most processes don't have it; only root or processes explicitly granted the capability can read the kernel log. |
| `kernel.yama.ptrace_scope` | `2` | **Restricts `ptrace` to processes with `CAP_SYS_PTRACE`.** `ptrace` (process trace) lets one process inspect and modify another process's memory — it's how debuggers like `gdb` work, but also how attackers dump secrets (API keys, passwords, tokens) from running processes. Value `0` = any process can trace any other (dangerous); `1` = only a parent can trace its child; `2` = only processes with `CAP_SYS_PTRACE` (almost nothing on a server needs this). |
| `net.core.bpf_jit_harden` | `2` | **Hardens the BPF JIT compiler.** BPF (Berkeley Packet Filter) is a kernel subsystem that runs sandboxed programs inside the kernel — used for networking (iptables, tc), tracing (perf, bpftrace), and security tools (seccomp). The JIT (Just-In-Time) compiler converts BPF bytecode to native machine code for performance. Without hardening, the JIT output is predictable and can be exploited for kernel code execution via JIT spraying attacks. Value `2` = hardened for all users including root (enables constant blinding and disables optimizations that could leak info). |
| `kernel.unprivileged_bpf_disabled` | `1` | **Prevents non-root users from loading BPF programs.** While BPF is powerful and useful, it has been a frequent source of kernel privilege escalation vulnerabilities (multiple CVEs per year). Restricting BPF loading to root significantly reduces the kernel's attack surface. Docker containers and normal services don't need to load BPF programs. |

### Files to modify

- `nixos/configuration.nix` — Add `boot.kernel.sysctl` block (place after the existing boot/kernel section, around line 80)

### Verification

- `sudo nixos-rebuild test` first to validate without persisting
- After `nixos-rebuild switch`, verify each setting:
  - `sysctl kernel.sysrq` should return `0`
  - `sysctl kernel.kptr_restrict` should return `2`
  - `sysctl kernel.dmesg_restrict` should return `1`
  - `sysctl kernel.yama.ptrace_scope` should return `2`
  - `sysctl net.core.bpf_jit_harden` should return `2`
  - `sysctl kernel.unprivileged_bpf_disabled` should return `1`
- Run `dmesg` as a non-root user — should get "Permission denied" (confirms `dmesg_restrict`)
- Confirm Docker containers still start normally (some sysctl changes can break container networking — test `docker compose up -d` after switch)
- Confirm SSH still works on port 28 (test from a second terminal before closing your current session)

---

## Priority 5: Uptime Monitoring & External Status Page

Homepage's `siteMonitor` only shows current state — no history, no trend detection, no alerting on repeated flaps. More importantly, a self-hosted status page goes down when the server goes down — exactly when friends need to check status.

### Completed

- **Uptime Kuma deployed** — running at `https://uptime.danteb.com` in `compose.dashboards.yml`, Homepage widget configured with `HOMEPAGE_VAR_KUMA_SLUG`, status page created with slug `homeserver`
- **Upptime repo created** — `dantebarbieri/homeserver-status` (from Upptime template), `.upptimerc.yml` configured with 11 services, local clone at `~/Programming/HomeServer-Status`

### Remaining: Configure Uptime Kuma Monitors

The Uptime Kuma container is running and the status page exists, but no monitors have been added yet. This is the remaining work.

#### 1. Create monitors

In Uptime Kuma (`https://uptime.danteb.com`), click **"Add New Monitor"** for each service. Use type **HTTP(s)** for all web services.

**Recommended monitors** — all public-facing services with a web UI or API:

| Monitor Name | URL | Notes |
|-------------|-----|-------|
| Plex | `https://plex.danteb.com` | |
| Jellyfin | `https://jellyfin.danteb.com` | |
| Seerr | `https://seerr.danteb.com` | |
| Immich | `https://immich.danteb.com` | |
| Komga | `https://komga.danteb.com` | |
| Radarr | `https://radarr.danteb.com` | |
| Sonarr | `https://sonarr.danteb.com` | |
| Bazarr | `https://bazarr.danteb.com` | |
| Prowlarr | `https://prowlarr.danteb.com` | |
| Tdarr | `https://tdarr.danteb.com` | |
| qBittorrent | `https://qbittorrent.danteb.com` | |
| SABnzbd | `https://sabnzbd.danteb.com` | |
| Suwayomi | `https://suwayomi.danteb.com` | |
| SearXNG | `https://searxng.danteb.com` | |
| Nginx Proxy Manager | `https://nginx-proxy-manager.danteb.com` | Critical — if this is down, everything is down |
| Element | `https://element.danteb.com` | |
| Synapse | `https://matrix.danteb.com` | |
| Authelia | `https://authelia.danteb.com` | |
| Nextcloud | `https://cloud.danteb.com` | |
| AdGuard Home | `https://adguardhome.danteb.com` | |
| Vaultwarden | `https://vaultwarden.danteb.com` | |
| Syncthing | `https://syncthing.danteb.com` | |
| ntfy | `https://ntfy.danteb.com` | Monitor this even though it's the notification target — if ntfy is down, you want to see it in the dashboard |
| Dashdot | `https://dashdot.danteb.com` | |
| IT-Tools | `https://tools.danteb.com` | |
| Homepage | `https://homepage.danteb.com` | |
| Travel Planner | `https://travel.danteb.com` | |

**Skip these** — game servers use raw TCP/UDP ports, not HTTP, and are only online when actively used:
- Minecraft servers (mc.danteb.com, rlcraft.danteb.com)
- Hytale server
- Satisfactory server

**Monitor settings** — good defaults for all HTTP monitors:
- Heartbeat Interval: `60` seconds (default)
- Retries: `3` (avoids false alerts from transient network hiccups)
- Accepted Status Codes: `200-299` (some services may return 401/403 — adjust per-service if needed)

#### 2. Configure ntfy notifications

Go to **Settings → Notifications → Setup Notification**:
- Notification Type: **ntfy**
- Topic URL: `https://ntfy.danteb.com/homeserver-alerts`
- Priority: `high` (for down alerts)
- Check **"Apply on all existing monitors"** to enable globally
- Click **Test** to confirm a notification arrives on your phone

#### 3. Add monitors to the status page

Go to `/status/homeserver?edit`:
1. Click **"+ Add Group"** — create groups to organize (e.g., "Media", "Infrastructure", "Utilities") or use a single "Services" group
2. Within each group, click **"Add a monitor"** and select from your created monitors
3. Click **Save**

#### 4. Set the Homepage widget slug

```zsh
# Edit .env and set:
# HOMEPAGE_VAR_KUMA_SLUG=homeserver
# Then:
docker compose up -d homepage
```

#### 5. Verify

- All monitors should show green "UP" status within 60 seconds of creation
- Stop a container (`docker compose stop jellyfin`), confirm Uptime Kuma detects downtime within ~60s and ntfy fires an alert
- Restart the container, confirm recovery notification
- Check Homepage — the Uptime Kuma widget should show monitor counts (up/down)

### Remaining: Upptime (External Status Page)

The repo `dantebarbieri/homeserver-status` is created and `.upptimerc.yml` is configured. Remaining manual steps:

1. **Add `GH_PAT` secret** — Create a fine-grained PAT with read-write permissions for Actions, Contents, Issues, Workflows. Add as repo secret `GH_PAT` in Settings → Secrets.
2. **Enable GitHub Pages** — repo Settings → Pages → Source: "Deploy from a branch" → Branch: `gh-pages` / `/(root)`
3. **Cloudflare DNS** — Add CNAME record: `status.danteb.com` → `dantebarbieri.github.io`. This specific record overrides the wildcard — all other `*.danteb.com` subdomains continue working normally. Confirmed per [Cloudflare wildcard DNS docs](https://developers.cloudflare.com/dns/manage-dns-records/reference/wildcard-dns-records/).
4. **GitHub Pages custom domain** — repo Settings → Pages → Custom domain: `status.danteb.com`. GitHub auto-provisions TLS.
5. **Enable workflows** — visit the Actions tab and enable them

#### Upptime verification

- Check GitHub Actions tab — "Uptime CI" workflow should run every 5 minutes
- Visit `https://status.danteb.com` — should show the status page with all monitors
- Test from phone on cellular (not home WiFi) — page should load even if the server is down (it's hosted on GitHub Pages)

---

## Priority 6: Docker Container Hardening

Most containers run with default capabilities, no resource limits, and read-write root filesystems. Only `searxng` and `suwayomi_redis` properly use `cap_drop: [ALL]`.

### What to implement

#### 6a. Resource limits (low urgency)

With 100+ GB of RAM, resource conservation is not a concern. These limits are **safety nets against runaway processes**, not resource management. The consequence of NOT setting limits: a memory leak in one container (e.g., Synapse is notorious for this) could consume all available RAM and trigger the Linux OOM killer, which may kill a random important process (like Postgres) instead of the leaky one. With limits, only the misbehaving container gets killed by Docker.

Given the large memory headroom, this is low urgency — the suggested limits below are generous and unlikely to constrain normal operation:

| Service | Suggested memory limit | Rationale |
|---------|----------------------|-----------|
| plex | 8G | Transcoding can spike |
| jellyfin | 8G | Same |
| immich-machine-learning | 6G | CUDA ML models |
| immich-server | 4G | Photo processing |
| synapse | 2G | Matrix homeserver (known for memory leaks) |
| nextcloud | 2G | PHP workers |
| All Postgres instances | 1G each | Shared buffers |
| All Redis instances | 512M each | In-memory cache |
| adguardhome | 512M | DNS cache |
| vaultwarden | 256M | Lightweight |

Game servers (Minecraft 24G/12G, Satisfactory 16G) already have memory settings — add matching `deploy` limits so Docker enforces them.

#### 6b. Capability dropping (incremental, not global)

**Do NOT add `cap_drop: [ALL]` to `common-service` globally** — this would affect 50+ services at once and breakage may not be immediately obvious (some services fail silently or only break under specific conditions).

Instead, apply incrementally per-service, starting with the simplest stateless services that are easiest to validate:

**Wave 1 (low risk):** Redis/Valkey instances, flaresolverr, lk-jwt-service, bmc-ip-monitor, qbit-port-sync
**Wave 2 (medium risk):** Starr apps (Radarr, Sonarr, Bazarr, Prowlarr), Komga, Komf, Suwayomi
**Wave 3 (test carefully):** Plex, Jellyfin, Nextcloud, Synapse, Immich

```yaml
cap_drop:
  - ALL
cap_add:
  - NET_BIND_SERVICE  # only if binding ports < 1024
```

Services known to need additional capabilities:
- `gluetun`: `NET_ADMIN` (already configured — VPN tunnel setup)
- `coturn`: `NET_BIND_SERVICE`, `NET_RAW` (TURN protocol)
- `adguardhome`: `NET_BIND_SERVICE` (port 53)
- `dashdot`: runs privileged (required for hardware access — permanent exception)

Test each service individually after adding, monitor for 24-48 hours before moving to the next wave.

#### 6c. Read-only root filesystems

Add `read_only: true` + `tmpfs: ["/tmp", "/run"]` to stateless services:
- All Redis/Valkey instances
- flaresolverr
- lk-jwt-service
- qbit-port-sync
- bmc-ip-monitor

#### 6d. Health checks for missing services

Add `healthcheck:` to services that currently lack them:
- `flaresolverr` — `curl -f http://localhost:8191/health`
- `arm-server` — `curl -f http://localhost:8080/health` (check actual health endpoint)
- `komga` — `curl -f http://localhost:25600/api/v1/actuator/health`
- `komf` — `curl -f http://localhost:8085/health` (check actual port/endpoint)

### Files to modify

- Individual `compose.*.yml` files — Add `cap_drop`/`cap_add` per service (wave by wave), `deploy.resources.limits`, `read_only`, `tmpfs`
- Test each service after changes to ensure it still starts

### Verification

- After adding `cap_drop: [ALL]` to a wave of services: `docker compose config` to validate YAML, then `docker compose up -d` — watch for any container crash loops
- Check resource limits are applied: `docker inspect <container> | grep -A5 Memory` — should show the configured limit
- Check capabilities: `docker inspect <container> --format '{{.HostConfig.CapDrop}}'` — should show `[ALL]`
- For read-only: `docker exec <container> touch /test-file` — should fail with "Read-only file system"
- Monitor for 24-48 hours after applying changes — some services may need additional capabilities or writable paths that aren't immediately obvious
- Run `docker compose logs --tail=50 <service>` for each modified service to check for permission errors

---

## Priority 7: Paperless-ngx

**Lower priority** — depends on increased Nextcloud usage first. Consider moving contacts to Nextcloud (from iCloud via vdirsyncer) and becoming a regular Nextcloud user before adding another document management layer. Paperless-ngx complements Nextcloud well once you're actively using it.

Document scanning, OCR, full-text search, and automatic tagging. The NVIDIA RTX 2070 SUPER can accelerate OCR processing.

### What to implement

- `paperless-ngx` container (with optional GPU-accelerated OCR via `ocrmypdf`)
- Dedicated Postgres instance (or reuse an existing one — but isolation is cleaner)
- Redis instance for task queue
- Consume folder on RAID for document ingestion (scan/email → folder → auto-import)

### Files to modify

- New `docker/compose.documents.yml` — paperless-ngx, postgres, redis
- `docker/docker-compose.yml` — Add to `include:` list
- `docker/sample.env` — Add Paperless env vars (secret key, OCR language, etc.)
- `homepage/services.yaml` — Add to Utilities section
- NPM — Add proxy host for `https://paperless.danteb.com`

### Verification

- `docker compose -f compose.documents.yml up -d` — all three containers start and pass health checks
- Access `https://paperless.danteb.com`, create admin account
- Upload a test PDF — verify OCR extracts text (check document content in the web UI)
- Place a test document in the consume folder — verify auto-import within the configured polling interval
- Search for text from the OCR'd document — should return results
- Verify GPU acceleration (if configured): check Paperless logs for OCR timing, compare with CPU-only

---

## ~~Priority 8: NixOS Auto-Upgrade~~ ✅ Done

Currently the daily timer updates Docker containers, but NixOS itself requires manual `nixos-rebuild switch`. This means security patches for the kernel, OpenSSH, and system packages are only applied when you remember to rebuild.

### What to implement

```nix
system.autoUpgrade = {
  enable = true;
  dates = "04:30";                # After Docker update at 04:00
  allowReboot = false;            # Stage updates only, reboot manually
  # Optionally pin to a channel:
  # channel = "https://nixos.org/channels/nixos-25.11";
};
```

With `allowReboot = false`, this only downloads and builds the new system closure. You still need to manually reboot or run `nixos-rebuild switch` to activate it. This is a safe middle ground.

### Files to modify

- `nixos/configuration.nix` — Add `system.autoUpgrade` block

### Verification

- After `nixos-rebuild switch`, check the timer exists: `systemctl list-timers | grep auto-upgrade`
- Manually trigger: `sudo systemctl start nixos-upgrade` — should complete without errors
- Check `/var/log/journal` for the upgrade service logs: `journalctl -u nixos-upgrade --since today`
- Confirm the system hasn't rebooted unexpectedly (since `allowReboot = false`)
- After a manual reboot, run `nixos-rebuild switch` and confirm the staged update activates cleanly

---

## ~~Priority 9: Recyclarr CI Validation~~ ✅ Done

The recyclarr config is excellent but has no automated validation. Since you commit directly to main, a GitHub Actions workflow would catch YAML errors and recyclarr config issues before the server pulls the update.

### What to implement

A GitHub Actions workflow that runs on push to `recyclarr-configs/` files:

```yaml
# .github/workflows/recyclarr-validate.yml
name: Validate Recyclarr Config
on:
  push:
    paths: ['recyclarr-configs/**']
  pull_request:
    paths: ['recyclarr-configs/**']
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run recyclarr config test
        run: |
          docker run --rm \
            -v ${{ github.workspace }}/recyclarr-configs:/config \
            ghcr.io/recyclarr/recyclarr:latest \
            config list --config /config/recyclarr.yml
```

Note: This does use Docker-in-CI, but it's a quick validation-only command — `recyclarr config list` parses and validates the YAML without connecting to Sonarr/Radarr, and the Docker image is lightweight. The CI job should complete in well under 60 seconds. The `sync --preview` command would require API access and isn't suitable for CI.

### Also consider

- **`yamllint`** as a fast pre-check before the Docker step — runs natively (no Docker), catches syntax errors instantly. Add as a first step in the workflow.
- Docker Compose validation: `docker compose -f docker/compose.*.yml config` in CI for all compose files (separate workflow)

### Files to modify

- New `.github/workflows/recyclarr-validate.yml`
- Optionally: new `.github/workflows/compose-validate.yml` (for Docker Compose files)

### Verification

- Push a commit that touches `recyclarr-configs/recyclarr.yml` — workflow should trigger and pass
- Introduce a deliberate YAML syntax error (e.g., bad indentation) — push and confirm the workflow fails with a clear error message
- Fix the error, push again — workflow should pass
- Check GitHub Actions tab for workflow run history and timing (should complete in under 2 minutes)

---

## Priority 10: Homepage Dashboard Updates

Lower priority but keeps the dashboard accurate.

### Missing services to add

- **Uptime Kuma** — If added (Priority 5), Homepage has a built-in `uptimekuma` widget.
- **Grafana** — If added (Priority 2), Homepage has a built-in `grafana` widget.

**Note:** arm-server does NOT have a web UI — it's an API-only service for mapping anime IDs between AniList, AniDB, MAL, and Kitsu. The [docs site](https://arm.haglund.dev/docs) is API documentation, not a dashboard. It's consumed internally by other services (Komf, etc.) and should not be added to the homepage.

### Missing widgets for existing services

- **Suwayomi** — Listed but has no widget. Homepage has a native [`suwayomi` widget](https://gethomepage.dev/widgets/services/suwayomi/) that shows chapter counts by category. Add with `type: suwayomi`, `url`, and optional `username`/`password` fields.
- **Gluetun VPN status (optional)** — Gluetun doesn't need its own dashboard entry since qBittorrent already covers the download workflow. However, Gluetun exposes a REST API at `http://gluetun:8000/v1/openvpn/status` (or wireguard equivalent). Could add as a `customapi` widget on the existing qBittorrent entry or as a standalone entry showing the forwarded port and connected server — nice-to-have, not essential.

### Layout consideration

If monitoring services are added (Grafana, Uptime Kuma), create a new "Infrastructure" section in `homepage/settings.yaml` rather than overcrowding Utilities. Use `mdi-server-network` or similar icon.

### Files to modify

- `homepage/services.yaml` — Add Suwayomi widget, new monitoring services, optional gluetun widget
- `homepage/settings.yaml` — Add Infrastructure section to `layout` (if creating new section)
- `docker/compose.dashboards.yml` — Pass through any new `HOMEPAGE_VAR_*` env vars
- `docker/sample.env` — Add templates for new API keys
- `homepage/WIDGET_API_KEYS.md` — Document how to obtain new widget credentials

### Verification

- After editing `services.yaml`, reload Homepage (container restart or wait for file-watch reload)
- Verify each new service entry shows: correct icon, clickable link to `https://service.danteb.com`, green siteMonitor dot, Docker container stats (CPU/mem/network)
- For widgets: verify live data renders (not "N/A" or error states). Check browser console for API errors.
- Verify no existing services broke (scroll through all sections)

---

## Priority 11: Mail Config Improvements

### 11a. iCloud Calendar Sync

vdirsyncer supports CalDAV but only CardDAV (contacts) is configured. Adding calendar sync is straightforward.

Add to `vdirsyncer/config.example`:

```ini
[pair icloud_calendars]
a = "icloud_cal_local"
b = "icloud_cal_remote"
collections = ["from a", "from b"]
conflict_resolution = "b wins"
metadata = ["displayname", "color"]

[storage icloud_cal_local]
type = "filesystem"
path = "~/.local/share/vdirsyncer/calendars/icloud/"
fileext = ".ics"

[storage icloud_cal_remote]
type = "caldav"
url = "https://caldav.icloud.com/"
username = "YOUR_APPLE_ID@icloud.com"
password.fetch = ["command", "pass", "contacts/icloud-app-password"]
```

Also need a calendar viewer — `khal` is the terminal equivalent of `khard` for calendars.

### 11b. setup.sh validation

Add `command -v` checks before using platform-specific tools:

```sh
if [ "$PLATFORM" = "linux" ] && ! command -v pass >/dev/null 2>&1; then
    echo "WARNING: 'pass' not found. Install it for credential storage."
fi
if [ "$PLATFORM" = "macos" ] && ! command -v security >/dev/null 2>&1; then
    echo "WARNING: 'security' command not found (should be built into macOS)."
fi
```

### Files to modify

- `mail-config/vdirsyncer/config.example` — Add calendar pair/storage sections
- `mail-config/setup.sh` — Add `command -v` validation, create calendar data directories, update cron job to sync calendars too
- `nixos/configuration.nix` — Update vdirsyncer timer script to include `icloud_calendars` sync (currently only syncs `icloud_contacts`)

### Verification

- Run `setup.sh` on a fresh machine (or after removing symlinks) — should complete without errors and show warnings if `pass`/`security` missing
- Run `setup.sh` again (idempotency test) — should report "already exists" for all items, no duplicates
- After configuring credentials: `vdirsyncer discover icloud_calendars` should find calendars
- `vdirsyncer sync icloud_calendars` should download `.ics` files to `~/.local/share/vdirsyncer/calendars/icloud/`
- If `khal` is installed: `khal list` should show upcoming events

---

## Priority 12: Additional Services

Services listed in order of interest, highest first.

### ~~IT-Tools~~ ✅ Done

Deployed at `https://tools.danteb.com`. In `compose.utilities.yml` + homepage dashboard.

### Forgejo (self-hosted git) ⭐

Self-hosted git server. Mirror GitHub repos for redundancy, host private repos without GitHub dependency. Forgejo is the community fork of Gitea, more actively developed.

- Image: `codeberg.org/forgejo/forgejo:latest`
- Needs its own Postgres instance
- Add as new `compose.git.yml`
- Proxy at `https://git.danteb.com` (has solid built-in auth — no Authelia)
- Key use case: mirror this homeserver monorepo for disaster recovery

**Verification**: Access the URL, create admin account, create a test repo, push a commit. Set up a mirror of a GitHub repo, confirm it syncs.

### Calibre-web ⭐

Self-hosted ebook library with a web reader. Good for ebooks beyond manga/comics (Komga already covers those). Especially useful for migrating Kindle library from parent's Amazon account — download via Calibre desktop, import into Calibre-web, access from any device.

- Image: `lscr.io/linuxserver/calibre-web:latest`
- Needs a Calibre database (can create empty one on first run)
- Mount ebook library from RAID (e.g., `${RAID}/shared/reading/ebooks`)
- Add to `compose.media.yml`
- Proxy at `https://books.danteb.com` (has built-in auth — no Authelia)

**Verification**: Access the URL, upload a test EPUB. Verify the web reader renders it correctly. Test OPDS feed if you use a mobile reader app.

### Code-server

VS Code in the browser. Useful alongside nvim for when a GUI editor is more convenient (complex refactors, extensions, visual diff).

- Image: `lscr.io/linuxserver/code-server:latest`
- Add to `compose.utilities.yml`
- Mount project directories as needed (e.g., `/srv/homeserver`)
- Proxy at `https://code.danteb.com` with Authelia SSO (code-server has basic password auth, but Authelia is recommended for a code execution environment)

**Verification**: Access the URL, open a terminal, verify you can edit files. Install extensions, confirm they persist across container restarts.

### Home Assistant (future — low priority)

Only valuable once you have smart home devices (lights, sensors, cameras, locks). Powerful automation engine. Worth adding the compose file now so it's ready when needed, but no rush.

- Image: `ghcr.io/home-assistant/home-assistant:stable`
- Needs `privileged: true` or specific device access for Zigbee/Z-Wave dongles
- Add as new `compose.home.yml`
- Proxy at `https://ha.danteb.com` (has solid built-in auth — no Authelia)

**Verification**: Access the URL, complete onboarding. If you have any smart devices, verify they're discoverable.

### Changedetection.io (optional)

Monitors web pages for changes and sends notifications. Use cases: tracking software release pages, ISP service notices/outage pages, price monitoring for hardware, detecting changes to terms of service.

- Image: `ghcr.io/dgtlmoon/changedetection.io:latest`
- Needs a playwright/chrome container for JS-rendered pages
- Add to `compose.utilities.yml`, join `proxy` network
- Proxy at `https://changedetection.danteb.com` (has built-in auth — no Authelia)
- Connect to ntfy for notifications

**Verification**: Add a monitor for a page that changes frequently (e.g., a GitHub releases page). Wait for a change, confirm ntfy notification arrives.

### pgAdmin (optional)

Web-based Postgres management GUI for the 5+ Postgres instances. Mostly useful for debugging — databases are service-managed and rarely need manual intervention.

- Image: `dpage/pgadmin4:latest`
- Add to `compose.utilities.yml`
- Join `proxy` + internal networks that contain Postgres instances (`authelia`, `matrix`, `nextcloud`, `immich`, `suwayomi`)
- Proxy at `https://pgadmin.danteb.com` (has solid built-in auth — no Authelia)

**Verification**: Access the URL, log in, add a server connection to one of the Postgres instances (e.g., `authelia_postgres:5432`). Browse tables, run a simple query.

---

## ~~Priority 13: fail2ban for SSH~~ ✅ Done

Endlessh is a honeypot on port 22 but doesn't protect the real SSH on port 28. fail2ban would rate-limit brute-force attempts.

### What to implement

```nix
services.fail2ban = {
  enable = true;
  maxretry = 5;
  bantime = "1h";
  bantime-increment.enable = true;  # Exponential backoff for repeat offenders
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
```

### Files to modify

- `nixos/configuration.nix` — Add `services.fail2ban` block

### Verification

- After `nixos-rebuild switch`: `systemctl status fail2ban` should show active
- `sudo fail2ban-client status sshd` should show the jail is running with 0 currently banned
- Test: from another machine, attempt 4 failed SSH logins to port 28 with a wrong password. On the 4th attempt, the connection should be refused (banned).
- `sudo fail2ban-client status sshd` should now show 1 banned IP
- `sudo fail2ban-client set sshd unbanip <your-ip>` to unban yourself
- Confirm legitimate SSH still works from your authorized keys (fail2ban only triggers on failed auth)

---

## Summary Table

| # | Item | Area | Risk | Effort | Notes |
|---|------|------|------|--------|-------|
| 1 | Backup automation | NixOS + Docker | Fixes critical gap | Medium | |
| 2 | Monitoring stack (Prometheus/Grafana/Loki) | Docker | None (additive) | Medium-High | Grafana uses own auth; Prometheus/cAdvisor internal only |
| 3 | VPN server (WireGuard in Docker) | Docker | Low | Low | wg-easy container; portable across OS |
| 4 | ~~Kernel hardening (sysctl)~~ ✅ | NixOS | Low (test first) | Low | All settings validated against CIS/KSPP |
| 5 | Uptime monitoring (Upptime + Kuma) | Docker + GitHub | None (additive) | Low | Cloudflare wildcard override confirmed |
| 6 | Container hardening (limits, caps, read-only) | Docker | Medium (test each) | Medium | Incremental per-service, not global; limits are safety nets |
| 7 | Paperless-ngx | Docker | None (additive) | Medium | Lower priority — increase Nextcloud usage first |
| 8 | ~~NixOS auto-upgrade~~ ✅ | NixOS | Low (no auto-reboot) | Low | |
| 9 | ~~Recyclarr CI validation~~ ✅ | GitHub Actions | None | Low | Keep Docker-based CI; add yamllint pre-check |
| 10 | Homepage dashboard updates | Homepage | None | Low | Suwayomi widget, arm-server is API-only (no dashboard) |
| 11 | Mail calendar sync + setup.sh validation | Mail | None | Low | |
| 12 | Additional services | Docker | None (additive) | Low-Medium each | Priority: IT-Tools > Forgejo > Calibre-web > Code-server |
| 13 | ~~fail2ban for SSH~~ ✅ | NixOS | Low | Low | |
