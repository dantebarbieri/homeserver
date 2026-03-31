# homeserver-docker

Docker Compose configuration for my home server, organized into logical service categories.

## Structure

```
├── docker-compose.yml      # Main index file (includes all categories)
├── compose.common.yml      # Shared templates (extends only, not included)
├── compose.core.yml        # Core infrastructure (nginx proxy, ddclient, endlessh)
├── compose.auth.yml        # Authelia authentication stack
├── compose.dashboards.yml  # Homepage, Dashdot
├── compose.downloads.yml   # VPN/torrent stack, SABnzbd, Flaresolverr
├── compose.gaming.yml      # Game servers (Minecraft, Hytale, Satisfactory)
├── compose.immich.yml      # Immich photo management stack
├── compose.matrix.yml      # Matrix communication stack (Synapse, Element, Coturn)
├── compose.nextcloud.yml   # Nextcloud cloud storage stack
├── compose.media.yml       # Media consumption (Plex, Jellyfin, Komga, Suwayomi)
├── compose.searxng.yml     # SearXNG search engine stack
├── compose.starr.yml       # *arr apps + Seerr + Whisper ASR
├── compose.utilities.yml   # Utilities (Vaultwarden, Syncthing, ntfy)
├── compose.websites.yml    # Web hosting (custom sites)
├── hwaccel.transcoding.yml # Hardware acceleration for transcoding
├── hwaccel.ml.yml          # Hardware acceleration for ML
├── .env                    # Environment variables (not in git)
├── scripts/                # Operational shell scripts
├── dockerfiles/            # Custom Dockerfiles and container scripts
└── docs/                   # Service-specific documentation
```

## Usage

```bash
# Start all services
docker compose up -d

# Pull updates and restart
docker compose pull && docker compose up -d

# View merged configuration
docker compose config

# Start specific category only (for testing)
docker compose -f compose.gaming.yml up -d
```

## Service Categories

| Category | Services |
|----------|----------|
| **Core** | nginxproxymanager, ddclient, endlessh |
| **Auth** | authelia, authelia_postgres, authelia_redis |
| **Dashboards** | homepage, dashdot |
| **Downloads** | vpn-netns, gluetun, qbittorrent, qbit-port-sync, sabnzbd, flaresolverr |
| **Gaming** | minecraft-server, rlcraft-minecraft-server, hytale-server, satisfactory-server |
| **Immich** | immich-server, immich-machine-learning, immich-redis, immich-postgres |
| **Matrix** | synapse, synapse_postgres, element, coturn, livekit, lk-jwt-service |
| **Nextcloud** | nextcloud, nextcloud_cron, nextcloud_postgres, nextcloud_redis |
| **Media** | plex, jellyfin, komga, komf, suwayomi, suwayomi_postgres |
| **SearXNG** | searxng, searxng_redis |
| **Starr** | radarr, sonarr, bazarr, prowlarr, recyclarr, seerr, whisperasr, tdarr |
| **Utilities** | vaultwarden, syncthing, ntfy |
| **Websites** | (custom web apps) |

## Shared Templates

`compose.common.yml` provides reusable service templates:
- `gpu-service` - NVIDIA GPU passthrough
- `common-service` - Standard restart policy and logging
- `hotio-service` - For Hotio images (PUID/PGID/TZ)
- `linuxserver-service` - For LinuxServer.io images

Usage in category files:
```yaml
services:
  radarr:
    extends:
      file: compose.common.yml
      service: hotio-service
    image: ghcr.io/hotio/radarr:latest
    # ...
```

## Matrix Setup

See [MATRIX.md](MATRIX.md) for the full Matrix stack setup guide (Synapse, Element, Coturn, PostgreSQL).

See [MATRIX-RTC.md](MATRIX-RTC.md) for adding voice/video call support via LiveKit (MatrixRTC).

## Nextcloud Setup

See [NEXTCLOUD.md](NEXTCLOUD.md) for the full Nextcloud cloud storage setup guide (PostgreSQL, Redis, cron, reverse proxy).

## Tdarr Setup

See [TDARR.md](TDARR.md) for the full Tdarr configuration guide (HEVC compression, library setup, transcode flows, Sonarr/Radarr integration).

## Service Catalogue

All services are catalogued and monitored in the [Homepage](https://github.com/dantebarbieri/homepage) dashboard.
