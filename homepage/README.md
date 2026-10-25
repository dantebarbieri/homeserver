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
interfaces. Docker status and inventory widgets use the existing Docker socket
without exposing private services or joining their networks. CouchDB retains
its useful admin link.

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

Set the `HOMEPAGE_VAR_*` values in the server's `docker/.env` and recreate
Homepage from the main Compose entry point. `compose.dashboards.yml` explicitly
passes these variables into the container; do not put real keys in the tracked
YAML files.

👉 **[Widget API Keys Guide](WIDGET_API_KEYS.md)** — step-by-step instructions
for obtaining every token.

See the [Homepage widget docs](https://gethomepage.dev/widgets/services/) for
details on each service's widget configuration.

### Native and custom coverage

Prefer native widgets where available. Forgejo uses Homepage's compatible
`gitea` widget. Syncthing uses `customapi` for local, all-folder sync completion,
item counts, and remaining bytes; MirkLurk Wiki uses it for public MediaWiki
statistics. Both call documented JSON APIs over the existing proxy network,
without new published ports or adapter services. Suwayomi keeps its existing
authenticated adapter because its UI_LOGIN authentication needs a login flow.

New authenticated widgets need `HOMEPAGE_VAR_FORGEJO_KEY` and
`HOMEPAGE_VAR_SYNCTHING_KEY`; setup and permission details are in the
[key guide](WIDGET_API_KEYS.md). Missing credentials produce widget errors until
configured. Existing widget credentials and Suwayomi's adapter are unchanged.

Every service now has a widget. Existing native/API widgets keep their
application statistics. The other cards, including all backends, use the shared
`&container-info` widget: **App / Build**, **Container Up**, **State**, and
**Health**. The list layout leaves room for build identifiers on narrow cards.
Do not scrape authenticated pages, disable authentication, or expose databases
just to fill a card.

### Container inventory

`homepage-inventory` serves a narrowly filtered JSON API on the existing internal
`homepage-widgets` network. It has no published ports, NPM host, `proxy` network,
or additional application credentials. It only returns the four display fields,
never Docker environment variables, mounts, labels, healthcheck output, logs,
or complete inspection responses. Containers must belong to Compose project
`compose`. Only GET is accepted; this is not a general-purpose Docker proxy.

Version sources are deliberately explicit. Verified application image labels
and database/NPM image version variables supply application versions. WireGuard
reads the installed package's `release.version` (v14), **not** its unrelated
`package.json` version. Satisfactory reads its installed Steam build ID.
Application-owned Git revisions appear as `Build <revision>`. Otherwise the
widget says `Image <ID>`, an immutable image identity, **not an application
version**. In particular, inherited Ubuntu, Node, Nginx, and Deno versions must
not masquerade as Storyteller, Komf, Whisper, or MirkMap versions. Hytale's image
version is explicitly labeled **Wrapper**, not the game version.

Uptime is time since the container started, not a promise about application
availability or a process's age. A running container without a healthcheck says
**No check**, not healthy. A stopped container says **Not running**, has no live
uptime, and retains its actual Docker state; Hytale stays disabled and is not
started by this feature. Missing containers and Docker/version-source failures
are visible widget errors, not invented healthy or zero-valued responses.
Widgets refresh every 30 seconds; successful inventory results are cached for
10 seconds, without serving stale data after a failed refresh.

The adapter runs as the unprivileged `node` user with `DOCKER_GID` as a
supplementary group, a read-only root filesystem, and dropped capabilities.
Its Docker socket mount is `:ro`, but **a read-only socket mount is not a
Docker API authorization boundary**: the adapter is a trusted socket consumer,
like Homepage itself. Keep it internal, and never expose its socket or raw
Docker inspection data to browsers. Its only archive reads are fixed version
files for WireGuard and Satisfactory; no arbitrary file paths or exec endpoints
are offered.

Service-specific icons use verified Dashboard Icons filenames where available,
including infrastructure and database backends. Custom apps and helpers without
an available logo keep descriptive Material Design icons. BookBridge uses its
own icon, Soularr/qbit-manage/cAdvisor use selfh.st assets, and both MirkLurk
cards use their existing approved branding. Games & Guides starts with RomM,
MirkLurk Wiki, and the World Viewer, followed by Skyjo and Sorry.

## Features vs Homer

- **Docker status**: Green/red indicator per service based on container state
- **Site monitoring**: HTTP ping checks on public URLs (status dot)
- **Service widgets**: Live stats from Radarr, Sonarr, Plex, qBittorrent, etc.
- **Search**: Integrated SearXNG search bar
- **Weather**: OpenMeteo weather widget (no API key needed)
