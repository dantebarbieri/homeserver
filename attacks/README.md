# Attacks

Private, read-only security-event observatory for **attacks.danteb.com**.
A charcoal UI with an SVG world map, live event stream, severity, multi-select
type/outcome and source (IP, country, network) filters, inspectable evidence
badges, an optional **Group by source** view (one expandable row per IP with its
event count and type/severity mix; the choice is remembered), Loki window statistics, and
Prometheus lifetime counters and live gauges.
There is no classifier queue for a human to work through, and no AI dependency.

## What the badges mean

| Source | Evidence retained | Classification |
|---|---|---|
| Endlessh | Accept/close, IP, source port, completed duration | Observation of a bot stuck in Endlessh, not proof of human intent |
| Real SSH | Attempted user, explicit rejection reason, auth method when logged | Rejected authentication or incomplete pre-auth disconnect |
| Real SSH success | User, auth method, public-key fingerprint | Accepted; recognized vs unregistered credential |
| fail2ban | sshd jail's actual ban record | Blocked |
| Authelia | Explicit unsuccessful authentication record, user, factor, IP | Failed sign-in; not ordinary 401 login-page redirects |
| NPM | Common probe paths or 401/403/429; method, host, client IP | Suspected probe or unclassified access denial |
| Forgejo SSH (2222) | Bare sshd messages from Forgejo's own SSH server, parsed like real SSH: user, reason, auth method | Same outcomes as real SSH, badged **Git SSH** |
| Plex | WAN request lines from Plex's own log: method, path (no query), source | Signed-in client, public endpoint, probable remote-access check, or unauthenticated request; see below |
| Hytale | Container log line for a refused identity token | Failed game login; intent unknown |
| Other game/service ports | Inbound TCP SYN or representative UDP datagram | Unclassified connection, not automatically an attack |

Plex requests are split by what the request itself shows. A request carrying a
Plex token is a **client request** (informational). Tokenless `/identity`, the web
app or a streaming session path is a **public endpoint** request: these expose no
library data. A tokenless `/identity` from an AWS-published range is relabeled a
**probable Plex remote-access check**, because plex.tv checks reachability that way,
but any AWS customer can send the same request, so this is an inference. A
tokenless request for any other path is an **unauthenticated request**: what an
internet scanner sends, not evidence that anything was accessed. Tokens, query
strings and account names are never read into events. Busy clients and scanners
are summarised to one event per source and request class per window.

Hytale refuses clients whose identity token is invalid
(`invalidIdentityToken`). That means the client was not a signed-in player; it
could be a server-list poller, a scanner speaking the game protocol or an outdated
client. Player names from the same log are never stored. A rejection within one
interval of a known status poller's contact is labeled as that poller's (below).

Satisfactory clients reach the game port (7778) before its messaging port
(29778). A messaging-port connection from an address that had not contacted the
game port in the previous 10 minutes is labeled **Port scan: not a game client**.
The collector keeps that contact history in memory, so in the first 10 minutes
after a collector restart a real player can be mislabeled. The messaging port
used to be 8888, a common HTTP-alternate port; every connection seen there in a
week came from scanning and cloud networks that never touched the game port.
History collected before the move keeps its old Satisfactory label.

Every event includes a plain-language evidence explanation. A failed sign-in
can be a legitimate typo; a port connection can be a real player, viewer or
health check. Successful SSH logins are audit events, **not attack counts**.
The aggregate is deliberately called **events observed**, not attackers.

### Severity

Each event kind has a severity, read from its kind at query time, so it also
applies to history collected before it existed:

| Severity | Kinds |
|---|---|
| Info | Accepted SSH login, Plex client request, probable Plex remote-access check |
| Low | Endlessh close (the trapped duration), HTTP 401/403/429, service-port connection, game port scan, public Plex endpoint |
| Suspicious | Endlessh connection, real-SSH port probe, SSH disconnect before login, unauthenticated Plex request, rejected Hytale identity token |
| High | Failed SSH login, fail2ban ban, failed Authelia sign-in, suspicious web request |
| Critical | SSH login with a credential missing from the key registry |

Endlessh connections and real-SSH port probes are Suspicious: nothing legitimate
connects to the decoy, and both are reported to AbuseIPDB. Game-port scans stay Low
and are never reported, since server-status sites probe those ports.

Severity ranks how much attention an event deserves, not whether it was an
attack, and it never uses source reputation. A "Suspicious or higher" filter keeps
Suspicious, High and Critical. Plex, Hytale and Forgejo SSH events exist only from
the day those log sources were added; the severity scale and filters cover
everything collected.

**Own** means the source belongs to LAN/private, loopback, link-local, Tailscale
address space, or the home's public IPv6 /64. The host capture heartbeat reports
usable global /64s from `bond0`; the collector does not hardcode a changing ISP
prefix. Own traffic is retained as audit evidence, hidden by default behind
**Show own traffic**, and always excluded from the map and aggregate cards.
This is a network classification, not proof of identity or permission.
Other legitimate public clients can still appear.

