# MirkMap · Mirklurk World Viewer

<https://map.mirklurk.danteb.com> (**MirkMap**) is intentionally public without Authelia.
Opening a save folder/ZIP and desktop **Live saves** remain browser-local:
**nothing uploads by default**. Under **My worlds & sync**, a browser keeps a
private synced **library** (its sync key is never shown); **Add to my worlds**
uploads only the selected character, and re-adding the same character name and
zone layout updates that world instead of copying it. A sync link/QR code joins
another of the owner's devices to the same library with full access; so does a
**one-time sync code** (8 characters, single use, 10 minutes), the way into a
Home Screen app with its own storage. The browser encrypts the sync key with a
key derived from the code; the server holds only that ciphertext, in memory,
under the code's SHA-256 hash, and never sees the code or key. **Share...**
gives one world a separate read-only key derived one-way from the sync key;
**Reset link** revokes it. Followers poll every 30 seconds with ETags; opt-in
desktop live publishing sends settled snapshots, not unsaved game movement.
Links from the earlier seven-day share system no longer work. The full-screen
map, floating legend and wiki pictures are same-origin static assets. Mobile
controls and midpoint pinch zoom are included. Realistic rendering remains
default-off. Inspecting a creature or NPC shows its saved hit-point grid
(armor shields; burned, lost, poison and bleed), attack pattern with a
damage-class badge and a Melee/Ranged toggle; merchants list wares and prices.
The clickable player marker shows hit points, armor to distribute, wellbeing,
stats, conditions and inventory (equipped badges, True/Minimum coins). These
panels read only the locally opened save or a synced world already loaded.
A touch tap that misses every small marker picks the nearest one within 22 px.
On a narrow full-screen map (a phone held upright) details open in a draggable
bottom sheet and the map glides to keep the marker in sight; Back closes an
open card or sheet before leaving full screen (client-side history only).
Map markers show a pointer cursor. The map also has gatherables layers,
creature icons and the saved time and weather; a **C** (Cheated) or **S**
(From Share) badge follows a world's name; and **Download** builds a playable
world ZIP in the browser from the existing data endpoints. The **Save editor**
at `/edit/` (linked from the map) changes a character's save files locally
through the File System Access API (desktop Chrome/Edge) and uploads nothing;
saving any edit writes a permanent Cheated mark (a `cheated` entry in
MirkMap's notes file `MirkMap.json` beside `Player.save`). Since 0a38974 that
file is JSON (`fromShare`, `shareDownloaded`, `cheated: {since, edits}`)
rather than `MirkMap.ini`, because Chrome/Edge on Windows refuse `.ini` names
in that API and could not save at all. The editor has an **Editor** /
**Full map** switch (MirkMap's own map of the save with unsaved edits; move
yourself from it), per-change **Undo**, and a list of worn and carried items
with **Remove**; the editor and the map's sharing panel ask in in-page
dialogs instead of the browser's `confirm()`. Since 911dc35 the editor also
equips items by the game's slot rules: **Wear it** puts a new item on in a free
equipment slot (so a character with no bag can put on a backpack), worn items
have **Take off** (into the other bags) and carried items that fit a free slot
have **Wear**. Since 006f096 the map, editor and upload server read a bag kept
inside another bag the way the game loads it (below), so such saves open
instead of failing with "Invalid inventory cell"; the editor's items get a
**Move to…** menu (between worn containers, only where an item fits, upright
or turned sideways), worn containers show their size and free cells, and
adding an item can turn it sideways. Since a70f513 the editor (in edit mode)
has **Reload save**, so the page can stay open while the owner plays: after
saving and quitting to the game's menu it rereads the save folder and replays
the unsaved changes on the newest save, dropping (and naming) any that now do
nothing or no longer apply; stats/wellbeing and time/weather edits write only
the values changed. This is browser-only; nothing new is uploaded.
Since d2ad2d4 **Where you stand** no longer refuses water: moving onto water
or off a raft asks first, giving the water's depth, and offers to bring your
raft, make one there, go without, leave it, or dock it at that shore (written
to the zone's `Stations.save` as a finished raft, station 171). Every carryable
item can be added (Campfire, Raft Base, quest items, seeds); spawned creatures
go only on tiles the game lets them live on; and the map gains a **Rafts**
layer (under Items) with raft symbols, whose inspection shows the game's raft
picture from the already-bundled `spr_placed_16x16_wider` strip. The parsed
`Player.save` gains an `onRaft` flag (`ensureRaft`); nothing new is uploaded.
MirkMap is installable (web app manifest,
service worker): after the first visit it keeps the page, the save editor's
page, scripts, stylesheets, manifest, icons and all bundled art (367 files) so
local saves open offline.
It never caches `/api/`; pages are fetched network-first (up to 3 seconds) so
an online visit gets the newest release.

The application, Dockerfile and base nginx configuration live in
[dantebarbieri/mirklurk-map](https://github.com/dantebarbieri/mirklurk-map).
This repository owns pinned Compose services, the narrow nginx integration,
Homepage entry and operational runbook. No game binaries or user saves ship
in either image; 72 manifest-listed game-art PNGs and 282 manifest-listed
mirklurk.wiki pictures (`assets/wiki/`) are used with permission, as are the
six MirkMap icons drawn from the game's "Map of area" item. The web image also
serves `/manifest.webmanifest` (as `application/manifest+json`), `/sw.js` and
`/icons/`; like `index.html` they revalidate (`no-cache`). The editor page
`/edit/` (`/edit` too, via the existing `try_files`) uses `<base href="../">`
to load its hashed `edit.*.js` / `editor.*.css` from the site root; they are
cached immutable like `app.*.js` / `style.*.css`.

| Item | Value |
|---|---|
| Source (both targets) | `d2ad2d4d57530b68ec1e754c81a4d172aca9d9fe`, merged main; [exact-source CI](https://github.com/dantebarbieri/mirklurk-map/actions/runs/38291758838) passed `test` and `docker-smoke` |
| Web | `mirklurk-map:d2ad2d4`, target `web`, nginx non-root UID 101, private IPv4/IPv6 :8080 |
| Uploads | `mirklurk-map-uploads:d2ad2d4`, target `uploads`, Deno non-root UID/GID **1993**, private :8081 |
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
`/data/adds.json`, `/data/cheated.json`, `/data/salt`. On startup the backend
(since af0e249) deletes old seven-day share payloads (`/data/<64 hex>.bin`);
they are not migrated.

Since 800f34a, the first upload of a library world whose package carries the
Cheated mark adds its record key (a hash of the library hash and world ID) to
`/data/cheated.json`, a JSON array kept for good, outside the 30-day retention,
so the mark outlives deletion and expiry. World records may carry `fromShare` /
`cheated` flags, returned in WorldInfo only when true. A later upload of a
listed world without the mark is repacked with it before storing
(413 if that exceeds 64 MiB). Startup tolerates a missing `cheated.json` and
removes a stray `cheated.json.tmp`; invalid content stops the backend starting.
Since 0a38974 the mark and `fromShare` are read from the package's
`MirkMap.json` (a `cheated` entry; `"fromShare": true`), the repack writes
`MirkMap.json`, and package validation accepts `MirkMap.json` besides
`.save`, `.tmap`, `.png` and `.ini`. An old `MirkMap.ini` no longer counts;
existing records keep their stored flags, and a world's `fromShare` is re-read
on its next upload. No migration. API routes, quotas, `/api/config`, record
fields and the sharing format are otherwise unchanged.

Since 006f096 the upload server's `Player.save` validation (it parses
equipment inventories with the map's shared inventory reader) follows the
game's loader (`item_recreate_grid`, 0.8.1.5): a `null` inventory cell counts
as empty, and a container kept inside another container's grid is read as
empty without parsing its own stale saved grid. Saves like that, previously
rejected with 400 "Invalid inventory cell", are accepted; genuinely malformed
cells are still rejected. API routes, quotas, `/api/config` and stored formats
are unchanged; no migration.

One-time sync codes (since d30a806: `POST`/`DELETE /api/library/pair` with the
sync key, `POST /api/pair` to claim once) live only in backend memory and are
never written to `/data`. A library has one open code (a new one replaces it);
limits are ten open codes per network, 1,024 in total and 20 wrong or reused
codes per network per hour. Codes expire after 10 minutes and a restart or
recreate forgets them; users simply make a new one.

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
The CSP permits only same-origin connections (`connect-src 'self'`) and
same-origin manifests and service workers (`manifest-src`/`worker-src 'self'`).
`base-uri 'self'` (since 800f34a; previously `'none'`, under which browsers
ignore `/edit/`'s `<base href="../">` and the editor loads unstyled and without
its script) still refuses a base URL on any other origin.

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
   Check the CSP (`base-uri 'self'`), `/manifest.webmanifest` content type,
   `/sw.js` `no-cache`, that `/edit/` serves the editor page with
   `<base href="../">` and immutable `edit.*.js` / `editor.*.css` of the right
   types, and that `POST /api/library/pair` without a key returns 401.
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

Previous source: `a70f5135cf9afe3ca9490a17e0cc365f6141e448`, tags
`mirklurk-map:a70f513` / `mirklurk-map-uploads:a70f513`. Preflight on
2026-10-12 observed exact running images
`sha256:27e83d743dcbb4148b6bda04424f7e4ade30aff1f571a925d6f92c0df4968993` (web)
and `sha256:120045f3859362305baafa08b745c30f9491e0fffb75859a6835c7d6466809c3`
(uploads); record again before mutation because tagged base-image rebuilds can
change it. The a70f513 → d2ad2d4 release is frontend: it changes `edit.html`,
`style.css`, `src/editor/`, `src/dialog.ts`, `src/inspect.ts`,
`src/itemdata.ts`, `src/mapview.ts`, `src/objects.ts`, `src/save.ts`,
`src/view.ts`, `tools/itemdata.ts`, tests and the README (water and raft
moves, every carryable item, creatures only where they live, the Rafts layer,
above). `server/`, the Dockerfile, `.dockerignore`, source `deploy/nginx.conf`,
compose, the sharing code, `assets/` and `tools/smoke.sh` are unchanged
(`nginx/mirklurk-map.conf` changed only its source-SHA comment; the service
worker still keeps 367 files). Of what the upload server imports only
`src/save.ts` changed, additively (`parsePlayer` also reads `ensureRaft` into
`onRaft`), so the uploads image changes but no API route, quota,
`/api/config`, validation outcome or stored format does. Rolling back to
a70f513 is a pin revert plus recreating uploads then web; no migration, data
or proxy change is involved and no data is lost. The editor again refuses to
move you into water, rafts are neither brought, made, left nor docked, the
non-lootable items and creature habitat checks disappear, and the map loses
its Rafts layer. Edits already saved to local game files are unaffected.

Rolling back further to `006f096ca20d755d8364e284f7292818548f1042`
(`mirklurk-map:006f096` / `mirklurk-map-uploads:006f096`, observed
`sha256:8a7efa4afe823a45efc745c1ba3a2d1e9bea2c9effa7089e17bac86cd6d46f93` /
`sha256:5edbf80ddaece62fbfcef5919c378d6b94a4e23dc4035c287af4e4ec1e5851ff` on
2026-10-12) also removes the a70f513 release, which was frontend only: it
changed `edit.html`, `src/editor/`, tests and the README (the editor's Reload
save, above). `server/`, the Dockerfile, `.dockerignore`, source
`deploy/nginx.conf`, compose, the sharing code, `assets/` and `tools/smoke.sh`
were unchanged, and nothing the upload server imports changed
(`nginx/mirklurk-map.conf` changed only its source-SHA comment; the service
worker kept 367 files). It is a pin revert plus recreating uploads then web;
the API and stored formats are the same, so no migration, data or proxy change
is involved. The editor's Reload save also disappears (and stats/time edits
again write every value of their group).

Rolling back further to `911dc35077b8ff3e0e2e7cc30fa4d622395d475f`
(`mirklurk-map:911dc35` / `mirklurk-map-uploads:911dc35`, observed
`sha256:6bbad9fa2f3f0491cfeb9c0947af26881f7b35755a3c56b5702f9cf22367ca0b` /
`sha256:9d7a52ee25e7a20a5af2ab05545eac969dca993147c7ab3c71526bb291638236` on
2026-10-12) also removes the 006f096 release, which changed `src/inventory.ts`
(the shared inventory reader, above), `src/editor/`, `editor.css`, tests and
the README. `server/`, the Dockerfile, `.dockerignore`, source
`deploy/nginx.conf`, compose, the sharing code, `assets/` and `tools/smoke.sh`
were unchanged (`nginx/mirklurk-map.conf` changed only its source-SHA comment;
the service worker kept 367 files), but the uploads image did change behavior:
`unpackSave` validates `Player.save` with that reader. It is a pin revert plus
recreating uploads then web; the API and stored formats are the same, so no
migration, data or proxy change is involved, and no data is lost. The 911dc35
images (and clients loaded from them) again reject `Player.save` files with a
stale grid inside a nested container: uploading one returns 400, and a world
stored with one since 006f096 does not open in a rolled-back client until it
is uploaded again or after rolling forward. The editor's Move to…, container
sizes and sideways adding disappear.

Rolling back further to `0a38974793b401368804626cd8b801575ad2c0cb`
(`mirklurk-map:0a38974` / `mirklurk-map-uploads:0a38974`, observed
`sha256:b1ee5a914038cd3da742a53c937be953ada989f647b001d5ed5419bad952b484` /
`sha256:f1a8107546faf69897993763ae4a616a6aa656d103db723fe9bb10dddca6cc1a` on
2026-10-12) also removes the 911dc35 release, which was frontend only: it
changed `src/editor/`, `editor.css`, tests and the README (the save editor's
equipping, above); `server/`, the Dockerfile, `.dockerignore`, source
`deploy/nginx.conf`, the sharing code, `assets/` and `tools/smoke.sh` were
unchanged (`nginx/mirklurk-map.conf` changed only its source-SHA comment; the
service worker kept 367 files). It is a pin revert plus recreating uploads then
web; the API and stored formats are the same, so no migration, data or proxy
change is involved. The editor's Wear it / Wear / Take off also disappear.

Rolling back further to `800f34a8f054ec0d0e092104ced20aaa0fd48946`
(`mirklurk-map:800f34a` / `mirklurk-map-uploads:800f34a`, observed
`sha256:0ed5a76acc1ab12e683b0acd19a2e26f745714e610cc322333594478487e5247` /
`sha256:91b8bda1c2b068421907924a43827bef9757524db4b1cbc47f45b23cd9c28db3` on
2026-10-12) also removes the 0a38974 release, which changed only application
code (the Dockerfile, `.dockerignore`, source `deploy/nginx.conf`, `assets/`
and `tools/smoke.sh` were unchanged; `nginx/mirklurk-map.conf` changed only its
source-SHA comment; the service worker kept 367 files). That release moved
MirkMap's notes from `MirkMap.ini` to `MirkMap.json` (above) and added the
editor's Full map, per-change Undo, item removal and in-page dialogs. It is a
pin revert plus recreating uploads then web; no migration, data or proxy
change is involved. The 800f34a backend accepts the
same record fields and keeps `cheated.json`, but every release before 0a38974
rejects packages containing `MirkMap.json` ("Invalid save file entry"): a world
stored since 0a38974 with that file (marked by the editor, repacked with
the mark, or a downloaded share added again) does not open in the rolled-back
map until it is uploaded again from the rolled-back page (whose packer skips
`MirkMap.json`; a listed world is re-marked with `MirkMap.ini`) or after rolling
forward. Nothing is deleted. The rolled-back editor again cannot save on
Windows Chrome/Edge.

Rolling back further to `d30a80686165d45fbe129f574ba8f04063180e7f`
(`mirklurk-map:d30a806` / `mirklurk-map-uploads:d30a806`, observed
`sha256:4aba2142a23af6c3874af7ecd3629d2b9df8ab50da26d8cf46bdf2a78cda4cfa` /
`sha256:5886b38218d8baa2f4e2079e489dc60102d670537bbe2d9df29f69cdfd62d659` on
2026-10-11) also removes the 800f34a release: the save editor (the
Dockerfile/`.dockerignore` copy `edit.html` and `editor.css`; the
service worker kept 364 files before it; `assets/` is unchanged), the map's
C/S badges, gatherables, creature icons, time and weather and world ZIP
downloads, the additive `cheated.json` / record-flag handling in `server/`
(above) and two nginx contract changes (`edit`/`editor` hashed assets
immutable; CSP `base-uri 'self'`). It is a pin revert that
includes `nginx/mirklurk-map.conf`, plus recreating uploads then web; no
migration, data or proxy change is involved. The d30a806 backend ignores the
extra record fields and `cheated.json` (which stays in the volume); a world it
rewrites loses the record flags and a package without the mark is not
re-marked, but after rolling forward again `cheated.json` restores the mark on
that world's next upload. `/edit/` is gone while rolled back.

Rolling back to `b16fbb1` (`mirklurk-map:b16fbb1` /
`mirklurk-map-uploads:b16fbb1`, observed
`sha256:58eea02db725d27e000964535b32bd81662f22bb55278625aff97a5879d5d1fe` /
`sha256:18f8d788bbfe1dbdd23ef032f98f40f754e721f3d916767f4ed0517ce20b2561` on
2026-10-10) also removes the MirkMap rebrand, the PWA files (manifest,
service worker, icons), the in-memory sync-code endpoints and that release's
nginx contract changes (CSP `manifest-src`/`worker-src 'self'`; the manifest
content type). Existing API routes, quotas, `/api/config`, the sharing format
and `assets/` are unchanged across both releases. It is likewise a pin revert
including `nginx/mirklurk-map.conf`, plus recreating uploads then web; open sync
codes are dropped (as on any restart). Browsers that installed the app keep its
service worker, but pages load network-first, so online visits get the
rolled-back page and its assets. The same holds back to `af0e249`
(`mirklurk-map:6e8929b` / `:af0e249` and their `mirklurk-map-uploads` tags are
retained), whose releases changed only the frontend.

Rolling back further to `8676b17` crosses the storage-format change
(seven-day shares → synced libraries) and the wiki-art immutable-cache rule.
Per upstream, the 8676b17 backend ignores the `worlds/`, `libraries/` and
`adds.json` files and starts empty, so that is a pin revert (including the
nginx cache rule) plus recreating uploads then web; rolling forward again
serves the retained worlds. Deleted seven-day payloads cannot be restored.

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
