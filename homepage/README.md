# Homepage Dashboard Config

Configuration files for [Homepage](https://gethomepage.dev/) — a self-hosted dashboard
with Docker integration and service status monitoring.

This is the **canonical service catalogue** for the homeserver. All services are
defined and monitored here.

Replaces the previous [Homer](https://github.com/dantebarbieri/homeserver-homer)
dashboard, which is now archived.

## Files

| File | Purpose |
|------|---------|
| `settings.yaml` | Global theme, layout, and search settings |
| `services.yaml` | App links and backend status cards with consumer descriptions |
| `bookmarks.yaml` | External links (GitHub repos) and local management pages |
| `widgets.yaml` | Top-level page widgets (date/time, weather) |
| `docker.yaml` | Docker socket connection for container status |

## Dashboard Layout

The dashboard has three tabs, ordered by everyday use:

- **Apps** (default): Watch & Request, Read & Listen, Files & Photos,
  Personal & Communication, Search & Tools, Plan & Cook, Games & Guides,
  and Game Servers.
- **Manage**: Media Automation, Downloads, Network & Access, Monitoring,
  Development, and Hardware & External Links.
- **Backends**: Media Helpers, Communication & Sync, Monitoring Pipeline,
  Network Helpers, Website & Development Backends, and Databases & Caches.

App and management groups use three-column rows on desktop; backend groups
use four-column rows. Groups are collapsible, with Databases & Caches initially
collapsed. The header keeps search (SearXNG), date/time, and weather on every tab.

List each service once. Services with useful interfaces belong under Apps or
Manage, even when they support other apps (for example, BookBridge and Soularr).
Backend descriptions name the apps or integrations they power and their role.
Anime Relations is explicitly marked as having an undocumented consumer rather
than guessing which app uses its API.
Backend cards normally have no `href` or `siteMonitor`: API roots are not web
interfaces, and monitoring uses the existing Docker socket without exposing
private services or joining their networks. CouchDB retains its useful admin link.

Docker status reports container state and health where a healthcheck exists;
it does not prove end-to-end application availability. The disabled Hytale
server is labeled so absence is not mistaken for
an unexpected outage. Homepage itself is not listed on its own dashboard.
The qBittorrent port-sync card uses Compose's generated container name
`compose-qbit-port-sync-1` because that service has no explicit `container_name`.

Every service and bookmark group must have a matching `layout` entry in
`settings.yaml` with an explicit `tab`; otherwise Homepage repeats it on all tabs.
The layout also controls display order independently of the order in the
catalogue. Use distinct names for service groups and bookmark groups.

## Deployment

Deploy `services.yaml`, `settings.yaml`, `widgets.yaml`, and `bookmarks.yaml`
together to the config directory mounted by `HOMEPAGE_CONFIG_PATH`. After updating
the files, use Homepage's refresh button at the bottom right to reload the layout.

Copy these files to your Homepage config directory:

```bash
cp -r /path/to/homepage/* ${DATA}/homepage/config/
```

Then start the service:

```bash
docker compose up -d homepage
```

## Enabling Service Widgets

Many services show live data (movie counts, download speeds, etc.) via widgets.
These require API keys from each service's settings page.

Uncomment and set the `HOMEPAGE_VAR_*` environment variables in
`compose.dashboards.yml`, or edit the keys directly in `services.yaml`.

👉 **[Widget API Keys Guide](WIDGET_API_KEYS.md)** — step-by-step instructions
for obtaining every token.

See the [Homepage widget docs](https://gethomepage.dev/widgets/services/) for
details on each service's widget configuration.

## Features vs Homer

- **Docker status**: Green/red indicator per service based on container state
- **Site monitoring**: HTTP ping checks on public URLs (status dot)
- **Service widgets**: Live stats from Radarr, Sonarr, Plex, qBittorrent, etc.
- **Search**: Integrated SearXNG search bar
- **Weather**: OpenMeteo weather widget (no API key needed)