**Poller** marks game-server status checkers: server lists and uptime trackers that
contact a game port (Hytale, Satisfactory 7778, Minecraft, RLCraft) on a steady timer.
Three contacts from one address to one port whose two gaps are 2–60 minutes and agree
to within 20% (or 30 s) confirm a poller; its later contacts count while they keep no
more than twice that pace, and a Hytale identity rejection within one interval of a
contact is its handshake. A quicker contact restarts an unconfirmed cadence and is not
a poll once confirmed, so scanner retry bursts stay attacks, and a day of silence
starts over. The collector keeps this history in SQLite and lists up to 64 known
(address, port) pairs with their first confirmation time in `/status`, dropping a pair
31 days after its last contact or, once it stops polling, after its confirmation. The
API also hides each pair's contacts from before that confirmation, including the first
two; its later contacts keep the collector's verdict.
Like own traffic, pollers are hidden by default behind **Show status pollers**,
excluded from the map and aggregate cards, and never reported to AbuseIPDB. A steady
cadence is not proof of who runs the checker.
Missing/stale network metadata reports an error and holds source checkpoints,
rather than silently counting home IPv6 clients as external.

SSH's existing `LogLevel VERBOSE`, key-only authentication and fail2ban policy
are unchanged. Unsupported password-method requests are not necessarily logged
at this level: the UI says **unknown** when the method is not in the evidence.
It never invents attempted passwords. Generic established-session disconnects,
post-quantum negotiation warnings and successful key-discovery messages are not
classified as rejected logins.

Nix generates `/etc/attacks/ssh-keys.json` from declarative authorized public
keys, including the Studio tunnel key. Fingerprint recognition is scoped to the
login user. No private key is read. A recognized fingerprint proves which
credential was accepted, not who physically used it. Runtime
`~/.ssh/authorized_keys` entries and SSH certificates may legitimately be absent
from this registry: **unregistered does not mean unauthorized**. Registry errors
are visible in collection health and never silently mark a key as recognized.

### Map and live stream

Changing statistic, live-trapping, feed and map counters roll their changed digits
upward over 420 ms. Unchanged digits and labels stay still. Initial values appear
immediately, rapid updates replace stale transitions, and reduced motion disables
the effect. The accessible/selected text always contains the current value once,
not the animation's previous digits.

The desktop default **Equal Earth** projection preserves relative land areas rather
than exaggerating polar regions. A selector compares it with the original
equirectangular map (which was not Mercator). Both country outlines and event
coordinates use the same projection. It uses no map tiles, CDN or third-party
requests in the browser.

The map's controls are icon buttons in its top-right corner, each with an accessible
name and a tooltip. **Map settings** (the gear) opens a popover, or a bottom sheet on
phones, holding the projection, **Show faded dots** and the dot settings; Escape, its
close button or a press outside closes it. On touch phones both bottom sheets (map
settings and event details) close with a downward swipe, like native sheets, and
hide their close button, which stays available to screen readers and keyboards; a
short or slow pull springs back, and long content still scrolls. **Full screen** sits beside the gear.
Wherever the view can move (the globe, or the full-screen flat map) a second row adds
**Reset view**, **Follow** and the zoom buttons. A status line under the map names
the sources it leaves out, for example `Sources not drawn: 2 faded · 5 on far side`.
**Faded** sources have fully faded (they are drawn instead when Show faded dots is
on), **on far side** applies to the globe, **unlocated** sources have no
coordinates, and **over the dot limit** counts sources dropped by the cap below.
The line is empty when everything is drawn.

**Globe** is the touch-first default and is selectable on desktop too. Drag to
rotate in any direction; pinch or scroll to zoom around the chosen point.
It works inline and fullscreen. The page can still scroll outside the globe;
flat-map gestures remain fullscreen-only. Projection choice is saved locally
and takes precedence over the device default. **Reset view** zooms out and restores
a north-up globe centered at latitude **30.429156 N**, with no roll. At that
northern viewing angle it faces the most currently eligible dots, accounting for filters, fading, history and the
dot limit. Ties favor the widest centering range to keep dots away from the limb.
With no displayable dots, it faces longitude 97.742164 W at the same northern
latitude; this is also the starting orientation. Reset never changes
filters, and it turns **Follow** off.
Far-side dots are hidden, including their hit targets and tooltips,
and their count is disclosed; all events remain available in the stream.

Borders progressively change from Natural Earth **1:110m** below 2.5x zoom,
to **1:50m** at 2.5x, to **1:10m** at 6x. These are cartographic scale
denominators (millions), not metre-level accuracy. All three are pinned to
Natural Earth v5.1.2, its latest published release when added, and served
locally as compressed TopoJSON. The detailed set includes Singapore, Monaco,
Vatican, San Marino and Hong Kong S.A.R. Small country/territory labels appear
from 4x zoom, with overlap suppression; country outlines also have hover titles.
Shapes remain to scale, so microstates need close zoom. Detail loading failures
are explicit and retain the available map. This is regional cartography, not
street-level OpenStreetMap or a claim that disputed borders are uncontested.
More detailed borders do not improve the accuracy of IP geolocation.

**One dot represents one source IP**, not one request. The dot shows how many
matching events from that IP are loaded. Its age follows the latest observation;
its position uses the most recent available location for that IP.
Different IPs at the same coordinates are still different sources. Every request
remains a separate stream row and still counts toward event totals.

