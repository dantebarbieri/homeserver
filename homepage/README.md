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
application statistics. Five additional apps use read-only aggregate statistics
below. The remaining cards, including all backends, use the shared
`&container-info` widget: **App / Build**, **Container Up**, and **Health** only
when a healthcheck is configured. State is already on the card, so it is not
repeated. Dynamic lists omit inapplicable rows and leave room for build IDs.
Do not scrape authenticated pages, disable authentication, or expose databases
over the network just to fill a card.

### Read-only application statistics

The existing internal adapter also serves five fixed `/stats/<app>` routes.
No new `.env` credentials or application admin tokens are needed. Metrics are
**instance-wide**, not scoped to the Homepage viewer's account:

| App | Metrics and scope |
|-----|-------------------|
| Aurral | Distinct available songs/albums and their album artists; album-request events retained in Aurral history from the last 30 days; active track download jobs (pending, downloading, cancellation requested). Requests are not a lifetime total or the live Lidarr request queue. Unavailable files and duplicate file formats do not inflate song counts. |
| Storyteller | Catalogue books; distinct books with non-missing audiobook assets; non-missing aligned readalouds; summed available audiobook duration, converted from seconds to hours/minutes. If any assets lack duration, a separate row says how many are excluded from that duration. |
| BookBridge | Books by sync/processing status: active, pending, processing, and failed (retry-later or permanent); unrecognized statuses appear only as an aggregate Other Status count. These are not reading/finished statuses. |
| Vaultwarden | Active login items, all active vault items, secure notes, cards, and trash. Active category counts exclude trash. Includes personal and organization items once each, across all users; never reads encrypted item names or contents. |
| ntfy | Distinct topics represented in unexpired published cached messages, cached message count, and unexpired scheduled/unpublished messages. These are **not** subscription counts, connected subscribers, or all subscribable topics: ntfy accepts arbitrary topic names, and a topic disappears from this count when its cache expires. |

The adapter has read-only directory mounts for Aurral `/config`, Storyteller and
BookBridge `/data`, ntfy's cache, and the existing `vw-data` named volume.
Directory mounts keep SQLite's live database, WAL, and SHM files together;
`immutable=1` is deliberately not used because it ignores live WAL changes.
Connections are read-only, query-only, short-lived transactions with a one-second
busy timeout. Only fixed aggregate SQL is executed. No database filenames, SQL,
filters, or file contents are accepted from HTTP callers.

**Trust boundary:** directory access necessarily allows this trusted process to
read other files in those mounts, including sensitive application data. It does
not decrypt Vaultwarden data, but read-only mounting is not field-level access
control. Keep the collector internal and keep access to Homepage appropriately
restricted for instance-wide counts. Responses contain only display labels and
aggregate counts/durations plus inventory rows, never titles, usernames,
topic names, vault contents, credentials, or raw database errors. Query/schema
failures are visible widget errors, never silently substituted zero counts.
Apps without a useful supported metric keep the simplified inventory widget.

### Container inventory

`homepage-inventory` serves a narrowly filtered JSON API on the existing internal
`homepage-widgets` network. It has no published ports, NPM host, `proxy` network,
or additional application credentials. Container routes only return display rows,
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
availability or a process's age. A container without a configured healthcheck
has **no Health row**, including when a check is explicitly disabled with `NONE`.
A stopped container with a check says **Not running** and has no live uptime;
Hytale stays disabled and is not
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
