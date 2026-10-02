# Mirklurk World Viewer

<https://map.mirklurk.danteb.com> is intentionally public without Authelia.
Opening a save folder/ZIP and desktop **Live saves** remain browser-local:
**nothing uploads by default**. Explicit sharing uploads one selected character,
provides a private read-capability link, and keeps a separate owner key on the
creating device for replacement/deletion. The browser remembers its links
locally. Read-only visitors poll every 30 seconds with ETags; opt-in desktop live
publishing sends settled snapshots, not unsaved game movement. Mobile controls
and midpoint pinch zoom are included. Realistic rendering remains default-off.

The application, Dockerfile and base nginx configuration live in
[dantebarbieri/mirklurk-map](https://github.com/dantebarbieri/mirklurk-map).
This repository owns pinned Compose services, the narrow nginx integration,
Homepage entry and operational runbook. No game binaries or user saves ship
in either image; 72 manifest-listed game-art PNGs are used with permission.

| Item | Value |
|---|---|
| Source (both targets) | `77b12638469682856c92ce9bed704ad3a6004f6f`, merged main; [exact-source CI](https://github.com/dantebarbieri/mirklurk-map/actions/runs/37031494818) passed `test` and `docker-smoke` |
| Web | `mirklurk-map:77b1263`, target `web`, nginx non-root UID 101, private IPv4/IPv6 :8080 |
| Uploads | `mirklurk-map-uploads:77b1263`, target `uploads`, Deno non-root UID/GID **1993**, private :8081 |
| Networks | Web joins `proxy` and internal `mirklurk-map-uploads`; backend joins only the internal network with alias `uploads` |
| Storage | Named volume `compose_mirklurk-map-shares` at `/data`; Docker initializes ownership from the image, not host UID 1000 |
| Hardening | Both read-only, 16 MiB `/tmp`, cap-drop ALL, no-new-privileges; backend 768 MiB RAM, 1 CPU, 64 PIDs, unless-stopped |
| Exposure | No host ports, no router/firewall changes, no public file listing, no outbound backend network |
| Health | Each container's `/healthz`; web depends on healthy uploads |

## Privacy, limits and retention

Three active saves per IP (IPv6 /64 bucket); six creations per rolling day,
including deletions; fixed seven-day expiry that updates never extend.
Packages are bounded at 64 MiB / 4096 files; updates have a 30-second throttle.
The single-process store limits total active payloads to 1 GiB / 128 saves.
Do not scale the backend or attach a second writer to its volume. The 1 GiB
limit is an **application admission limit**, not a filesystem quota; allow space
for one atomic replacement, metadata and tombstones. Monitor Docker disk space.
Expired payloads are denied immediately and cleaned each minute/on startup.
Deletion atomically replaces payloads with a quota tombstone until expiry.

**Do not back up this volume or copy its payloads for rollback.** The current
Docker root is `/var/lib/docker`; existing rclone jobs cover selected
`/srv/docker/data`, `/data/automated-backups` and media/Nextcloud, not Docker named
volumes. Wiki SQL/files snapshots cover only wiki mounts. Recheck the actual
active backup units before rollout or changing Docker's data root/backup scope.
No new backup job is appropriate for explicitly temporary saves.

API access/error logs are disabled in both web nginx and its NPM location.
Backend Docker logging is disabled because filesystem exceptions can include
capability filenames; HTTP failures and container health remain observable.
Never paste read/owner keys into diagnostics, issue comments or shell arguments.
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
using the existing `bmc-ip-monitor` credential environment (same method as
`configure-recipe-app-proxies.sh`). It refuses unexpected routing, extra domains,
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
6. Use only a small **synthetic** save: create, retrieve metadata/data read-only,
   verify ETag/304, reject anonymous PUT/DELETE, respect 30-second update
   throttle, update with owner key without extending expiry, delete with owner
   key, then verify 404. Check that the specific test payload is gone and
   capability keys never reached proxy/container logs. Do not upload real saves.
   Confirm other containers and all maintenance/timer state remained unchanged.

`python3 -B docker/scripts/mirklurk-map-smoke.py --family 4` (or `6`)
performs the synthetic HTTPS lifecycle without printing tokens. The manually
dispatched **Verify deployed Mirklurk map sharing** workflow runs it from a
GitHub-hosted external IPv4 client, so acceptance is not limited to LAN hairpin
traffic. It never deploys and runs only on merged main. Each run uses one of
that client's six daily creations even after deletion; do not run it in a loop.
Compare its capability-free health-probe peer with a separate IPv6 client's
quota bucket. LAN IPv4 hairpin requests may correctly share the router's
`192.168.50.1` NAT identity; do not mistake that for the Docker proxy identity.

## Rollback

Previous source: `8ca82beb753ff53dfc8f8b72ad2c6180279ee54e`, tag
`mirklurk-map:8ca82be`. Preflight on 2026-10-02 observed exact running image
`sha256:c265cd7d7bb849df76409f6a6de415906c33251d32d586271c4e3a29f7d47443`;
record again before mutation because tagged base-image rebuilds can change it.

For reviewed rollback, restore **only** the prior web image/pin and remove its
new nginx mount, uploads dependency and backend network membership; leave
unrelated commits intact. Recreate just web under the existing lock. Keep the
NPM API log suppression even when API returns 404. Keep the private upload
backend running for expiry cleanup (still no host ports), or explicitly purge
payloads before stopping it: stopping alone would retain temporary saves beyond
their expiry. Never restore old upload-volume snapshots. Remove only this
backend/volume after its retention obligation is satisfied and removal is
authorized. No wiki/database migrations or restores are involved.