A source with several event kinds is drawn as a **pie**: one slice per kind, in
the legend's fixed order, sized by its share of the loaded matching events. Each
kind gets one contiguous slice, which is already the fewest arcs possible, and
the fixed order keeps colours from jumping as counts change. Every slice gets at
least 10% of the circle so a single odd event stays visible, so slice sizes are
approximate. A source with one kind is a plain dot. The ring around a dot shows
**severity** (grey info, blue low, amber suspicious, orange high, red critical),
split into arcs with small gaps when the source's events differ, highest first.
The ring appears when a dot flashes and while it is hovered or focused; hovering
also enlarges the dot. The hover card, arrival card and screen-reader label list
the counts per kind and per severity.

The **7 most recently active located sources** in the loaded view stay bright. Older dots start
fading when displaced from that group and disappear after **30 minutes**.
The map has a hard **300-dot limit**, dropping oldest points first during bursts;
this never deletes collected events. **Map settings** adjusts all three values
and saves them in the browser. Set the held count to 0 for a fully fading map.
Fading uses collection time, not time since opening the page. **Show faded dots**
draws fully faded sources at 12% opacity, still within the limit. It uses only
events already loaded in the browser (the stream's **Load older events** is what
fetches more) and changes no statistic.

A new event **flashes** its source's dot: a burst in the new event's kind colour,
a white-hot dot and two expanding severity rings, settling back into the pie
within about six seconds before joining the slow fade above. Only genuinely fresh events flash (arrived within 60 seconds,
or 30 seconds on first load, by the server's clock), at most 12 at once, so
catching up after a paused or hidden tab never lights up the whole map. Far-side
globe events cannot flash unless **Follow** turns to them, which replays their
flash and summary on arrival. Reduced-motion replaces the animation with a static
white outline and severity ring for the same six seconds. Brief summary cards last 4.5 seconds.
Desktop summaries track the dot center, not the expanding rings. Up to three are
shown, one per IP; when different IPs share a location, cards keep their separate spots as older
ones fade. With Follow on, an offscreen arrival's card appears only once its
dot is in view. Phones show one bottom card, with overflow disclosed during bursts.
Hover/focus always offers details: the hover
card shows how long ago the event happened (top right, kept current while open)
and a hint that matches what a click does. Normal
desktop clicks filter the stream to a multi-event source's IP (or highlight its
row for a single event). In fullscreen or on mobile, a dot opens the latest
event details with a link to the source's stream; phones use a scrollable bottom
sheet, with 48-pixel invisible touch targets around visible dots.

**Full screen** supports wheel/pinch zoom, drag-to-pan, zoom/reset buttons and
keyboard arrows, `+`/`-` and `0`. Zoom is bounded to 1-128x and flat-map panning stays within
the world. Native fullscreen is used where available; an expanded viewport
works on iPhone too. The globe supports the same gestures without fullscreen.
Reduced-motion mode removes decorative animation. GeoIP is approximate and
locates infrastructure, not a person.

**Follow** (globe, or the full-screen flat map) moves the view to new attacks.
It moves only when a new dot is off screen, behind the globe, near the edge or
squashed against the limb, then holds still for **4 seconds** so it can be read.
Arrivals during a move or hold are batched into the next move, so a busy stream
moves about once every five seconds rather than on every event. The globe turns
north-up at the current zoom, framing a burst together when it fits and
otherwise facing the newest event. The flat map zooms out and back in along a
smooth path (van Wijk and Nuij) to frame the new dots at the follow zoom (3x
by default, or the zoom you set). Zooming keeps following; dragging, arrow keys or
**Reset view** turn it off. It waits while a pointer is down, a hover card or
event details are open, or the tab is hidden, and skips arrivals older than 15
seconds. Reduced-motion jumps instead of animating. The choice is saved locally
and starts off.

The feed polls every three seconds, loads 250 rows per page and retains at most
1,000 in the browser. Busy live polls catch up through at most eight pages per
cycle and show a catching-up indicator while more remain. Each poll re-reads the
last 15 seconds, so the stream changes only when an event is new or came back
different; unchanged rows are reused, so a quiet poll costs nothing and a row's
highlight, focus and scroll position survive new arrivals. Filters are applied
server-side, not just to the visible
rows. The map and source count describe the loaded rows, not every event in the
selected period. Top-level metrics cover **all sources** in the selected window.
**Filters** combine as AND across groups. **Severity** is a five-step "at least" control
(Any, Low, Suspicious, High, Critical). **Type** and **Outcome** are multi-select
pickers (several values in a group combine as OR). Each Severity step, Type and Outcome
option shows how many events in the selected window it would show, counted against the
other two groups' current choices and the Source filters (Severity counts are cumulative,
since a step means "at least"); options with none are dimmed but still selectable.
`/api/facets` returns those counts grouped by type, outcome and severity, so changing a
picker recounts instantly; they refresh every 30 seconds. **Source** chooses an exact IP,
a country or a network (ASN); its country and network lists show the top twelve by
event count in the selected window (own traffic and pollers follow their toggles), fetched when the
picker opens. An event's details also offer **Only this source IP / country / network**.
Active filters appear as removable chips. They are applied server-side: `/api/events`
accepts `severity`, comma-separated `type` and `outcome`, `ip`, `country` and `asn`, and
`/api/sources` returns the Source picker's lists. There is no attempted-username filter; the
username is still shown on events. `own=1` and `pollers=1` include own traffic and status
pollers. **Clear filters** clears all of these, **Show own traffic** and **Show status pollers**
and immediately reloads the unfiltered stream, preserving the observation window and pause state.

