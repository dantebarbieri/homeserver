# CLAUDE.md

This file provides guidance to Claude Code when working with the `homepage/` directory.

## Key Files

- `services.yaml` — Main service catalogue. All dashboard entries with Docker status, health checks, and API widgets.
- `settings.yaml` — Theme, layout, search provider, per-group column/icon config.
- `widgets.yaml` — Top-of-page widgets (datetime, weather).
- `bookmarks.yaml` — External links organized by category (GitHub repos, management UIs).
- `docker.yaml` — Docker socket mapping (`my-docker` → `/var/run/docker.sock`).
- `WIDGET_API_KEYS.md` — Step-by-step guide for obtaining every service's API credentials.

## Adding a Service to `services.yaml`

```yaml
- Service Name:
    icon: servicename.svg              # or mdi-icon-name for Material Design
    href: https://service.danteb.com
    description: One-line description
    siteMonitor: https://service.danteb.com
    server: my-docker
    container: container-name
    widget:
      type: servicetype
      url: http://container-name:port  # internal Docker network URL
      key: "{{HOMEPAGE_VAR_SERVICE_KEY}}"
```

### Checklist

1. List the service once in the appropriate Apps, Manage, or Backends category (see `README.md`).
2. For web interfaces, use `https://service.danteb.com` for public `href` and `siteMonitor` — the subdomain should match the NPM proxy host (see [Subdomain Naming Convention](../CLAUDE.md#subdomain-naming-convention) in the root CLAUDE.md). For backends, normally omit both fields and describe which apps they power; do not expose private APIs just for the dashboard.
3. Use `http://container-name:port` for widget `url` (internal Docker network)
4. `server` is always `my-docker`
5. `container` must match the Docker container name exactly
6. Add the corresponding `HOMEPAGE_VAR_*` to **three places**: `docker/sample.env`, the server's `.env`, **and** the `environment:` block in `docker/compose.dashboards.yml` (Homepage only sees env vars explicitly listed there — `.env` alone is not enough)
7. Document how to obtain the API key in `WIDGET_API_KEYS.md`
8. Add the category to `settings.yaml` `layout` if it's new, including an explicit `tab` so it does not repeat on every tab. Service and bookmark groups must have distinct names.
9. Custom widgets must use native `display: block` metric tiles with **2-4 entries**, never tall list/dynamic-list layouts. App-specific cards show only application data; do not append version/uptime/health. Fallbacks use `widget: { <<: *container-info, url: http://homepage-inventory:8080/containers/<container-name> }` for just build and uptime. The anchor is defined inside Aurral's widget merge; keep it before aliases and explicitly supply every URL. See `README.md` for fixed aggregate routes, PostgreSQL provisioning, source semantics and trust boundaries. New sources require regression coverage; never hardcode dashboard counts.

## Environment Variable Convention

Widget credentials use `{{HOMEPAGE_VAR_*}}` interpolation at container runtime:

| Pattern | Example |
|---------|---------|
| API key | `{{HOMEPAGE_VAR_RADARR_KEY}}` |
| Username | `{{HOMEPAGE_VAR_QBIT_USER}}` |
| Password | `{{HOMEPAGE_VAR_QBIT_PASS}}` |

These are set as Docker environment variables in `docker/compose.dashboards.yml` and defined in `docker/.env`.

## Icon Systems

- **SVG icons**: Service-specific (e.g., `plex.svg`, `radarr.svg`) — from [Dashboard Icons](https://dashboardicons.com/icons). **Search the icon catalog at https://dashboardicons.com/icons** to find the exact filename (including light/dark variants like `matrix-light.svg`, `openclaw-dark.svg`). This is much more efficient than browsing the GitHub repo directly. Note that filenames sometimes contain typos (e.g., `litlellm.svg` for LiteLLM) — use whatever the catalog shows.
- **Material Design Icons**: For group headers and fallbacks (e.g., `mdi-multimedia`)
- **Simple Icons**: For bookmarks (e.g., `si-github`)

## Service Categories

Groups are defined in `settings.yaml` under `layout`. Each has `tab`, `style`,
`columns`, and `icon`. Tabs are Apps (default), Manage, and Backends; the complete
category list and placement rules are documented in `README.md`. Apps and Manage
use three-column rows, Backends uses four-column rows, and Databases & Caches is
initially collapsed. Search is an info widget in `widgets.yaml`.
