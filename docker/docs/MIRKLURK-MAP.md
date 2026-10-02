# Mirklurk World Viewer

`mirklurk-map` serves the static Mirklurk World Viewer at
<https://map.mirklurk.danteb.com>. Visitors open their own save folder and it
is read entirely in their browser. The site has no backend, database,
persistent volume, secrets, uploads, or third-party requests, and it is
intentionally public without Authelia. Optional Realistic mode loads bundled
game art from this same site; save processing stays entirely browser-local.

The application, its `Dockerfile`, and its nginx configuration live in
[dantebarbieri/mirklurk-map](https://github.com/dantebarbieri/mirklurk-map).
This repository owns only the pinned Compose service, the Homepage entry, and
this runbook. The viewer replaces the earlier seed-map idea and does not use
the `seedfinder.mirklurk.danteb.com` name mentioned in [MIRKLURK.md](MIRKLURK.md).

| Item | Value |
|---|---|
| Service / container | `mirklurk-map` in `compose.websites.yml` |
| Source commit | `8ca82beb753ff53dfc8f8b72ad2c6180279ee54e` on `main`; [CI run 37021372145](https://github.com/dantebarbieri/mirklurk-map/actions/runs/37021372145) passed `test` and `docker-smoke` |
| Image | `mirklurk-map:8ca82be`, built by Compose from the pinned Git URL |
| Runtime | `nginxinc/nginx-unprivileged:1.29-alpine`, non-root, port 8080 over IPv4 and IPv6 |
| Network | `proxy` only; no published host ports, firewall, or router rules |
| Hardening | Read-only root filesystem, 16 MiB `/tmp` tmpfs, all capabilities dropped, `no-new-privileges` |
| Health | `http://127.0.0.1:8080/healthz` returns `ok` |
| Storage and backups | None; the pinned commit and this repository fully describe the deployment |

This release adds opt-in **Live saves** with read-only directory access in
desktop Chrome/Edge over HTTPS. It follows saved positions, not unsaved player
movement, and retains the last accepted snapshot while files are being written.
**Stop live saves** or a manual import stops monitoring. It also adds saved
equipment/inventory and container/corpse/ground-loot inspection. Verified wiki
links open `mirklurk.wiki` separately; no save data is sent to the wiki. No
server-side game integration, writable storage, or CSP relaxation is needed.

The opt-in **Realistic** toggle remains **off by default**, for
terrain rendered from the visitor's saved map layers. Its 72 content-hashed
PNGs are selected game art used with the developer's permission. The static
build packages only `src/artdata.json`-listed files under `assets/game/`;
no game executables or user saves are shipped. There are no data migrations.

## Build, deploy, and update

Compose builds the image from
`https://github.com/dantebarbieri/mirklurk-map.git#<full commit SHA>`, so a
moved branch cannot change the deployed site. The daily updater's
`docker compose build --pull` rebuilds from the same commit and refreshes the
`denoland/deno:2.9.7` build image and the nginx runtime image within their
tags. A build needs GitHub (source), Docker Hub (base images), and
`registry.npmjs.org` (esbuild for `deno bundle`).

The updater stops at the first failed build, so a pin that cannot be fetched
or built blocks the whole nightly update. Keep the source repository public,
pin only commits on its `main` whose `test` and `docker-smoke` CI jobs passed,
and never rewrite pinned history.

To release a version, change the image tag (`mirklurk-map:<sha7>`), full-SHA
build context, revision label, and the source commit above in one reviewed
commit. After merging, deploy it without waiting for 04:00:

```bash
z /srv/homeserver/docker
bash -c 'exec 9</run/lock/homeserver-compose.lock; flock -x -w 30 9 && ./scripts/deploy-update.sh mirklurk-map'
```

`deploy-update.sh` pulls `main`, builds only this service, recreates it, and
waits for it to become healthy. If `main` was already pulled and it reports no
updates, rerun it with `--no-pull` inside the same lock wrapper. The wrapper
coordinates with the nightly updater; the deploy script alone does not take
that lock. Avoid manual deploys around 04:00.

Roll back by reverting the homeserver commit (or restoring the previous tag,
SHA, and label), then deploy the same way. There is no data to restore.
The previous source is `5520bd07e3158757b14cf14281bca1f6bdcf1679`, tagged
`mirklurk-map:5520bd0`; retain that image until the release is verified.
Before rollout, also record the running container's image ID: rebuilds can
refresh base images without changing the source tag.

## Nginx Proxy Manager (owner-managed)

Create the proxy host once the container is healthy. DNS already resolves
through the `*.danteb.com` CNAME, but the wildcard certificate does not cover
this two-level name, so it needs its own HTTP-01 Let's Encrypt certificate.

| Setting | Value |
|---|---|
| Domain Names | `map.mirklurk.danteb.com` |
| Scheme / Forward Hostname / Forward Port | `http` / `mirklurk-map` / `8080` |
| Cache Assets | Off: NPM's asset cache replaces the app's `immutable` and `no-cache` headers |
| Block Common Exploits | On |
| Websockets Support | Off |
| Access List | Publicly Accessible (no Authelia) |
| SSL Certificate | Request a new Let's Encrypt certificate, DNS challenge off |
| Force SSL / HTTP/2 / HSTS / HSTS Subdomains | On / On / On / Off |
| Custom locations / Advanced | None |

The app sets its own Content-Security-Policy and cache headers and omits HSTS,
which NPM adds.

## Validation

On the server:

```bash
docker compose ps mirklurk-map
docker inspect mirklurk-map --format '{{.Name}} restart={{.HostConfig.RestartPolicy.Name}} health={{.State.Health.Status}} readonly={{.HostConfig.ReadonlyRootfs}}'
docker image inspect mirklurk-map:8ca82be --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
docker exec nginxproxymanager curl -fsS http://mirklurk-map:8080/healthz
docker exec nginxproxymanager curl -fsSI http://mirklurk-map:8080/
```

Publicly, after NPM is configured, over both IPv4 and IPv6 (`curl -4`/`-6`):

- `http://` returns a 301 to `https://`, and the certificate names
  `map.mirklurk.danteb.com`.
- `/` returns 200 with no authentication redirect, the app's
  Content-Security-Policy, `Cache-Control: no-cache`, and a single HSTS header.
- The hashed `app.*.js` and `style.*.css` files return
  `public, max-age=31536000, immutable` with JavaScript and CSS content types.
  All 72 manifest-listed `assets/game/*.png` files return the same immutable
  cache policy with `image/png`. Unknown paths return 404.
- In a browser, opening a save folder renders the map with no CSP violations
  and Realistic off by default. Enabling Realistic fetches only same-origin
  bundled game art; save contents are never uploaded. Switching it off
  restores the original overview.
- Confirm the served HTML includes **Live saves...**, **Stop live saves**,
  and **Follow saved location**, and compare its hashed JS/CSS bytes with the
  pinned image, not just a successful HTTP status. In supported browsers,
  monitoring starts only after granting read-only folder access; stopping
  retains the snapshot. Saved equipment and loot remain browser-local.