### Network ownership, flags and VPN evidence

Every source can include a country flag, ASN and organization, plus cloud and
relay badges. These are **offline lookups**, not WHOIS/API queries containing
observed IPs. Network ownership never upgrades the attack classification. The
one exception is the optional AbuseIPDB integration below.

- DB-IP Lite City and ASN provide approximate location and routed-network ownership.
  US locations read `City, ST` because city names repeat across states; US
  territories such as Puerto Rico are separate countries in DB-IP.
- Official AWS, Azure Public Cloud, Google Cloud and Oracle Cloud prefix lists
  support explicit cloud badges, independent of ASN ownership.
- Mullvad and NordVPN's public server lists support **VPN server** associations.
  These are entry-server addresses, not comprehensive exit lists: a match does
  not prove VPN exit traffic; no match does not mean "not a VPN."
- Tor's published exit list supports a distinct **Tor exit** badge.
- Vercel appears only when the ASN organization explicitly names it. A shared
  AWS/Cloudflare address cannot reveal that Vercel, or any particular tenant,
  made a request. Other network organizations remain visible without guessing.

Details show evidence, source URLs and dataset times. Cloud and VPN/relay
evidence remain separate, so one address can have both badges. Nothing claims
to identify the actual person, or to exhaustively detect commercial,
residential or self-hosted VPNs. No AI or manual classification queue is used.

`attacks-intelligence.service` downloads public bulk datasets into
`/var/lib/attacks-intelligence` as a dynamic, unprivileged user. Its timer runs
daily at 02:45 with up to 15 minutes' jitter, plus a boot refresh. DB-IP files
download once per monthly release; prefix/server lists refresh daily.
Validated files replace atomically. Failed refreshes retain the previous
timestamp, report errors and fail the unit for ntfy notification. Cloud
associations expire after seven days, VPN/Tor associations after two days;
expired lists no longer produce new badges. Missing data stays unknown.
ASN/City databases warn 62 days after their embedded build time, not download
time. Corrupt lookup records are reported as unavailable without stopping event
collection or independent prefix matching. Existing event enrichment is a historical
snapshot; refreshes do not rewrite old events.

### AbuseIPDB reputation and reports

Event details link to the source's public AbuseIPDB page; the link sends
nothing until clicked. With `ABUSEIPDB_API_KEY` set in `docker/.env` (a free
account allows 1,000 checks and 1,000 reports a day), the collector also:

- **Looks up** each external public source once a day and shows an
  **AbuseIPDB N%** badge (grey 0, amber 1-49, red 50+) plus details: reports,
  reporting users, last report, usage type and Tor/whitelist flags. Own-network
  and private addresses are never sent. Reputation is context only; it never
  changes an event's classification or severity. Sources this server reported get a
  separate **Reported by us** badge.
- **Filters** the stream, map and facets by a **Reputation** picker (shown only
  while a key is configured): High risk (50-100%), Some reports (1-49%), No reports
  (0%), Not checked yet, and Reported by this server. Choices combine with OR,
  and each shows its matching count. "Not checked yet" means no grade, whether or
  not this server reported the source. The API joins grades to events in Python,
  never as a LogQL address list (see **Query cost** below).
- **Reports** (`ABUSEIPDB_REPORTING=strict`, the default; `off` disables it)
  only high-confidence abuse from external sources within one hour:

  | Evidence | Threshold | Categories |
  |---|---|---|
  | SSH login with a username that does not exist or may not log in, such as root or admin (real port or Forgejo) | 1 | SSH, Brute-Force |
  | Other failed SSH authentication (real port or Forgejo) | 3 | SSH, Brute-Force |
  | Connection to the real SSH port, or SSH handshake abandoned before login | 3 | Port Scan, SSH |
  | Failed Authelia sign-in | 5 | Brute-Force, Web App Attack |
  | Rejected (401/403/429) POST to a login, sign-in or session path | 10 | Brute-Force, Web App Attack |
  | Exploit, credential-file or admin-path web probe (`.env`, `.git`, `.aws`, `.ssh`, `phpinfo.php`, `wp-config.php`, root `*.sql` dumps…) | 2 | Web App Attack |
  | Endlessh visit (port 22 serves no SSH) | 1 | Port Scan, SSH |

  Game-port scans (server-status sites probe those), other 401/403 responses
  (expired sessions, token refreshes), plain 404s (mostly real app traffic),
  Plex, Hytale and other service connections are never reported. The wiki
  (mirklurk.wiki) sits behind Cloudflare's proxy; NPM takes its visitor's
  address from `CF-Connecting-IP`, trusted only from Cloudflare's ranges
  (`docker/nginx/cloudflare-real-ip.conf`, applied by
  `docker/scripts/mirklurk-wiki-proxy.sh --apply`), so wiki probes are mapped
  and reported like any other. NPM's own CDN range list is disabled
  (`IP_RANGES_FETCH_ENABLED=false`): it trusted a client-supplied `X-Real-IP`
  through any CloudFront or Cloudflare edge, letting anyone forge the logged
  address. Safeguards: a report waits five minutes and is dropped if
  the address has since signed in successfully over SSH or used Plex as a
  client (such addresses stay exempt for 30 days); an address is reported at
  most once a day and never when AbuseIPDB whitelists it; events older than a
  day (backfill) are ignored. Reports carry a fixed public comment per rule, so
  usernames, hostnames and paths are never published. Every report is kept in a
  history table, and the top **Reported to AbuseIPDB** card shows the reports
  sent in the selected range and the share of distinct external sources seen
  in that range that we reported (without a key the card shows failed real-SSH
  and Authelia sign-ins instead).

