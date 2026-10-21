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
through the File System Access API (desktop Chrome/Edge) and uploads nothing
unless the owner saves to My worlds (since f7257fc, below);
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
Since f7257fc the map's crosshair button (under **World**) locates the
character, opening the interior or zone they are in; neighbouring zones also
draw their ground overlays, and a zoomed-out survey hides the zone outline.
Inventories show each item's condition as the game's tooltip does (durability
out of its maximum, _Portions left_, _Oil left_, a torch's or lantern's fuel,
wetness), and a **Journal** (under the map, in the player inspection and in
the editor) rebuilds the journal from the saved main-quest stage in the game's
own words, linking its people and places to the map. The editor adds
**Repair all** / **Refuel all** / **Dry all** and a per-item **Condition…**,
sets poison, bleeding and stun on picked hit points, edits sickness and the
warm/fed/rested/stamina-boost timers (`Player.save` also parses `fedTime` and
`staminaBoostTime`), and moves you inside caves, ruin cellars, quest rooms and
Scaal's depths. The map and the editor now share one opened save: **Save
editor** / **Back to MirkMap** hand it over (a Live saves folder handle kept in
this browser's IndexedDB `mirkmap-open`, a My worlds world, or a copy of the
character's files). The editor can open and save **My worlds** library worlds
through the existing `GET /api/library` and `GET`/`PUT
/api/library/worlds/:id[/data]` routes (one upload of the whole character, the
usual 30-second throttle) or download an edited ZIP, so editing no longer needs
the File System Access API. Shared packages are now gzip-compressed (sharing
limits, below).
Since a4220ad the character preview becomes directly editable after entering
edit mode: vital bars, hit points and conditions apply immediately, with
undo rather than a separate Apply button. Repeated edits to the same control
replace the pending change. Malformed saved object lists now produce a
warning instead of silently disappearing; an unreadable creature or station
list disables movement and creature changes only in that area, identifies
the file and preserves pending edits. Reader/editor equipment-copy detection
and armor durability metadata are shared, along with numeric, formatting,
hashing and build helpers; development path validation and the map timer are
also corrected. Library updates with a stale exact ETag, or any supplied
`If-Match` for a deleted world, return 412 before the update throttle is
considered. Nothing new is uploaded automatically.
Since a4671a4 MirkMap and the save editor also know Mirklurk 0.8.9.9, the
Steam beta (`next_version_tester`): its new beings, items and merchants, the
Survivors' camp (Wilda and Grand Mother's hut), the Magus realm and its rule changes,
with regenerated game data and art. Each save's `VERSION` (in `Player.save`)
picks the rules, and a **Latest** / **Beta** switch shows 0.8.1.5's or
0.8.9.9's instead; the editor refuses to write items or creatures the chosen
version lacks. This is browser code and art; the upload server only reads the
new 0.8.9.9 keys additively, and nothing new is uploaded.
Since 407e030 The Terror (being 40) has its own `terror` creature icon instead
of the Mirkfangs' bat, and Magus Clay's `magus` icon is redrawn from his sprite
as a hooded robe with folded arms and no staff. This is browser code only.
Since a83056c a later unsaved change in the save editor drops earlier changes
it leaves with nothing to do, and names them on its card: setting a field
again, or **Heal all wounds** after poisoning hit points, keeps one change
where there were several (and none when it only puts back what the save had).
This is editor code only; nothing new is uploaded.
Since 5ce1c5f the bundled mirklurk.wiki pictures are refreshed for 0.8.9.9:
24 new pictures (items 171, 258-262 and 264-275; beings 36-41) with
regenerated wiki art and data, and Magus Clay in his realm (being 41) shows
his own picture and links to the wiki page `Magus Clay (boss)`. This is
browser code and art only; nothing new is uploaded.
Since 3fb50b1 Mirklurk 0.9.0.0, the full release of the 0.8.9.9 beta, is
**Latest** (with 0.8.9.9's rules; Steam no longer has a beta), and the Beta
switch is hidden: the version switch shows only for a save whose version's
rules differ from Latest's (an 0.8.1.5 save). The art data's version stamp
reads 0.9.0.0; no art changes. This is browser code only; nothing new is
uploaded.
Since a38013f the wiki art data records the wiki's renamed, page-titled
picture files (for example `Finish_Raft_sprite_(cropped).png`) as sources, and
the wiki title list picks up its new pages (including `Version 0.9.0.0`, areas
and terrain). Every bundled picture is byte-identical. This is browser code
and data only; nothing new is uploaded.
Since e499f3b Mirklurk 0.9.0.2 (Steam's current release) is **Latest**, with
0.9.0.1's rules: orbs (items 267-274) have durability 30 and show their
condition, Magus Clay (being 41) has armour 49, Poison Arrow II at Wilda's
costs 0.25, and the hood is named `Clay's Magus Hood`. 0.9.0.0 and 0.8.9.9
saves now get a version switch; 0.9.0.1 and 0.9.0.2 saves get none. Item and
game data and the wiki data are regenerated; no art changes. This is browser
code and data only; nothing new is uploaded.
Since 00b3872 Mirklurk 0.9.1.0 (Steam's current release) is **Latest**, with
its own rules: it adds Flint (Large) (item 276, stacks to 5) and the Flint
Dagger (item 277, durability 20), which is also a chopping tool (×1.2), so
tree harvest costs and **Chop with** list it only under 0.9.1.0's rules.
0.9.0.1 and 0.9.0.2 saves now get a version switch; 0.9.1.0 saves get none,
and the editor offers and saves the two items only under Latest. Item and game
data are regenerated and the art data's version stamp reads 0.9.1.0; no art
changes. This is browser code and data only; nothing new is uploaded.
Since 5dbd86a the wiki data covers the 0.9.1.0 pages: Flint (Large) and the
Flint Dagger (items 276-277) show their mirklurk.wiki pictures
(`assets/wiki/item_276.a7eb5c2fd3.png`, `item_277.b27dd464e2.png`) and link
to their pages, and the wiki title list adds `Version 0.9.0.2` and
`Version 0.9.1.0`. No existing picture changes. This is browser code and data
only; nothing new is uploaded.
MirkMap is installable (web app manifest,
service worker): after the first visit it keeps the page, the save editor's
page, scripts, stylesheets, manifest, icons and all bundled art (394 files) so
local saves open offline.
It never caches `/api/`; pages are fetched network-first (up to 3 seconds) so
an online visit gets the newest release.

The application, Dockerfile and base nginx configuration live in
[dantebarbieri/mirklurk-map](https://github.com/dantebarbieri/mirklurk-map).
This repository owns pinned Compose services, the narrow nginx integration,
Homepage entry and operational runbook. No game binaries or user saves ship
in either image; 73 manifest-listed game-art PNGs and 308 manifest-listed
mirklurk.wiki pictures (`assets/wiki/`) are used with permission, as are the
six MirkMap icons drawn from the game's "Map of area" item and (since f7257fc)
the journal's text copied from the game's `UI.ini`. The web image also
serves `/manifest.webmanifest` (as `application/manifest+json`), `/sw.js` and
`/icons/`; like `index.html` they revalidate (`no-cache`). The editor page
`/edit/` (`/edit` too, via the existing `try_files`) uses `<base href="../">`
to load its hashed `edit.*.js` / `editor.*.css` from the site root; they are
cached immutable like `app.*.js` / `style.*.css`.

| Item | Value |
|---|---|
| Source (both targets) | `5dbd86a2b99ae28b538c4e191ed8d66789055a73`, merged main; [exact-source CI](https://github.com/dantebarbieri/mirklurk-map/actions/runs/39624946639) passed `test` and `docker-smoke` |
| Web | `mirklurk-map:5dbd86a`, target `web`, nginx non-root UID 101, private IPv4/IPv6 :8080 |
| Uploads | `mirklurk-map-uploads:5dbd86a`, target `uploads`, Deno non-root UID/GID **1993**, private :8081 |
| Networks | Web joins `proxy` and internal `mirklurk-map-uploads`; backend joins only the internal network with alias `uploads` |
| Storage | Named volume `compose_mirklurk-map-shares` at `/data`; Docker initializes ownership from the image, not host UID 1000 |
| Hardening | Both read-only, 16 MiB `/tmp`, cap-drop ALL, no-new-privileges; backend 768 MiB RAM, 1 CPU, 64 PIDs, unless-stopped |
| Exposure | No host ports, no router/firewall changes, no public file listing, no outbound backend network |
| Health | Each container's `/healthz`; web depends on healthy uploads |

Expected Deno 2.9.7 build identifiers (compare the actual image and live bytes,
not just HTTP status):

| Asset | SHA-256 |
|---|---|
| `app.29492404c5.js` | `29492404c592a40169f450905bf3f63c66e961ca44713948db9713901519a811` |
| `edit.9007285628.js` | `90072856289d7d3f8be43d42008d7a639c2eaa050bdd160c434d3007ed301e49` |
| `sw.js` | `aa042d7ee66076f5d5e8e50cce21f0dd4d32de7ba9c3c21e48d1aa0ec03be6ef` |

Stylesheets are `style.eac19037ec.css` and `editor.b1df531e67.css` (both
unchanged); the service worker keeps 394 entries and
lists both bundles, `assets/wiki/being_41.26af089dcc.png` and
`assets/wiki/item_277.b27dd464e2.png`, which are served as `image/png`. Both
browser bundles contain `Flint_Dagger_icon_(cropped).png` and
`Version 0.9.1.0`. Both browser bundles contain `0.9.1.0`, `Flint (Large)` and
`Flint Dagger`. Both browser bundles contain `0.9.0.2`, `0.9.0.1` and
`Poison Arrow II`. Both browser bundles contain
`Finish_Raft_sprite_(cropped).png`. Both browser bundles contain `0.9.0.0` and
`the game's Steam release`, and no longer `next_version_tester`. Both
browser bundles contain `Magus Clay (boss)`. Both browser
bundles contain `Game version rules`, The Terror's icon path
`M-2 -2.3 L-2.5 -6.1` and Magus Clay's `M0 -6.8 Q2.7 -6 2.7 -3.7`, and no longer
the old staff path `M-.6 -7 Q2 -6.8`; the map's also contains
`on no Steam branch now`, `Leeching` and `Grand Mother`,
and the editor's `does not have, so it could not load the save`,
`That takes back ` and `nothing to do: ` (neither is in the map's).

## Privacy, limits and retention

Five worlds per library; updating a world already in it never counts. Per
network (IPv4 address or IPv6 /64): ten stored worlds, ten new worlds per
rolling 24 hours (deleted ones count; rejected uploads do not) and ten named
libraries. A world is deleted **30 days after its last update**; updates extend
it. Packages are bounded at 64 MiB as sent and stored and at 4096 files; each
world has a 30-second update throttle and the backend allows 60 API
requests/minute per network. Since f7257fc clients send gzip-compressed
packages holding up to **256 MiB** of save once inflated. The backend inflates
into a buffer sized from the gzip trailer, refuses a declared size above
256 MiB before inflating and rejects a stream that disagrees; uncompressed
packages from older clients are still accepted up to 64 MiB, and are stored as
sent. The request body limit (`MAX_UPLOAD`, `/api/config` `maxBytes`, nginx's
and NPM's body bounds) stays 64 MiB. Worst case for one 256 MiB save is about
64 + 256 + 128 MiB (~450 MiB) and the backend processes one upload body at a
time, inside its 768 MiB limit; do not lower that limit.
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
(413 if that exceeds 64 MiB; since f7257fc the repack is gzip-compressed, and
413 also above 256 MiB inflated). Startup tolerates a missing `cheated.json` and
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

Since f7257fc that reader also requires an item's `burnTimeLeft` (torch and
lantern fuel), when present, to be a finite number, as `durability` and `wet`
already were; the game always writes a number, and a package that breaks this
is refused with 400 "Invalid item burnTimeLeft".

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
`compose_proxy` addresses **192.168.128.33** and **fd2b:92df:1a5b:1::21**, not
the shared Docker subnet. Confirm these addresses before each deploy; if NPM
is recreated with different addresses, update/review this file before enabling
uploads. The 2026-10-21 daily update recreated NPM, moving it from
192.168.128.46 / fd2b:92df:1a5b:1::2e (which `mirklurk-map` itself then took)
to these; until the 00b3872 release updated this file, web nginx saw every
client as NPM, so all clients shared one quota bucket. A stale entry trusts
whichever container takes that address next, so replace it; never add to it.
Web nginx always overwrites `X-Upload-IP` with its validated client IP.
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
   the 30-second throttle (including a matching exact ETag), and reject stale
   exact ETags with 412 before throttling. Update with `If-Match: *` (retention
   extended, creation time kept), reject the old ETag, reset the share link,
   delete, then verify 404 and that neither a wildcard nor an exact `If-Match`
   re-adds the deleted world (412). Never upload real saves or print keys.
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

Previous source: `00b3872fb36a5d1535a7d5e45a0e8bf9194cf677`, tags
`mirklurk-map:00b3872` / `mirklurk-map-uploads:00b3872` (also tagged
`rollback-00b3872-20261021-5dbd86a`). Preflight on
2026-10-21 UTC observed exact running images
`sha256:f1bc26dda44171aeef519db43ad38b7cdf041a42d80fcfd03f01387d8f1f87d4` (web)
and `sha256:dd5828c24bd85cf1ae5d51ee1e255dc6990dd43d96dbc5c74f0cc02e20369cfa`
(uploads); retain and recheck these exact images before mutation.
The 00b3872 -> 5dbd86a release is
[dantebarbieri/mirklurk-map#54](https://github.com/dantebarbieri/mirklurk-map/pull/54)
(wiki data for the 0.9.1.0 pages) and the docs-only
[dantebarbieri/mirklurk-map#53](https://github.com/dantebarbieri/mirklurk-map/pull/53)
(`.github/skills/game-update/SKILL.md`, not copied into either image). It
changes `src/wikidata.json`, `src/wikiart.json` and `tests/wiki_test.ts` and
adds `assets/wiki/item_276.a7eb5c2fd3.png` and `item_277.b27dd464e2.png` (the
service worker keeps 394 files). `server/`, the Dockerfile, `.dockerignore`,
source `deploy/nginx.conf`, compose, the sharing code and `tools/smoke.sh` are
unchanged, no existing asset changes, and the upload server imports none of
the changed files, so the rebuilt uploads image behaves identically: no
validation outcome, API route, quota, `/api/config` or stored format changes.
`nginx/mirklurk-map.conf` changes only its source-SHA comment. No migration,
config, secret or proxy change is required. Revert the pin and recreate only
uploads, then web, from the retained exact 00b3872 images under the shared
lock; never restore the uploads volume. The rollback has no format
incompatibility; it only brings back Flint (Large) and the Flint Dagger
without wiki pictures or page links.

Rolling back further to `e499f3b09018991ca6ae6b35baf88ba23171e396`, tags
`mirklurk-map:e499f3b` / `mirklurk-map-uploads:e499f3b` (also tagged
`rollback-e499f3b-20261021-00b3872`). Preflight on
2026-10-21 UTC observed exact running images
`sha256:206719fec71d58eb2a14995a5382d3ef3e8ae789fa64366f929fc36ce434c212` (web)
and `sha256:6857667c8df14170aee0a1e88ecae3918edd6757687c37f87140842f0df70d49`
(uploads); retain and recheck these exact images before mutation.
The e499f3b -> 00b3872 release is
[dantebarbieri/mirklurk-map#52](https://github.com/dantebarbieri/mirklurk-map/pull/52)
(Mirklurk 0.9.1.0 is Latest with its own rules). It changes
`src/version.ts`, `src/chop.ts`, `src/inspect.ts`, `src/view.ts`, a doc
comment in `src/coins.ts`, regenerated `src/itemdata.ts` / `src/gamedata.ts`
(items 276-277 only), the version stamp in `src/artdata.json` and
`tools/dump_art.csx`, header comments elsewhere, tests and the README.
`server/`, the Dockerfile, `.dockerignore`, source `deploy/nginx.conf`,
compose, the sharing code, `assets/` and `tools/smoke.sh` are unchanged (the
service worker keeps 392 files). Of what the upload server runs only comments
change (`src/health.ts`, `src/rules.ts`, `src/weather.ts`); `src/armor.ts`,
`src/chop.ts`, `src/itemdata.ts` and `src/version.ts` reach it only through
type-only imports erased at runtime, so the rebuilt uploads image behaves
identically: no validation outcome, API route, quota, `/api/config` or stored
format changes. `nginx/mirklurk-map.conf` changes its source-SHA comment and,
separately, its trusted NPM addresses (see NPM prerequisites). No migration,
secret or NPM proxy-host change is required. Revert only the pin (keep the
current NPM addresses in `nginx/mirklurk-map.conf`) and recreate only
uploads, then web, from the retained exact e499f3b images under the shared
lock; never restore the uploads volume. The rollback has no format
incompatibility; it only brings back 0.9.0.2 as Latest with 0.9.0.1's rules,
under which 0.9.1.0 saves are read without items 276-277 or the Flint
Dagger's chopping bonus.

Rolling back further to `a38013f49ac5b53aa2677c70c6f40537d65dd239`, tags
`mirklurk-map:a38013f` / `mirklurk-map-uploads:a38013f` (also tagged
`rollback-a38013f-20261016-e499f3b`). Preflight on
2026-10-16 UTC observed exact running images
`sha256:17f174d68652e21f6f00928a9911a73213769fbe79a85bb01b8ca2ce3343b8dc` (web)
and `sha256:db8f8e8b3ba63b8f2bd97f62141816924539536f915ad8dbbea585aa1085df8e`
(uploads); retain and recheck these exact images before mutation.
The a38013f -> e499f3b release is
[dantebarbieri/mirklurk-map#51](https://github.com/dantebarbieri/mirklurk-map/pull/51)
(Mirklurk 0.9.0.2 is Latest with 0.9.0.1's rules). It changes
`src/version.ts`, `src/condition.ts`, `src/bestiary.ts`, `src/creature.ts`,
`src/merchants.ts`, `src/inspect.ts`, `src/player.ts`, `src/view.ts`, the
editor, regenerated `src/itemdata.ts` / `src/gamedata.ts`, refreshed
`src/wikidata.json` / `src/wikiart.json`, the art version stamp, comments
elsewhere, tests and the README. `server/`, the Dockerfile, `.dockerignore`,
source `deploy/nginx.conf`, compose, the sharing code, `assets/` and
`tools/smoke.sh` are unchanged (the service worker keeps 392 files). Of what
the upload server imports only comments change, plus `src/itemdata.ts` (the
orbs' durability), which reaches it only through a type-only import erased at
runtime, so the rebuilt uploads image behaves identically: no validation
outcome, API route, quota, `/api/config` or stored format changes.
`nginx/mirklurk-map.conf` changes only its source-SHA comment. No migration,
config, secret or proxy change is required. Revert the pin and recreate only
uploads, then web, from the retained exact a38013f images under the shared
lock; never restore the uploads volume. The rollback has no format
incompatibility; it only brings back 0.9.0.0 as Latest with its rules.

Rolling back further to `3fb50b11c3701512b9ba49d08577521fe391a9df`, tags
`mirklurk-map:3fb50b1` / `mirklurk-map-uploads:3fb50b1` (also tagged
`rollback-3fb50b1-20261015-a38013f`). Preflight on
2026-10-15 UTC observed exact running images
`sha256:c9cb33608ece3580d3e15481355fe3dd66ead44f4edba9a51b97468b1c90332f` (web)
and `sha256:4246a95e90a6f785e50321039b29a00317fdede00648a8223f346187ad4dea36`
(uploads); retain and recheck these exact images before mutation.
The 3fb50b1 -> a38013f release is
[dantebarbieri/mirklurk-map#49](https://github.com/dantebarbieri/mirklurk-map/pull/49)
(wiki titles for the 0.9.0.0 pages) and
[dantebarbieri/mirklurk-map#50](https://github.com/dantebarbieri/mirklurk-map/pull/50)
(wiki pictures looked up by page title). It changes `src/wikidata.json`,
the `source` fields in `src/wikiart.json`, `src/wiki.ts`, `tools/wiki.ts`
and tests. `server/`, the Dockerfile, `.dockerignore`, source
`deploy/nginx.conf`, compose, the sharing code, `assets/` and
`tools/smoke.sh` are unchanged (the service worker keeps 392 files), and the
upload server imports none of the changed files, so the rebuilt uploads
image behaves identically: no validation outcome, API route, quota,
`/api/config` or stored format changes.
`nginx/mirklurk-map.conf` changes only its source-SHA comment. No migration,
config, secret or proxy change is required. Revert the pin and recreate only
uploads, then web, from the retained exact 3fb50b1 images under the shared
lock; never restore the uploads volume. The rollback has no format
incompatibility; it only brings back the older wiki title list and picture
source names.

Rolling back further to `5ce1c5fb8ed6d25034c696bfd385d42e7c69bf33`, tags
`mirklurk-map:5ce1c5f` / `mirklurk-map-uploads:5ce1c5f` (also tagged
`rollback-5ce1c5f-20261014-3fb50b1`). Preflight on
2026-10-14 UTC observed exact running images
`sha256:d186665d95e2159acd2b9c3e320fed2b7d355205716e43986ff35170fd58ab3d` (web)
and `sha256:9bc613f251cb2d89003c1dd85086773679a7a469d3138158b466b1f6bef2a7f8`
(uploads); retain and recheck these exact images before mutation.
The 5ce1c5f -> 3fb50b1 release is
[dantebarbieri/mirklurk-map#48](https://github.com/dantebarbieri/mirklurk-map/pull/48)
(Mirklurk 0.9.0.0 is Latest and the Beta switch is hidden). It changes
`src/version.ts`, `src/versionview.ts`, `src/editor/main.ts`, the version
stamp in `src/artdata.json`, comments elsewhere (including `style.css`),
tests and the README. `server/`, the Dockerfile, `.dockerignore`, source
`deploy/nginx.conf`, compose, the sharing code, `assets/` and
`tools/smoke.sh` are unchanged (the service worker keeps 392 files), and of
what the upload server imports only comments change, so the rebuilt uploads
image behaves identically: no validation outcome, API route, quota,
`/api/config` or stored format changes.
`nginx/mirklurk-map.conf` changes only its source-SHA comment. No migration,
config, secret or proxy change is required. Revert the pin and recreate only
uploads, then web, from the retained exact 5ce1c5f images under the shared
lock; never restore the uploads volume. The rollback has no format
incompatibility; it only brings back 0.8.1.5 as Latest and the Latest/Beta
switch.

Rolling back further to `a83056cea70de22a736009beb5c8e8f630820f84`, tags
`mirklurk-map:a83056c` / `mirklurk-map-uploads:a83056c` (also tagged
`rollback-a83056c-20261013-5ce1c5f`). Preflight on
2026-10-13 UTC observed exact running images
`sha256:ecb415d4283d2006e456a22a1b07d5981a5590c0019bb1218099ddc66995ea66` (web)
and `sha256:278b87367a4b1ee8ead9a88e1e482dd14f272a199d9c47e39e5a4c783b22bbc4`
(uploads); retain and recheck these exact images before mutation.
The a83056c -> 5ce1c5f release is
[dantebarbieri/mirklurk-map#47](https://github.com/dantebarbieri/mirklurk-map/pull/47)
(refreshed wiki pictures for 0.8.9.9; Magus Clay's realm picture and boss
page). It adds 24 PNGs under `assets/wiki/` and changes `src/wikiart.json`,
`src/wikidata.json`, `src/wiki.ts`, `src/inspect.ts`, tests and the README.
`server/`, the Dockerfile, `.dockerignore`, source `deploy/nginx.conf`,
compose, the sharing code and `tools/smoke.sh` are unchanged, and no existing
asset changes (the service worker keeps 392 files), so the rebuilt uploads
image behaves identically: no validation outcome, API route, quota,
`/api/config` or stored format changes.
`nginx/mirklurk-map.conf` changes only its source-SHA comment. No migration,
config, secret or proxy change is required. Revert the pin and recreate only
uploads, then web, from the retained exact a83056c images under the shared
lock; never restore the uploads volume. The rollback has no format
incompatibility; it only brings back the earlier wiki pictures and Magus
Clay's realm without his own picture or boss link.

Rolling back further to `407e030694efc0cc117e1df97fec3c0a1f6d293c`, tags
`mirklurk-map:407e030` / `mirklurk-map-uploads:407e030` (also tagged
`rollback-407e030-20261013-a83056c`). Preflight on
2026-10-13 UTC observed exact running images
`sha256:967d7c19befd895ffe6576df51fb2d19952228b390f9c78dce2391fc33855c92` (web)
and `sha256:4876dbdb6104bbf7333899252616fe5f7fd22c14542696bf540342ef042a50be`
(uploads); retain and recheck these exact images before mutation.
The 407e030 -> a83056c release is
[dantebarbieri/mirklurk-map#46](https://github.com/dantebarbieri/mirklurk-map/pull/46)
(the save editor drops unsaved changes a later change leaves with nothing to
do). It changes only `src/editor/main.ts`, `src/editor/session.ts`, tests and
the README. `server/`, the Dockerfile, `.dockerignore`, source
`deploy/nginx.conf`, compose, the sharing code, `assets/` and `tools/smoke.sh`
are unchanged (the service worker keeps 368 files, and the map bundle is
byte-identical), and nothing the upload server imports changes, so the rebuilt
uploads image behaves identically: no validation outcome, API route, quota,
`/api/config` or stored format changes.
`nginx/mirklurk-map.conf` changes only its source-SHA comment. No migration,
config, secret or proxy change is required. Revert the pin and recreate only
uploads, then web, from the retained exact 407e030 images under the shared
lock; never restore the uploads volume. The rollback has no format
incompatibility; it only brings back the editor listing every earlier change
a later one made redundant. Edits already saved to local game files are
unaffected.

Rolling back further to `a4671a4250d872d893bb1b2055dfd4ea27980a54`, tags
`mirklurk-map:a4671a4` / `mirklurk-map-uploads:a4671a4` (also tagged
`rollback-a4671a4-20261013-407e030`). Preflight on
2026-10-13 UTC observed exact running images
`sha256:0130950708e59f1236e131914db7d2f73c9f02c58f9e3051362dee17af841baf` (web)
and `sha256:71c6fd12e152ed57303024dd71d2669e61aed3d112e7f8bea15ecff5b5c3f189`
(uploads); retain and recheck these exact images before mutation.
The a4671a4 -> 407e030 release is
[dantebarbieri/mirklurk-map#45](https://github.com/dantebarbieri/mirklurk-map/pull/45)
(The Terror's own creature icon and Magus Clay's redrawn one). It changes only
`src/mapview.ts`, `src/objects.ts`, tests and the README. `server/`, the
Dockerfile, `.dockerignore`, source `deploy/nginx.conf`, compose, the sharing
code, `assets/` and `tools/smoke.sh` are unchanged (the service worker keeps
368 files), and nothing the upload server imports changes, so the rebuilt
uploads image behaves identically: no validation outcome, API route, quota,
`/api/config` or stored format changes.
`nginx/mirklurk-map.conf` changes only its source-SHA comment. No migration,
config, secret or proxy change is required. Revert the pin and recreate only
uploads, then web, from the retained exact a4671a4 images under the shared
lock; never restore the uploads volume. The rollback has no format
incompatibility; it only brings back the Mirkfangs' bat for The Terror and
Magus Clay's earlier icon.

Rolling back further to `a4220adcd704a43f0c954137ce1a167c71342cc1`, tags
`mirklurk-map:a4220ad` / `mirklurk-map-uploads:a4220ad` (also tagged
`rollback-a4220ad-20261013-a4671a4`). Preflight on
2026-10-13 UTC observed exact running images
`sha256:f14ad2299f50a08263039f45408e738b2a9d3d276647c9c872ca201df72ff6c0` (web)
and `sha256:802e75bd96073caa3982f980d8260a12655441af02b5ecdd303a9e223215d791`
(uploads); retain and recheck these exact images before mutation.
The a4220ad -> a4671a4 release includes
[dantebarbieri/mirklurk-map#43](https://github.com/dantebarbieri/mirklurk-map/pull/43)
(Mirklurk 0.8.9.9's beings, items, merchants, Survivors' camp, Magus realm and
rule changes, with regenerated data and art) and
[dantebarbieri/mirklurk-map#44](https://github.com/dantebarbieri/mirklurk-map/pull/44)
(each save's version is followed, the Latest/Beta switch, and the editor's
refusal to write what the chosen version lacks). `server/`, the Dockerfile,
`.dockerignore`, source `deploy/nginx.conf`, compose, the sharing code and
`tools/smoke.sh` are unchanged; `assets/game/` swaps content-hashed art (one
more PNG, so the service worker keeps 368 files) and `tools/` changes only
generators that are not copied into the image. Of what the upload server
imports, `src/save.ts` reads 0.8.9.9's added keys (`camp`, `campQ`, `xscale`)
additively and `src/itemdata.ts`, `src/armor.ts` and `src/rules.ts` gain
0.8.9.9 data, so the uploads image changes but no validation outcome, API
route, quota, `/api/config` or stored format does.
`nginx/mirklurk-map.conf` changes only its source-SHA comment. No migration,
config, secret or proxy change is required. Revert the pin and recreate only
uploads, then web, from the retained exact a4220ad images under the shared
lock; never restore the uploads volume. The rollback has no format
incompatibility; it removes 0.8.9.9 support and the Latest/Beta switch, so
0.8.9.9 saves are again read with 0.8.1.5 rules. Edits already saved to local
game files are unaffected.

Rolling back further to `f7257fc0c5c409aac06dba8a8f5976d1d1cf81bc`, tags
`mirklurk-map:f7257fc` / `mirklurk-map-uploads:f7257fc` (also tagged
`rollback-f7257fc-20261013-a4220ad`). Preflight on
2026-10-13 UTC observed exact running images
`sha256:419e17708118b9f8662638d9611bac559e9ff1487e841d047eb0b5f3d158866b` (web)
and `sha256:c9ce0d92ac676d98122974e03244513a663765366ff4acd0f5098874f63c01b6`
(uploads); retain and recheck these exact images before mutation.
The f7257fc -> a4220ad release includes
[dantebarbieri/mirklurk-map#41](https://github.com/dantebarbieri/mirklurk-map/pull/41)
(editable character preview and exact ETag handling),
[dantebarbieri/mirklurk-map#40](https://github.com/dantebarbieri/mirklurk-map/pull/40)
(shared helpers, development path validation and the map timer) and
[dantebarbieri/mirklurk-map#38](https://github.com/dantebarbieri/mirklurk-map/pull/38)
(reliable assertions, shared equipment rules and explicit malformed-object
warnings). The Dockerfile and `.dockerignore` add `tools/shared.ts` to the
build; runtime hardening, mounts, networks, resources, source nginx contract,
assets, API routes, quotas, `/api/config` and stored formats are unchanged.
`nginx/mirklurk-map.conf` changes only its source-SHA comment. No migration,
config, secret or proxy change is required. Revert the pin and recreate only
uploads, then web, from the retained exact f7257fc images under the shared
lock; never restore the uploads volume. Gzip packages already work at f7257fc,
so this rollback has no format incompatibility. It removes the new preview
and malformed-area behavior and the exact-ETag lost-update guard: f7257fc
honors only `If-Match: *` when refusing to re-add deleted worlds.

Rolling back further to `d2ad2d4d57530b68ec1e754c81a4d172aca9d9fe`, tags
`mirklurk-map:d2ad2d4` / `mirklurk-map-uploads:d2ad2d4`. Preflight on
2026-10-12 observed exact running images
`sha256:55530d749d1432b9f283577a331bc5f52e6c72f55b26434026e525714eaa2a3e` (web)
and `sha256:eb36ba0e5f1ea7dd981e6fe747d025b77d0e51746f2558e218cefd9c1514024a`
(uploads); record again before mutation because tagged base-image rebuilds can
change it. The d2ad2d4 → f7257fc release (mirklurk-map#29–#34, #36, #39)
changes the frontend (above) and the upload server's behavior: of
`server/`, the Dockerfile, `.dockerignore`, source `deploy/nginx.conf`,
compose, `assets/` and `tools/smoke.sh`, only `server/uploads.ts` changed (it
awaits the now-async `unpackSave`), and `deno.json` gained only tasks, lint
and coverage settings. Of what the upload server imports, `src/sharing-format.ts`
now reads gzip packages up to 256 MiB inflated and writes the Cheated-mark
repack gzip-compressed (above); `src/inventory.ts` also validates
`burnTimeLeft`; `src/save.ts`, `src/health.ts` and `src/files.ts` changed
additively. API routes, quotas and `/api/config` are unchanged
(`nginx/mirklurk-map.conf` changed only its source-SHA comment; the service
worker still keeps 367 files). No config, secret, proxy or nginx change and no
migration. Rolling back to d2ad2d4 is a pin revert plus recreating uploads
then web, with a **format caveat**: packages uploaded after this deploy (and
any the backend repacked with the Cheated mark) are stored gzip-compressed.
The d2ad2d4 client cannot open those worlds, and the d2ad2d4 backend rejects
gzip uploads from browsers that still run the cached f7257fc app, until rolling
forward again. Stored data is never lost, and worlds stored uncompressed (by
older clients) keep working. The locate crosshair, item condition display and
editing, the journal, hit-point status and timed-condition editing, interior
moves and the shared opened save (with the editor's My worlds saving)
disappear.

Rolling back further to `a70f5135cf9afe3ca9490a17e0cc365f6141e448`
(`mirklurk-map:a70f513` / `mirklurk-map-uploads:a70f513`, observed
`sha256:27e83d743dcbb4148b6bda04424f7e4ade30aff1f571a925d6f92c0df4968993` /
`sha256:120045f3859362305baafa08b745c30f9491e0fffb75859a6835c7d6466809c3` on
2026-10-12) also removes the d2ad2d4 release, which was frontend: it changed
`edit.html`, `style.css`, `src/editor/`, `src/dialog.ts`, `src/inspect.ts`,
`src/itemdata.ts`, `src/mapview.ts`, `src/objects.ts`, `src/save.ts`,
`src/view.ts`, `tools/itemdata.ts`, tests and the README (water and raft
moves, every carryable item, creatures only where they live, the Rafts layer,
above). `server/`, the Dockerfile, `.dockerignore`, source `deploy/nginx.conf`,
compose, the sharing code, `assets/` and `tools/smoke.sh` were unchanged
(`nginx/mirklurk-map.conf` changed only its source-SHA comment; the service
worker kept 367 files). Of what the upload server imports only
`src/save.ts` changed, additively (`parsePlayer` also reads `ensureRaft` into
`onRaft`), so the uploads image changed but no API route, quota,
`/api/config`, validation outcome or stored format did. It is a pin revert
plus recreating uploads then web; no migration, data or proxy change is
involved and no data is lost (the f7257fc gzip caveat above applies to this
and every earlier release). The editor again refuses to
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
