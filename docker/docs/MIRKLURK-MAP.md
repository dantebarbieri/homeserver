# Mirklurk World Viewer

`mirklurk-map` serves the static Mirklurk World Viewer at
<https://map.mirklurk.danteb.com>. Visitors open their own save folder and it
is read entirely in their browser. The site has no backend, database,
persistent volume, secrets, or outbound requests, and it is intentionally
public without Authelia.

The application, its `Dockerfile`, and its nginx configuration live in
[dantebarbieri/mirklurk-map](https://github.com/dantebarbieri/mirklurk-map).
This repository owns only the pinned Compose service, the Homepage entry, and
this runbook. The viewer replaces the earlier seed-map idea and does not use
the `seedfinder.mirklurk.danteb.com` name mentioned in [MIRKLURK.md](MIRKLURK.md).

| Item | Value |
|---|---|
| Service / container | `mirklurk-map` in `compose.websites.yml` |
| Source commit | `fb027e0c890c26f52cab88df28b815183fddd535` on `main`; CI run 36347695211 passed `test` and `docker-smoke` |
| Image | `mirklurk-map:fb027e0`, built by Compose from the pinned Git URL |
| Runtime | `nginxinc/nginx-unprivileged:1.29-alpine`, non-root, port 8080 over IPv4 and IPv6 |
| Network | `proxy` only; no published host ports, firewall, or router rules |
| Hardening | Read-only root filesystem, 16 MiB `/tmp` tmpfs, all capabilities dropped, `no-new-privileges` |
| Health | `http://127.0.0.1:8080/healthz` returns `ok` |
| Storage and backups | None; the pinned commit and this repository fully describe the deployment |

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
./scripts/deploy-update.sh mirklurk-map
```

`deploy-update.sh` pulls `main`, builds only this service, recreates it, and
waits for it to become healthy. If `main` was already pulled and it reports no
updates, rerun it with `--no-pull`. Avoid manual deploys around 04:00; they do
not take the updater's lock.

Roll back by reverting the homeserver commit (or restoring the previous tag,
SHA, and label), then deploy the same way. There is no data to restore.

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
docker image inspect mirklurk-map:fb027e0 --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
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
  Unknown paths return 404.
- In a browser, opening a save folder renders the map with no CSP violations
  and no further network requests.