The events-per-minute sparkline is labelled with its peak (and when), mean and
median rate; a trailing partial bucket is left out so one late event is not a
false peak.

Calls are capped locally at 900 checks and 900 reports per rolling day; an
HTTP 429 pauses that kind of call until `Retry-After`. State lives in
`/state/abuseipdb.sqlite`. The collector health card shows **abuseipdb · off**
without a key, otherwise its daily counts. Apply a new key with
`docker compose --env-file docker/.env -f attacks/compose.yml up -d attacks-collector`.

### Home-screen app

The authenticated site is installable as a standalone PWA. On iPhone, sign in
through Safari, then **Share -> Add to Home Screen**. Supporting browsers expose
**Install app**, or their own installation menu. The production URL must use
HTTPS; localhost is supported for development.

Only the static shell, geometry, fonts and icons are cached. Installation fetches
only the coarse 38 KB (compressed) overview, not the detailed world maps.
The 228 KB regional and 1.47 MB detailed maps download on demand at their zoom
thresholds, then use cache-first storage across visits. Geometry filenames carry
content hashes and receive immutable HTTP caching; unchanged maps survive app-shell
updates, while activation removes obsolete geometry hashes. Fonts and icons are
cache-first too. Application code and HTML check the network for current versions
and authentication, with an offline fallback. This deliberately uses three
compact whole-world vector levels, not geographic tiles or a street-map service.

**No events, IPs,
usernames, metrics, status responses or API requests enter the service-worker
cache.** Offline reloads show the shell with unavailable telemetry, never a
fabricated feed. A page left open offline can still show its previously loaded
in-memory rows, with an explicit stale/offline warning. Network navigation
preserves Authelia redirects and authentication failures; APIs remain
authenticated network-only requests. The manifest includes credentials so its
fetch works behind Authelia. The service worker is a classic script, not a
module: browsers fetch module service-worker scripts without cookies, so
Authelia would redirect them and registration would fail. Previously visited detail levels remain usable offline while browser storage is
retained; never-downloaded detail reports an error and keeps the available
coarser map. Browser storage can be evicted. Home-screen installation does not bypass 2FA and
does not add push notifications or background attack polling.

### Attacker time wasted

`attacks_endlessh_seconds_total` sums the durations in completed Endlessh `CLOSE`
records, once per source event. The main card uses **Loki's sum of completed
durations logged in the selected window, plus the full elapsed age of currently
observed external sessions**. Ongoing ages are not clipped at the window boundary.
Concurrent connections each
contribute their duration: these are **bot connection-hours, not human hours**.
The active set is persisted and deduplicated by source address/port; a close
removes it, and an Endlessh "Listening on" restart clears prior opens without
inventing completed durations. The UI ticks between samples, stopping estimates
after 90 seconds without fresh telemetry. Source lag or delivery errors disable
live estimates. The API uses one delivered-data watermark for the active snapshot
and completed log sums, so a racing close is not counted twice.

Live tracking starts with newly observed accepts after this feature's activation.
Already-open sessions are not reconstructed; their actual close records will
still contribute completed durations. Sessions lost during a restart have no
completed duration. The live gauges are `attacks_endlessh_trapped_connections`
and `attacks_endlessh_trapped_now_seconds`; consult `attacks_source_ready` before
using gauges for alerts.

Each Endlessh event also says how long **its own connection** was held. A close
record carries the duration Endlessh logged, so both the "Stuck in Endlessh" and the
"Left Endlessh" rows of a finished connection show **Trapped for 5 min 13 s**
(badges on rows, hover cards and arrival cards, and **Time stuck** in the event
details). A connection still open shows **Trapped now · 41 s**, a clock that advances
every second, and "so far · still connected" in the details. An open and its close
are matched by source address and port. When neither can be shown honestly (no close
was logged and live telemetry cannot confirm the connection is open, which includes
own traffic, restarts and lost log lines) the badge is omitted and the details say
**Unknown** rather than guess.

For the live part, `/api/stats` returns a `trapping` object beyond the totals:
`active` lists the newest currently held external connections (`ip`, `sourcePort`,
`since`; at most 200), `activeTruncated` is true when more were open than listed,
`asOf` is the API's clock when it answered and `through` is the delivered-data
watermark. An event observed at or before `through` is accounted for by `active`;
a later one may not be yet, so the page treats it as still held "so far" rather than
unknown. The collector publishes this list together with the live gauges, so after
changing it redeploy both `attacks` and `attacks-collector`.

