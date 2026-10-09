# Mirklurk World Viewer

<https://map.mirklurk.danteb.com> is intentionally public without Authelia.
Opening a save folder/ZIP and desktop **Live saves** remain browser-local:
**nothing uploads by default**. Under **My worlds & sync**, a browser keeps a
private synced **library** (its sync key is never shown); **Add to my worlds**
uploads only the selected character, and re-adding the same character name and
zone layout updates that world instead of copying it. A sync link/QR code joins
another of the owner's devices to the same library with full access. **Share...**
gives one world a separate read-only key derived one-way from the sync key;
**Reset link** revokes it. Followers poll every 30 seconds with ETags; opt-in
desktop live publishing sends settled snapshots, not unsaved game movement.
Links from the earlier seven-day share system no longer work. The full-screen
map, floating legend and wiki pictures are same-origin static assets. Mobile
controls and midpoint pinch zoom are included. Realistic rendering remains
default-off.

The application, Dockerfile and base nginx configuration live in
[dantebarbieri/mirklurk-map](https://github.com/dantebarbieri/mirklurk-map).
This repository owns pinned Compose services, the narrow nginx integration,
Homepage entry and operational runbook. No game binaries or user saves ship
in either image; 72 manifest-listed game-art PNGs and 282 manifest-listed
mirklurk.wiki pictures (`assets/wiki/`) are used with permission.

| Item | Value |
|---|---|
| Source (both targets) | `af0e249965c80d575a003fbc628ab291a56b1712`, merged main; [exact-source CI](https://github.com/dantebarbieri/mirklurk-map/actions/runs/37957859132) passed `test` and `docker-smoke` |
| Web | `mirklurk-map:af0e249`, target `web`, nginx non-root UID 101, private IPv4/IPv6 :8080 |
| Uploads | `mirklurk-map-uploads:af0e249`, target `uploads`, Deno non-root UID/GID **1993**, private :8081 |
| Networks | Web joins `proxy` and internal `mirklurk-map-uploads`; backend joins only the internal network with alias `uploads` |
| Storage | Named volume `compose_mirklurk-map-shares` at `/data`; Docker initializes ownership from the image, not host UID 1000 |
| Hardening | Both read-only, 16 MiB `/tmp`, cap-drop ALL, no-new-privileges; backend 768 MiB RAM, 1 CPU, 64 PIDs, unless-stopped |
| Exposure | No host ports, no router/firewall changes, no public file listing, no outbound backend network |
| Health | Each container's `/healthz`; web depends on healthy uploads |

## Privacy, limits and retention

Five worlds per library; updating a world already in it never counts. Per
network (IPv4 address or IPv6 /64): ten stored worlds, ten new worlds per
rolling 24 hours (deleted ones count; rejected uploads do not) and ten named
libraries. A world is deleted **30 days after its last update**; updates extend
it. Packages are bounded at 64 MiB / 4096 files; each world has a 30-second
update throttle and the backend allows 60 API requests/minute per network.
The single-process store limits totals to 1 GiB / 128 worlds / 2,048 named
libraries. Do not scale the backend or attach a second writer to its volume.
The 1 GiB limit is an **application admission limit**, not a filesystem quota;
allow space for one atomic replacement and metadata. Monitor Docker disk space.
Expired worlds are denied immediately and cleaned each minute/on startup.
Delete removes a world's data at once (no tombstones). The server stores only
hashes of sync/share keys and salted network hashes (`/data/salt`);
`/data/adds.json` keeps those hashes with add times for 24 hours only, so daily
quotas survive restarts. Layout: `/data/worlds/`, `/data/libraries/`,
`/data/adds.json`, `/data/salt`. On first start the af0e249 backend deletes
old seven-day share payloads (`/data/<64 hex>.bin`); they are not migrated.

**Do not back up this volume or copy its payloads for rollback.** The current
Docker root is `/var/lib/docker`; existing rclone jobs cover selected
`/srv/docker/data`, `/data/automated-backups` and media/Nextcloud, not Docker named
volumes. Wiki SQL/files snapshots cover only wiki mounts. Recheck the actual
active backup units before rollout or changing Docker's data root/backup scope.
No new backup job is appropriate: backups would break the 30-day retention
promise.

API access/error logs are disabled in both web nginx and its NPM location.
Backend Docker logging is disabled because filesystem exceptions can include
capability filenames; HTTP failures and container health remain observable.
Never paste sync/share keys into diagnostics, issue comments or shell arguments.
The CSP permits only same-origin connections (`connect-src 'self'`).

## NPM prerequisites (before enabling uploads)

Existing proxy host **70**, domain `map.mirklurk.danteb.com`, routes HTTP to
`mirklurk-map:8080` with a dedicated valid certificate. Keep caching off and
public access. Do not change unrelated proxy hosts, certificates or containers.

`nginx/mirklurk-map-npm.conf` is the complete map host **Advanced** configuration
(not a Custom Location). It disables API access/error logging and buffering,
sets the 64 MiB body bound, and rejects plain-HTTP API requests. The site is
DNS-only, so it forwards **`$realip_remote_addr`**, the actual socket peer before
NPM's broad global real-IP rewrites, rather than trusting supplied headers.
Preserve other NPM settings; the previously observed HTTP-page redirect/HSTS
discrepancy is separate from this release. Always use the HTTPS URL.

`scripts/mirklurk-map-proxy.sh --check` verifies the exact existing host through
NPM's supported REST API. `--apply` installs only this reviewed Advanced block,
using the existing `bmc-ip-monitor` credential environment. It refuses unexpected routing, extra domains,
custom locations, caching, missing TLS or unknown nonempty Advanced content.
It never prints credentials, edits the database, or patches generated files.
NPM performs its normal configuration reload; no container restart is needed.
Only run `--apply` from reviewed merged code under the shared mutation lock.
Alternatively the owner can paste the file into that host's Advanced tab.

`nginx/mirklurk-map.conf` follows the exact source nginx contract and adds only
real-IP trust plus API error-log suppression. It trusts NPM's observed
`compose_proxy` addresses **192.168.128.46** and **fd2b:92df:1a5b:1::2e**, not
the shared Docker subnet. Confirm these addresses before each deploy; if NPM
is recreated with different addresses, update/review this file before enabling
uploads. Web nginx always overwrites `X-Upload-IP` with its validated client IP.
Backend `TRUST_UPLOAD_PROXY=true` is safe only on the two-service private network.
Verify distinct real external IPs form distinct quota buckets and spoofed
`X-Forwarded-For` / `X-Real-IP` / `X-Upload-IP` cannot change them.

## Guarded release

Update both image tags, full-SHA Git contexts, revision labels, this runbook,
and the nginx contract together. Use only merged source with successful exact
CI. Normal PR checks/merge are required; a merged pin is not proof of deployment.
The daily updater also builds these pins, so complete proxy/privacy prerequisites
in an attended locked window before it can activate the backend.

1. Coordinate with every active homeserver rollout. Never advance canonical main,
   merge, build or mutate the host while another owner holds its maintenance
   window. Inspect current maintenance guards/timers; do not resume/remove another
   owner's guards or change wiki, backups, OS, router or unrelated services.
2. Record canonical SHA, running map image/container identity, other container
   IDs/start times, proxy addresses/config and backup scope. Retain the exact old
   map image under a rollback tag. Confirm Docker disk space.
3. After checks and authorized normal merge, open the **existing lock inode
   read-only** and acquire exclusive flock. Never replace/chmod it. Fast-forward
   `/srv/homeserver` to reviewed merged main only. HTTPS fetch is acceptable when
   the server account's Git SSH key cannot fetch; do not change remotes/reset.
4. Under that lock validate the **main-entry** Compose model, configure NPM,
   build both exact targets, start uploads healthy, then recreate only web.
   The explicit commands below avoid `deploy-update.sh`'s one-service interface
   and its observed service-list pipeline failure. Never use category `up`.

```bash
z /srv/homeserver/docker
# Run within the coordinated, attended window after the reviewed fast-forward:
bash -c '
  set -euo pipefail
  exec 9</run/lock/homeserver-compose.lock
  flock -x -w 30 9
  docker compose config --quiet
  sh scripts/mirklurk-map-proxy.sh --apply
  docker compose build mirklurk-map mirklurk-map-uploads
  docker compose up -d --no-deps --wait --wait-timeout 90 mirklurk-map-uploads
  docker compose up -d --no-deps --force-recreate --wait --wait-timeout 90 mirklurk-map
'
```

5. Verify exact source labels/image IDs, UID 101/1993, volume ownership,
   read-only roots, resource bounds, healthy containers, only intended network
   members and no published backend ports. Check nginx effective real-IP/log
   config, NPM health route, HTTPS IPv4/IPv6, expected sharing/mobile UI and
   exact HTML/JS/CSS/art bytes versus the pinned image, not just HTTP 200.
6. Use only a small **synthetic** save in a fresh random library: create, list,
   read data with ETag/304, read through its derived share key, reject writes via
   the share key and on the read-only view, reject a mismatched world ID, respect
   the 30-second throttle, update with `If-Match: *` (retention extended,
   creation time kept), reset the share link, delete, then verify 404 and that a
   deleted world is not re-added (412). Never upload real saves or print keys.
   Confirm other containers and all maintenance/timer state remained unchanged.

`python3 -B docker/scripts/mirklurk-map-smoke.py --family 4` (or `6`)
performs that synthetic HTTPS lifecycle without printing keys. The manually
dispatched **Verify deployed Mirklurk map sharing** workflow runs it from a
GitHub-hosted external IPv4 client, so acceptance is not limited to LAN hairpin
traffic and does not consume the owner's network quota. It never deploys and
runs only on merged main. Each run uses one of that client's ten new worlds per
rolling 24 hours even after deletion; do not run it in a loop.
Compare its capability-free health-probe peer with a separate IPv6 client's
quota bucket. LAN IPv4 hairpin requests may correctly share the router's
`192.168.50.1` NAT identity; do not mistake that for the Docker proxy identity.

## Rollback

Previous source: `8676b175bfb6020a0461a604c80b89e546059926`, tags
`mirklurk-map:8676b17` / `mirklurk-map-uploads:8676b17`. Preflight on
2026-10-09 observed exact running images
`sha256:a10d01909a670a4bf84437c0c6483a5005515d35bb5afe2a43509efd42cb0867` (web)
and `sha256:0783d3e843d95662cb8af010a12918c098782923e4d20f22043da36e833d8676`
(uploads); record again before mutation because tagged base-image rebuilds can
change it. The 8676b17 → af0e249 release replaced the upload backend's storage
format (seven-day shares → synced libraries) and added wiki art to the web
image plus its immutable-cache rule. Old seven-day payloads are deleted on the
first af0e249 start and cannot be restored. Per upstream, the 8676b17 backend
ignores the new `worlds/`, `libraries/` and `adds.json` files and starts empty,
so rolling back is a pin revert (including the nginx cache rule) plus
recreating uploads then web; rolling forward again serves the retained worlds.

To remove sharing entirely (rollback to a pre-sharing release), restore
**only** the prior web image/pin and remove its
new nginx mount, uploads dependency and backend network membership; leave
unrelated commits intact. Recreate just web under the existing lock. Keep the
NPM API log suppression even when API returns 404. Keep the private upload
backend running for expiry cleanup (still no host ports), or explicitly purge
payloads before stopping it: stopping alone would retain stored worlds beyond
their retention. Never restore old upload-volume snapshots. Remove only this
backend/volume after its retention obligation is satisfied and removal is
authorized. No wiki/database migrations or restores are involved.
