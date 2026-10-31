# homeserver-docker

Docker Compose configuration for my home server, organized into logical service categories.

## Structure

```
├── docker-compose.yml      # Main index file (includes all categories)
├── compose.common.yml      # Shared templates (extends only, not included)
├── compose.core.yml        # Core infrastructure (NPM, ddclient, endlessh, bmc-ip-monitor)
├── compose.auth.yml        # Authelia authentication stack
├── compose.dashboards.yml  # Homepage, Dashdot
├── compose.downloads.yml   # VPN/torrent stack, SABnzbd, Flaresolverr, qbit-manage
├── compose.gaming.yml      # Game servers (Minecraft, Hytale, Satisfactory)
├── compose.immich.yml      # Immich photo management stack
├── compose.matrix.yml      # Matrix communication stack (Synapse, Element, Coturn, LiveKit)
├── compose.media.yml       # Media consumption (Plex, Jellyfin, ARM, Komga, Suwayomi, Calibre-web, Audiobookshelf, Storyteller, BookBridge)
├── compose.nextcloud.yml   # Nextcloud cloud storage stack
├── compose.romm.yml        # RomM library and MariaDB
├── compose.searxng.yml     # SearXNG search engine stack
├── compose.starr.yml       # *arr apps + Seerr + Whisper ASR + Tdarr
├── compose.utilities.yml   # Utilities (Vaultwarden, Syncthing, ntfy)
├── compose.websites.yml    # Web hosting (travel-planner)
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
| **Core** | nginxproxymanager, ddclient, endlessh, bmc-ip-monitor |
| **Auth** | authelia, authelia_postgres, authelia_redis |
| **Dashboards** | homepage, suwayomi-widget, dashdot |
| **Downloads** | vpn-netns, gluetun, qbittorrent, qbit-port-sync, qbit-manage, sabnzbd, flaresolverr |
| **Gaming** | minecraft-server (vanilla Hardcore), matcha-minecraft-server (Fabric/Matcha), rlcraft-minecraft-server, satisfactory-server; hytale-server (opt-in profile) |
| **Immich** | immich-server, immich-machine-learning, immich-redis, immich-postgres |
| **Matrix** | synapse, synapse_postgres, element, coturn, livekit, lk-jwt-service |
| **Media** | plex, jellyfin, navidrome, anime-relations, komga, komf, suwayomi, suwayomi_postgres, calibre-web, audiobookshelf, storyteller, bookbridge, librofm-downloader |
| **Nextcloud** | nextcloud, nextcloud_cron, nextcloud_postgres, nextcloud_redis |
| **RomM** | romm, romm-db |
| **SearXNG** | searxng, searxng_redis |
| **Starr** | radarr, sonarr, bazarr, prowlarr, recyclarr, seerr, whisperasr, tdarr |
| **Utilities** | vaultwarden, syncthing, ntfy |
| **Websites** | travel-planner, recipe, skyjo, sorry, mirklurk, mirklurk-db, mirklurk-backup, mirklurk-map, mirklurk-map-uploads |

## Shared Templates

`compose.common.yml` provides reusable service templates:
- `gpu-service` - NVIDIA GPU passthrough and the standard restart policy (no logging block)
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

See [MATRIX.md](docs/MATRIX.md) for the full Matrix stack setup guide (Synapse, Element, Coturn, PostgreSQL).

See [MATRIX-RTC.md](docs/MATRIX-RTC.md) for adding voice/video call support via LiveKit (MatrixRTC).

## qBittorrent Web UI

qBittorrent bundles the latest stable [VueTorrent](https://github.com/VueTorrent/VueTorrent)
from its official `ghcr.io/vuetorrent/vuetorrent-lsio-mod:latest` image into the
LinuxServer qBittorrent image. In qBittorrent's Web UI settings, enable the
alternative Web UI and set its location to `/vuetorrent`.

The daily 04:00 update job and `dcu`/`dcupdate` use `docker compose build --pull`,
which refreshes both upstream images. A VueTorrent release changes the built
qBittorrent image, so Compose recreates it even if qBittorrent itself has not
changed. Failed builds leave the running container on its previous image and
are reported through the existing update failure handling. No extra timer,
startup download, or optional VueTorrent backend is needed.

The former `${DATA}/qbittorrent/VueTorrent` checkout is no longer mounted; any
existing copy is preserved on disk. For rollback, pin the VueTorrent `FROM` tag
in `dockerfiles/Dockerfile.qbittorrent` to a known-good release (for example,
`2.36.1`). The `/config` and torrent-data mounts are unchanged.

## Game Servers

See [MINECRAFT.md](docs/MINECRAFT.md) for the separate Hardcore, Matcha and RLCraft
worlds, and [HYTALE.md](docs/HYTALE.md) for Hytale's disabled profile and recovery.

## Nextcloud Setup

See [NEXTCLOUD.md](docs/NEXTCLOUD.md) for the full Nextcloud cloud storage setup guide (PostgreSQL, Redis, cron, reverse proxy).

## Tdarr Setup

See [TDARR.md](docs/TDARR.md) for the full Tdarr configuration guide (HEVC compression, library setup, transcode flows, Sonarr/Radarr integration).

## Audiobooks Setup

See [AUDIOBOOKS.md](docs/AUDIOBOOKS.md) for Audiobookshelf, Storyteller readalouds, BookBridge progress sync (KOReader), and the libro.fm downloader.

## RomM Setup

See [`../docs/ROMM.md`](../docs/ROMM.md) for ROM library storage, native authentication, reverse proxy, and Steam Deck setup.

## Recipe Collection

The handwritten `recipe` service at `https://recipe.danteb.com` remains in
`compose.websites.yml`. The four model-generated experiments are retired; see
[RECIPE-APPS.md](docs/RECIPE-APPS.md) for cleanup and retained data.

## MirkLurk Wiki

See [MIRKLURK.md](docs/MIRKLURK.md) for the external wiki release, scoped secrets,
nested-domain TLS, first installation, database backups, and controlled updates.

## Mirklurk World Viewer

See [MIRKLURK-MAP.md](docs/MIRKLURK-MAP.md) for the pinned static viewer release,
proxy settings, validation, and updates.

## Service Catalogue

All services are catalogued and monitored in the [Homepage](https://github.com/dantebarbieri/homepage) dashboard.