The secondary lifetime figure remains Prometheus's **completed external** counter,
with its classification start date shown. Pre-upgrade counters are preserved as
`origin="legacy"`: their own/external split is unknowable from aggregate labels,
so they are not guessed into the new external lifetime counter. New counters carry
`origin="own"`, `origin="external"` or `origin="poller"`. SQLite persists all four.

Window totals, failures and the per-minute timeline count normalized Loki records,
not Prometheus `increase()` estimates. This avoids missing the first event of a
new counter series and extrapolated fractional counts. It trades cheap time-series
queries for bounded log scans; the UI's maximum window is Loki's 30-day retention,
while Prometheus retains 90 days. Failures are reported, never replaced with fake
zeroes. Timeline gaps from valid, quiet queries are zero-filled. Extracted
high-cardinality fields are removed before aggregation.

**Query cost.** Moving back to Prometheus would not speed up long windows; the
LogQL shape decides it. Never put a set of IPs into LogQL: an `ip=~"a|b|…"`
filter over hundreds of graded addresses took over 9 seconds per query and,
re-polled every 30 seconds, queued every other dashboard query behind it until
7- and 30-day windows timed out. Instead:

- `/api/facets` is one `sum by (type, verdict, kind, ip)` metric query; Python
  merges the rows and joins reputation grades.
- A reputation-filtered `/api/events` first counts events per IP with one
  metric query, so with no matching source it answers at once. Otherwise it
  reads plain Loki pages, keeps rows whose IP passes the filter and stops once
  it has a page, every counted match, or five 1,000-row pages. Unless it read
  to the window's end, it returns a cursor to continue: the count can miss
  events delivered after it ran. While a reload finds nothing yet, the page
  keeps following that cursor (up to eight requests). Loki's `end` is
  exclusive, so `before` cursors and re-read page boundaries end one
  nanosecond after the last timestamp they must include.
- `/api/stats` runs its seven upstream queries concurrently, and `/api/sources`
  its two.
- Hiding status pollers is the one deliberate exception: at most 64 known
  (address, port) pairs, each a `(ip != "…" or port != "…" or timestamp >= …)`
  filter. New poller events are already excluded by their `origin` stream label;
  the pairs only catch contacts logged before confirmation.

Per-IP aggregation needs more than Loki's default 500 series per query, so
`docker/monitoring/loki-config.yml` sets `max_query_series: 20000`. That limit
applies only to query results; ingestion limits are unchanged. Loki also runs
each query as one sub-query per split interval. At the 1h default a 30-day
query was 720 sub-queries through four workers, about 5 seconds of queueing
for 9 MB of data, so the config splits by 24h and runs 16 workers. Every
dashboard request then takes under a second. Restart `loki` after changing
any of these. The page shows a spinner with what it is loading
(events, statistics, filter counts) and cancels a request superseded by a newer
window or filter, so switching ranges never waits on a stale query.

## Data flow and limits

```text
Endlessh / Authelia / Forgejo / Hytale stdout ─ Alloy Docker ─┐
sshd / fail2ban journal ─── Alloy fixed journal filters ──────┤
bond0 headers ─ capture.py ─ journal ─ Alloy ─────────────────┤
                                                            v
                                                     existing Loki
                                                            |
NPM access + Plex request logs (read-only) ──────── attacks-collector
                                                            |
                           durable bounded outbox ──────────┤
                                                            v
                            sanitized event JSON ─── existing Loki (30d)
                            bounded counters ──── existing Prometheus (90d)
                                                            |
                                             fixed read-only web APIs
                                                            |
                                         NPM + Authelia admins / 2FA
```

The normalizer has no Docker socket or capture capability. SQLite stores
cursors, deduplication IDs, cumulative counters, bounded active-session state,
and undelivered events, **not
a second searchable event archive**. The web container has no writable state,
log mounts, keys or host privileges. Neither publishes a host port.

The host helper runs as a dynamic unprivileged user with `CAP_NET_RAW`, not
`CAP_NET_ADMIN`. It observes `bond0` ingress before Docker DNAT, so published
container ports are visible. It does not listen, alter the firewall, block
traffic, or enable promiscuous mode. Bounded packet prefixes pass through memory
to decode headers; no packet files or application payloads are analyzed or
retained. Public-source traffic only is considered for service connections,
NPM and Endlessh; authentication audit events also include local/tailnet users.

Endlessh uses a dedicated dual-stack Docker network. An IPv4-only bridge makes
Docker proxy incoming IPv6 through its gateway, hiding the source address;
those private-gateway log records cannot be geolocated or attributed. The
dual-stack network preserves real clients without changing the published port.

