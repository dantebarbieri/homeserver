# Homepage Dashboard Config

Configuration files for [Homepage](https://gethomepage.dev/) — a self-hosted dashboard
with Docker integration and service status monitoring.

Replaces the previous [Homer](https://github.com/bastienwirtz/homer) dashboard.

## Files

| File | Purpose |
|------|---------|
| `settings.yaml` | Global theme, layout, and search settings |
| `services.yaml` | All services with Docker status + siteMonitor health checks |
| `bookmarks.yaml` | External links (GitHub repos) and local management pages |
| `widgets.yaml` | Top-level page widgets (date/time, weather) |
| `docker.yaml` | Docker socket connection for container status |

## Deployment

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

See the [Homepage widget docs](https://gethomepage.dev/widgets/services/) for
details on each service's widget configuration.

## Features vs Homer

- **Docker status**: Green/red indicator per service based on container state
- **Site monitoring**: HTTP ping checks on public URLs (status dot)
- **Service widgets**: Live stats from Radarr, Sonarr, Plex, qBittorrent, etc.
- **Search**: Integrated SearXNG search bar
- **Weather**: OpenMeteo weather widget (no API key needed)
