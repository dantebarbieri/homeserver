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
application statistics. Additional apps use the aggregates below. Custom widgets
use Homepage's native **block** layout with **2-4 metric tiles**, not tall lists.
Application widgets show only application data, without build, uptime or health.
The remaining cards use the shared `&container-info` widget with just
**App / Build** and **Uptime**. Docker state/health remain on the service card.
Do not scrape authenticated pages, disable authentication, or expose databases
over the network just to fill a card.

### Read-only application statistics

The internal adapter serves fixed `/stats/<app>` routes. The setup script
generates its own restricted credentials; no application admin tokens are needed.
Metrics are
**instance-wide**, not scoped to the Homepage viewer's account:

| App | Metrics and scope |
|-----|-------------------|
| Aurral | Distinct available songs/albums and their album artists; album-request history entries from the last 30 days. Requests are not a lifetime total or the live Lidarr queue. Unavailable files and duplicate formats do not inflate song counts. |
| Storyteller | Books with non-missing audiobook assets; non-missing aligned readalouds; available audiobook duration, returned in seconds and displayed with Homepage's official Audiobookshelf duration formatter (e.g. `3d12h`). Missing Duration counts available audio assets with null duration metadata, excluded from the total; it is not a processing-job count. |
| BookBridge | Active, pending and processing books; Issues combines failed and unrecognized/null sync statuses. These are sync/processing states, not reading/finished states. |
| Vaultwarden | Active login items, all active vault items, and trash. Includes personal/organization items once each across users; never reads encrypted names or contents. |
| ntfy | Distinct topics represented in unexpired published cached messages, cached message count, and unexpired scheduled/unpublished messages. These are **not** subscription counts, connected subscribers, or all subscribable topics: ntfy accepts arbitrary topic names, and a topic disappears from this count when its cache expires. |
| ConvertX | Registered converter engines in the installed application; retained successful file-result rows; non-success results (Issues); retained job rows. History can be deleted, and one conversion can produce several file-result rows: these are not lifetime conversion totals. |
| IT-Tools | Tools and categories from the deployed frontend's registration catalog. It executes tools in the browser, so there is no server-side usage count. The catalog is parsed as data, never executed by the collector. |
| Stirling PDF | File-accepting document actions and their categories in the deployed OpenAPI schema. Excludes administrative APIs. These are API action capabilities, not unique UI-tool counts or completed conversions; no external analytics is enabled. |
| SearXNG | Enabled engines; engine request calls since the metrics process started; unweighted mean of available per-engine response-time averages. One search fans out to several engines, so calls are **not search counts** and engine latency is not end-to-end search latency. Counters reset on restart; absent timing samples display No samples, not zero milliseconds. |
| SnapOtter | Queued/running jobs; retained completed/failed jobs with completion timestamps in the last 24 hours. Uses an aggregate-only PostgreSQL view; no administrator token or job details. |
| WireGuard | Configured peers and enabled peers from `wg0.json`. Enabled does **not** imply a recent handshake; traffic/live connection data needs authenticated v14 API access. No keys, addresses or peer names leave the adapter. |
| Element / Synapse | Non-deactivated, non-guest local users; all known room records; distinct users in Synapse's daily-visit tracking during the last 24 hours. These are homeserver metrics, not Element browser sessions or message contents. |
| Authelia | Successful/failed authentication-log events in the last 24 hours, TOTP configurations, and registered WebAuthn credentials. Authentication attempts are not distinct users. No usernames, IPs, authentication secrets or log records are returned. |

Hytale remains disabled. Satisfactory's server denies passwordless client login;
without a client credential it keeps its compact build/uptime fallback rather
than reporting invented player counts. No game server is restarted by this work.

Before the first expanded-widget deployment, run
`docker build -t homepage-inventory:latest docker/dockerfiles/homepage-inventory`, then
`bash docker/scripts/setup-homepage-widgets.sh` from the repository root (or pass
the candidate image tag as its first argument). It preserves existing `.env`
values and SearXNG YAML comments, adds generated `HOMEPAGE_WIDGET_DB_PASSWORD`
and `HOMEPAGE_SEARXNG_METRICS_PASSWORD`, and configures views in the three databases.
It preserves an existing SearXNG metrics password and refuses to enable metrics
if collection was explicitly disabled. Only access to already-collected local
engine metrics is enabled, using password-protected `/metrics`; no search text
or new usage analytics is recorded. Recreate SearXNG to load that password.

The `homepage_widget` PostgreSQL identity can select only the single aggregate
view in each database. It has no base-table privileges, schema creation rights,
superuser capabilities, or role inheritance, and defaults to read-only
transactions with a two-second statement timeout. The runtime explicitly uses
read-only transactions too. The setup refuses to overwrite unrelated roles or
schemas with that name. Application accounts/credentials are unchanged.
The main collector joins the existing `matrix` and `authelia` networks to reach
those views. SnapOtter's embedded PostgreSQL remains **loopback-only**:
`snapotter-widget` shares its network namespace and serves only aggregates on
port 8089, with no host port or proxy host. Recreate the companion with SnapOtter
when its network namespace changes; Compose's dependency restart wiring covers
explicit Compose updates.

The adapter has read-only directory mounts for Aurral `/config`, Storyteller and
BookBridge `/data`, ConvertX `/app/data`, ntfy's cache, and the existing `vw-data` named volume.
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
aggregate counts/durations or two fallback values, never titles, usernames,
topic names, vault contents, credentials, or raw database errors. Query/schema
failures are visible widget errors, never silently substituted zero counts.
Apps without a useful supported metric keep the simplified inventory widget.

### Container inventory

`homepage-inventory` serves a narrowly filtered JSON API on the existing internal
`homepage-widgets` network. It has no published ports, NPM host, or `proxy` network.
Container routes only return `version` and `uptime`,
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
availability or a process's age. No widget repeats Docker state or health.
A stopped container has no live uptime; Hytale stays disabled.
Missing containers and Docker/version-source failures
are visible widget errors, not invented healthy or zero-valued responses.
Widgets refresh every 30 seconds; successful inventory results are cached for
10 seconds, without serving stale data after a failed refresh.

The adapter runs as the unprivileged `node` user with `DOCKER_GID` as a
supplementary group, a read-only root filesystem, and dropped capabilities.
Its Docker socket mount is `:ro`, but **a read-only socket mount is not a
Docker API authorization boundary**: the adapter is a trusted socket consumer,
like Homepage itself. Keep it internal, and never expose its socket or raw
Docker inspection data to browsers. Archive reads are fixed version files for
WireGuard/Satisfactory, the filtered WireGuard peer configuration, and ConvertX's
converter registry; no arbitrary file paths or exec endpoints
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