Ports are explicitly mapped in `events.py`: real SSH 28, Git SSH 2222, Plex
32400/8324/32469, Minecraft 36676/36677, Hytale 5205 and Satisfactory 7778 (game) / 29778 (messaging).
Unknown ports and traffic blocked upstream by the router are not visible.
Forgejo's and Hytale's container logs reach the collector through the same Loki
path as Endlessh. Plex's own `Plex Media Server*.log*` files are mounted read-only at
`/plex-logs` (from `${DATA}/plex/config/.../Logs`); Plex writes them in the server's
local time, so `PLEX_LOG_TZ` (from `TZ`) converts them. Only WAN request lines are
read, and only those from public addresses. Plex debug logging must be on for
those lines to exist. The Forgejo accepted-login line format has not yet been
observed in production, so successful Git logins may not appear until it is.
Long IPv6 extension chains exceeding the 160-byte header snapshot, encrypted
payloads and application-level game/Plex authentication are not interpreted.
TCP SYN retransmissions are coalesced per tuple for 60 seconds; UDP is one
observation per source/target port per 60 seconds. A 100-events/second capture
ceiling bounds load. Suppressed observations are shown in collection health.

Raw journal collection begins at most one hour back. Normalization bootstraps
from ten minutes ago; NPM initially reads at most the last MiB of each recent,
uncompressed access file. Skipped bootstrap bytes are reported, not presented
as complete history. Rotation positions use device/inode and byte offsets.
Normal Docker log polling overlaps two minutes to tolerate ordinary delivery
delay, deduplicates replayed IDs, splits saturated time windows, and refuses to
advance a checkpoint if it cannot ingest a window completely. Logs arriving
later than the overlap can be missed. Source-format changes require parser
updates; a successful quiet query does not prove that the source is logging.

Loki's normalized log timestamp is **collection time**, with original event time
kept in the JSON and details. Window filtering and counters therefore use when an
event was observed, including ordinary catch-up after outages. **No historical
backfill, counter reconstruction or relaxed Loki ingestion limits are used.**
Existing normalized logs stay in place; the API applies own-network filtering to
older unlabeled records at read time, rather than rewriting or re-importing them.
Current home prefixes cannot identify a previously used, now-unknown ISP prefix.
Delivery is at-least-once; replayed IDs are deduplicated in the UI and never
re-increment persistent counters. The outbox holds at most 50,000 events and
applies explicit backpressure rather than silently dropping on overflow.

IPs, usernames, URLs, network organizations and key fingerprints are **never Prometheus labels**.
Metric dimensions are bounded kind/type/country/origin codes. Logs drop URL queries,
fragments, long token-like path components, raw messages, cookies, passwords,
and request bodies. Existing upstream raw Loki logs retain their existing policy.
The normalized events still contain private activity: protect the entire site,
including every `/api/` endpoint, with Authelia.

## Local preview and regression checks

```powershell
uv sync --project attacks
uv run --project attacks python attacks\server.py --port 8786
uv run --project attacks python -B -m unittest discover -s attacks -p 'test_*.py'
npm --prefix attacks test
```

The checked-in geometry bundle and atlas files need no Node build at deployment.
To regenerate them: `npm --prefix attacks ci`, then
`npm --prefix attacks run build:map` and `npm --prefix attacks run build:atlas`.
The latter downloads only the three pinned public Natural Earth datasets and
verifies that the requested microstates/territory have real polygons. Globe
rendering is split in two so dragging and zooming stay cheap even at 1:10m:
`static/globe-draw.mjs` converts each border and graticule line once into unit
vectors (subdividing long edges so they follow the great circle) and then, on each
frame, rotates only what can reach the viewport, clips it at the horizon and writes
integer path coordinates at a scale picked from the zoom. Marker sizes come from
the layout's own scale instead of asking the browser to measure on every frame.
A module worker (`static/atlas-worker.mjs`) decodes each detail level and builds its
flat-map paths off the main thread, and the next finer level is prepared shortly
after a zoom so crossing the threshold does not stall a gesture. After the page
loads, the service worker downloads the 1:50m and 1:10m files once in the
background (about 5 MB), so later zooms and offline use read them from cache. The atlas build also generates `static/atlas.mjs`, the shared
filename manifest used by the page, and rewrites the copy inlined in the classic
service worker (`static/sw.js`); a test fails if the two differ.

On a Linux Docker host, `uv run --project attacks python
attacks/integration_check.py --image attacks:local` exercises real isolated
Loki/Prometheus/collector/API containers with synthetic source logs. It creates
an internal test network and temporary state volume, publishes no ports, and
removes the test containers/network/volume afterward. It never writes to the
production monitoring services.
If Docker's default address pools are exhausted, supply `--subnet` with an
explicit test subnet verified not to overlap existing networks or routes.

Visit `http://127.0.0.1:8786/?demo=1` for the explicitly synthetic design preview.
It starts with 35 fabricated events and then simulates a live stream of arrivals
(occasional bursts included) so the flash and fade can be judged without real
traffic; add `&simulate=0` for a static, deterministic page. Every address is
inside an RFC 5737 documentation range. Without `demo=1`, unavailable backends
show errors, never fabricated events.
The API binds loopback by default; Docker explicitly selects `0.0.0.0`.

## Deployment

First deployed on Calcifer on **2026-11-24**, with existing Loki/Prometheus and
admins-only Authelia two-factor protection. History builds from collection;
the demo remains an explicitly synthetic local/design mode.

These are activation steps for an approved checkout containing this feature.
Like ChasEx, `compose.yml` is an
independent deployment using **existing** `compose_proxy` / `compose_monitoring`
networks, not a new `docker_proxy` network or the nightly main Compose updater.

1. Apply the Nix configuration through the normal guarded rebuild procedure.
   The flake must include the new tracked module and Python sources. This installs
   `attacks-connections.service`, the public-key registry, and the unprivileged
   intelligence updater/timer. It does not change
   SSH authentication or open any ports. `systemd.services` is an attribute set
   of service submodules; `serviceConfig` carries validated systemd settings.
   `environment.etc.*.text` is nullable lines and `mode` a string, verified
   against nixpkgs' option definitions. `systemd.timers` is an attribute set
   of timer submodules, default `{}`; `timerConfig` is an attribute set of
   systemd unit-option values, also default `{}`.
2. Create collector directories with ownership matching container UID/GID 65534:

   ```sh
   sudo install -d -o 65534 -g 65534 -m 0750 /srv/docker/data/attacks/state
   ```

3. Run the initial intelligence refresh before starting Compose; its bind mount
   deliberately refuses to create a missing host directory:

   ```sh
   sudo systemctl start attacks-intelligence.service
   systemctl status attacks-intelligence.service --no-pager
   ```

   The service installs `GeoIP.mmdb`, `ASN.mmdb` and `networks.json` into its
   systemd-managed state directory. The collector mounts it read-only and
   reloads within 60 seconds. The web container never mounts these files.
   Subsequent refreshes are automatic. Missing data is visible; events still
   work without invented coordinates or provider names.
4. Validate and recreate **only Alloy**, from the main Compose entry point,
   to activate the journal mounts/filters. Check that the fixed sshd, fail2ban,
   and capture source streams reach Loki. Keep Alloy's existing Docker broker
   restrictions. Reload the validated Prometheus scrape configuration with
   SIGHUP if its mounted file matches the host file. Git can replace the inode
   while the container keeps the old bind mount; in that case restart only
   Prometheus to remount it, then verify the `attacks` scrape target. The new
   target is unavailable until the collector is started. Recreate only
   Endlessh through the main Compose entry point to apply its dual-stack
   network; this interrupts existing honeypot sessions, not real SSH.
5. From the repository root, validate/build/start the independent deployment:

   ```sh
   docker compose --env-file docker/.env -f attacks/compose.yml config --quiet
   docker compose --env-file docker/.env -f attacks/compose.yml build
   docker compose --env-file docker/.env -f attacks/compose.yml up -d
   ```

6. In the existing Authelia configuration, add `attacks.danteb.com` to an
   **admins-only two-factor** rule, with an explicit deny rule for other users.
   Preserve existing rule order and policy. Validate/reload it through the
   established Authelia workflow. Do not weaken the rule if the site fails.
7. Run `sh attacks/setup-proxy.sh`. It checks admin/non-admin policy, creates an
   NPM host using a certificate covering this hostname, and refuses to overwrite
   an unexpected existing host. It reuses the established Authelia snippets and
   NPM credentials already available in `bmc-ip-monitor`; none are copied into
   this app. No DNS/router changes are needed. Only the PNG home-screen icons
   bypass Authelia, because iOS fetches them without the SSO cookie. Rerunning
   the script upgrades a host still on the previous config.
8. Verify anonymous API requests cannot retrieve telemetry, non-admin users
   are denied, and an admin with 2FA can use the UI. Check all collection health
   rows, Prometheus's target, map geolocation, one harmless Endlessh connection,
   and an authorized SSH login with a matching fingerprint. Do not deliberately
   guess passwords on a real account or weaken SSH for a demonstration.

Updating the independent app uses the same explicit build/up commands. Reverting
the Nix module and removing its import stops future capture; remove the private
NPM host, the three Alloy journal components/mounts, Prometheus target, and
Homepage entry when fully retiring it. Preserve state if lifetime counters must
survive a rollback. Existing SSH, fail2ban, Endlessh and public services remain
independent of this dashboard.
The Nix module also owns the intelligence timer; its state is public bulk data.
When changing cached asset membership, update `sw.js` and increment its cache
version. The worker deletes only its own obsolete `attacks-shell-*` caches.

## Map sources

Country geometry: Natural Earth's public-domain
[v5.1.2 Admin 0 country data](https://github.com/nvkelso/natural-earth-vector/tree/v5.1.2/geojson),
at 110m, 50m and 10m;
[terms](https://www.naturalearthdata.com/about/terms-of-use/).
Equal Earth: Šavrič, Patterson and Jenny (2018);
[PROJ reference](https://proj.org/en/stable/operations/projections/eqearth.html).
The UN General Assembly's [A/RES/80/307](https://digitallibrary.un.org/record/4127777)
(4 September 2026) encourages Equal Earth and other equal-area projections where
relative continental size matters; it does not prescribe one map for every use.
DB-IP Lite attribution is visible on the page, as required by CC BY 4.0.
Flag emoji use a self-hosted regional-indicator subset of Google Noto Color
Emoji, obtained through the Google Fonts CSS API. Its SIL Open Font License is
vendored as `static/flags-LICENSE.txt`; the browser never contacts Google Fonts.
The radar favicon and matching 180/192/512-pixel app icons are original artwork.
D3 Geo, Versor and TopoJSON Client are bundled locally, with their dependency
licenses in `static/geo-vendor-LICENSE.txt`. No external tile server, API key,
browser CDN request or WebGL dependency is needed.
