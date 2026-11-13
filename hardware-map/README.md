# Server Atlas

A hardware map and read-only live monitor for the ROMED8-2T server. The
dependency-free browser UI also works as an explicitly synthetic local demo.
No fan control, analytics or browser-side credentials.

## Run

From the repository root:

```powershell
uv run --no-project python -m http.server 8765 --bind 127.0.0.1 --directory hardware-map
```

Open <http://127.0.0.1:8765>. Use HTTP rather than opening `index.html` directly:
the app uses native JavaScript modules. Any static HTTP server works.
Tests require Node.js and no packages:

```powershell
node --test hardware-map\model.test.mjs hardware-map\metric-model.test.mjs
node --test hardware-map\live-data.test.mjs
```

## Live service

The deployed Python server marks the page **LIVE**; a static HTTP server marks
it **DEMO**. API errors never fall back to fabricated values. `?demo=1` is an
explicit synthetic-mode opt-in. The existing inspection annotations and their
browser-local storage remain separate from telemetry.

A root **host collector**, without a network listener, reads `/proc`, sysfs,
`lsblk`, read-only LVM metadata, SMART, local IPMI and NVIDIA counters. It writes
atomic private files under `/var/lib/server-atlas` every five seconds. Slow
inventory/IPMI refreshes run separately; SMART polls every five minutes with
`smartctl -n standby` so sleeping disks are not deliberately awakened.
Per-source timestamps/expiry accompany cached measurements. Unsupported or
failed readings stay unavailable; GPU 3D/copy/shared memory are not invented.
Rear RPM remains an explicit 2000-RPM
assumption; FAN3 remains one shared hub tach, not six measurements.

CPU package power uses the existing read-only
[powercap energy counters](https://docs.kernel.org/power/powercap/powercap.html):
microjoule delta divided by monotonic elapsed time. Only package domains count,
not their nested core domains. The first interval, resets, changed ranges,
unreadable counters and long sampling gaps remain unavailable. This is average CPU
package power, not instantaneous power, TDP or whole-server wall draw.

Cache occupancy and dirty data use
[`dmsetup status --target cache --noflush`](https://docs.kernel.org/admin-guide/device-mapper/cache.html).
The collector finds the `/data` cache through its actual mapper dependencies,
and converts block counts using the reported size in 512-byte sectors.
Resident blocks describe a warmed cache; dirty blocks differ from the origin.
A nearly full cache is normally useful, unlike a nearly full filesystem.
Capacity comes from active cache status, not LV allocation size. Metadata
`needs_check` or read-only state is surfaced for operator attention.
Neither source changes cache policy, flushes metadata, loads a driver, changes
power limits or alters device permissions. Upgrading the root collector needs
sudo; a web-only update cannot activate these new host readings.

The unprivileged, read-only `server-atlas` container serves only allowlisted
static files and GET/HEAD APIs. It mounts collector state read-only, has no
Docker socket or hardware devices, and publishes no host port. It joins the
existing `compose_proxy` and `compose_monitoring` networks. A separate Compose
project deliberately keeps this pinned feature deployment independent of the
main project's nightly updates and network ownership.

**History reuses the existing Prometheus 90-day TSDB**, with a 15-second Atlas
scrape. Bounded API queries accept registered channel IDs only, never raw
PromQL. Long windows return at most 301 points; missing/stale scrapes stay gaps,
not zeroes or invented backfill. CPU/disk/NIC rates handle counter resets.
Disk series use private stable-identity hashes, so Linux device renumbering
does not silently splice another disk's history onto a series.

**Provisional disk placement:** initial disk serials are lexicographically
sorted and assigned to sorted installed slots (three cages, bays 1–4; M2_1/2).
Private `assignments.json` preserves those assignments across renumbering;
absent devices retain their reserved slots and new identities use unused ones.
Unknown/duplicate identities are not assigned. Labels, popups and card leaders
explicitly distinguish this arbitrary mapping from physical verification.
Raw serials/WWNs never belong in the repository or public demo fixture.

Deployment source is a committed clone under `/srv/server-atlas/source`.
As root, run `hardware-map/deploy.sh`. It builds only the collector's Nix unit
closure, installs it in the host's supported persistent
`/usr/local/lib/systemd/system` search path (including a multi-user wants
symlink), and retains the closure with `/srv/server-atlas/collector-unit`.
It does **not** switch the whole NixOS generation or restart unrelated units.
The imported Nix module is the declarative equivalent for future rebuilds.
Do not install both competing unit versions; the installer refuses to replace
an already NixOS-managed unit. The Docker service has `restart: unless-stopped`.

Before exposing it, add `server-atlas.danteb.com` to Authelia's **admins /
two_factor** rule, validate the configuration and restart only Authelia.
`hardware-map/setup-proxy.sh` uses NPM's supported API and existing private
monitor credentials, requires the existing wildcard certificate, and creates
the authenticated route. `/metrics` returns 404 at the public proxy.
The existing `docker/monitoring/prometheus.yml` includes the internal scrape;
validate with `promtool check config` and reload Prometheus with SIGHUP.
Until this feature branch is integrated, production has only the additive
Atlas scrape/dashboard blocks in its existing checkout; the running Atlas
release is pinned separately. Preserve those blocks during monitoring or
dashboard configuration changes. Private pre-change backups live outside Git
under `/srv/server-atlas/backups`.

Backend checks (synthetic fixtures, no real identifiers):

```powershell
uv run --no-project python -B -m unittest discover -s hardware-map\server -p "test_*.py"
```

## What works

- Explore a wide landscape chassis view with selectable installed hardware:
  EPYC under its NH-U9 cooler, reported populated DIMMs, GPU, HBA, bare M.2
  drives, HX1000i, three front/three middle/two rear case fans, and 12 HDDs
  in a 15-bay count illustration. The near-full-window map is the default:
  no large header, status cards, navigation tabs or permanent details section.
- Clicking hardware or a connector opens a native modal popup. **Close**,
  **Escape** and backdrop clicks dismiss it without changing map zoom,
  category/search or scroll position, and return focus to the opener. Related
  connector buttons navigate within that same popup, without changing the map's
  category. Escape does not leave the map or change visualization mode.
  Unsaved annotation fields prompt **Keep editing** or **Discard edits & close**
  rather than trapping the user. Saved/tab-only annotations remain intact.
  Keyboard focus stays inside the open dialog; mobile popups scroll internally
  and keep their close control visible.
- **Tools & info** holds connection counts, fan-planning limits, reference and
  inspection notes, JSON import/export, telemetry and inventory. These remain
  available without surrounding the map. A connector popup also offers export
  for saved/tab-only annotations, including recovery after a storage failure.
- **Fan motion** previews six artistic case-fan stages: stopped, slow, medium,
  fast, very fast and maximum. The slow stage uses unchanged blades with gentle
  rotation; medium/fast/very-fast/maximum use 12/18/24/36 evenly spaced curved
  blade impressions and subtle tip streaks, fading toward a translucent disc.
  These are stylized exposure **multiples**, not the physical blade count or
  shutter-accurate motion blur. Periods are 2.2/1.25/0.9/0.75 seconds, keeping
  maximum's previous timing. Frames and hubs remain stationary.
  The chooser shows animated examples, applies a stage to all eight case fans,
  or compares all stages on the map (including rear-fan examples).
  Manual stages are labeled **DEMO**; they are not telemetry or fan control.
  **Use displayed RPMs** restores data-driven bands: the six front/middle fans
  share the synthetic hub RPM under the user's shared-speed assumption, and
  both rear fans use an explicitly assumed constant 2000 RPM. **Reported
  ~1100 RPM snapshot** uses the existing approximate FAN3 observation instead.
  This does not turn the other five hub fans into independently measured fans
  or add tach monitoring to the rear pair. CPU/GPU artwork, real reading labels,
  saved annotations and export data are untouched.
  Reduced-motion preferences initially disable rotation but retain distinct line
  patterns; **Spin fans** explicitly overrides that preference for this session.
  The same control can pause motion without changing the displayed speed stage.
  Filtered-out fans and closed chooser previews pause their animations.
  `fanMotionForSpeed` accepts a normalized RPM / rated-maximum fraction for a
  data adapter. Missing/invalid values stay unknown; only explicit zero
  selects stopped. Positive values choose five moving bands through maximum
  (overspeed uses the maximum illustration). These are stylized periods, not
  physical RPM, PWM duty, airflow or a thermal simulation. Sharing the hub RPM
  is an explicit visualization assumption and cannot detect a failed branch.
  Technique references: [rendered motion blur / exposure](https://docs.blender.org/manual/en/latest/render/cycles/render_settings/motion_blur.html)
  and [animation smear frames / multiples](https://blog.cg-wire.com/smear-frames/).
- Compact **Hardware / Connectors** controls choose what the category chips and
  search filter. Hardware categories cover compute, memory, storage, cooling,
  expansion cards, power, chassis and motherboard, including off-board parts.
  A part can belong to multiple categories (for example the HBA is storage and
  expansion). Nonmatching parts dim and cannot intercept pointer/keyboard
  selection; matching parts still open their details. **All hardware** restores
  all component targets. Search matches part labels, models and categories.
- **Linux devices & layers** appears in HDD, HBA, M.2, network-port and related
  connector popups. Click a Linux name to traverse partitions, RAID, VG/LV,
  internal cache/origin devices, filesystem and bond relationships within the
  same popup. Aliases identify multiple names for one object, not extra disks.
  The dated read-only snapshot currently shows `/dev/sde1` as the hot spare,
  11 in-sync RAID6 members and `enp66s0f1` as `bond0`'s active-backup active link.
  The spare is explicitly standby, not an active stripe-bearing member.
  `nvme0n1` holds the OS; `nvme1n1` backs both cache and ordinary `/data` extents.
  The latter means the data LV is **not entirely RAID-protected**. Privileged
  LVM metadata was unavailable: exact extents and current cache mode are not
  claimed from this inspection.
  Bay-to-disk, M.2-to-NVMe and LAN1/LAN2-to-interface mappings remain unassigned;
  no device is assigned from list order, PCI function order or old A/B sensors.
  The separate AMI USB virtual NIC is not the dedicated BMC LAN socket.
  `linux-snapshot.mjs` separates observed nodes, dependencies, RAID membership,
  bond roles and physical associations. `buildLinuxTopology(snapshot)` derives
  current roles anew, so replacing a future snapshot can change spare/active-link
  assignments without changing inspection annotations. No live endpoint,
  automatic polling, deployment or write/control operation is added here.
  Kernel names are temporary snapshot aliases. A future private collector needs
  stable identities and explicit physical bindings; serials/WWNs/MACs/IPs and
  credentials must not be added to this public fixture. Refreshes must collect
  RAID member **state and slot**, not mistake mdadm's bracketed device number
  for the active array slot, and retain collection timestamps/non-atomic limits.
  Comma-separated state flags are retained; a `spare` assigned to a recovery
  slot is not labeled an idle hot spare. See the [kernel MD state/slot reference](https://docs.kernel.org/admin-guide/md.html).
  **Connectors** retains the motherboard's original category filters and search.
  In connector mode, hardware dims and is disabled for pointer/keyboard selection; nonmatching
  connectors also dim and cannot intercept clicks. Choosing a category only
  filters the map; it does not open a popup. **Hardware** restores component
  selection. The compact **Connector list** provides searchable keyboard
  alternatives to the visual. Fan headers retain verified **logical** six-pin details.
  The manual-oriented board coordinates are rotated 180 degrees so rear I/O
  is on the right, with schematic spacing and upright labels. The landscape
  chassis is not a physical pin-orientation reference.
- Annotate connection target, confidence, physical occupancy (including blocked slots), evidence source
  and notes. Confirmed and inferred connections require evidence.
  Connector outlines, list indicators, detail badges and the Tools summary use
  **occupancy**, not confidence: teal = connected, pale gray = empty,
  amber/dashed = physically blocked, muted/dotted = unverified. Selection adds
  a glow without changing the state color. Unknown occupancy is never assumed
  empty; confidence/provenance remain recorded in details and JSON.
  Inspection defaults distinguish photo-confirmed, photo-inferred, uncertain
  photo, user-confirmed, user-reported and unverified observations.
- Fan-planning counts separate confirmed-free, confirmed-occupied and
  unverified headers. Inferred availability and missing tach readings never
  count as verified free. Seven headers, fourteen possible tach inputs,
  actual fan count and independently controllable groups are different things.
- Save to browser local storage; import/export versioned, validated JSON.
  Notes do not leave the browser. Export a backup: clearing browser data or
  changing the origin/port creates a different workspace. Import replaces,
  rather than merges, the saved connection annotations. Current inspection
  defaults fill missing connectors, but never overwrite an imported or saved
  annotation, even an explicit unknown. The supplied inspection record remains
  separately visible beside your editable annotation.
- Inspect explicitly dated observed snapshots, reported capacities and
  unknowns. Separately opt into synthetic telemetry and an air-temperature
  interpolation demonstration. These inspection snapshots do not live-refresh;
  the performance overlay uses the separate live API when deployed.

Do not put credentials, serial numbers, MAC addresses or other sensitive
details in public exports or commits. User annotations are private browser
data unless deliberately exported. Imported evidence/confidence is an assertion
by the file's author, not independent verification. Invalid saved data is not
silently overwritten; import a valid export to replace it. A change from another
tab blocks saves until reload to reduce accidental overwrites.

## Cleaning inspection and fan replacement, November 12–13, 2026

Initial inventory evidence was relayed by the coordinating session; the
November 13 walkthrough adds Dante's direct confirmations. Private
inspection photo sheets were also viewed for this UI revision's colors and
general case arrangement: green PCB, black/blue slots, silver chassis and
heatsinks, dark cards/fans/PSU, beige/brown Noctua frames. This does not upgrade
reported connections to confirmed ones. No photos or identifying serial
numbers are bundled.

The six front/middle BoK fans were replaced on November 12. Their earlier
Molex chain A and the empty-FAN3 photo are historical evidence, not the current
installation. The replacement details are user-installed/reported; the later
FAN3 tach is a relayed BMC observation, not an independent cable trace.

| Provenance | Observation |
| --- | --- |
| Photo-confirmed | Board silkscreen `ROMED8-2T REV 1.03`; GPU label `GV-N207SGAMING OC-8GD rev 1.0` in IMG_4548. The earlier extra zero in the GPU SKU was a transcription error. |
| User-confirmed, November 13 | User explicitly accepts the reviewed PCIe mapping as confirmed: **GPU in PCIE4**, **PCIE5/6/7 empty**, cooler covering **PCIE3/PCIE2**. This follows the three exposed rows in IMG_4537 and the manual; it is user confirmation, not a new readable-label photo. Earlier PCIE3 electrical assignment and PCIE4-free report are superseded. |
| User-confirmed | HBA in PCIE1, directly at the GPU fan intake. Candidate model is **SAS 9300-8i**, still user-suspected rather than label-confirmed. Firmware/mode is not established by this candidate identification. |
| Photo-confirmed | Both M.2 sockets right of PCIE7's end contain bare Samsung 2280 drives without heatsinks. Drives run perpendicular to the slots across the PCIE6→PCIE2 rows. Both onboard SATA connectors appear cabled; logical A/B identities and cable-to-drive routing remain unknown. |
| Photo observation, unmeasured | GPU shroud overhangs both M.2 drives with a visible gap estimated as a few mm. This is not a measured clearance or a verified heatsink allowance. Drive outlines in the schematic show orientation, not dimensions or exact shroud extent. |
| User-confirmed, November 13 | Both SSDs are **Samsung 990 EVO 2 TB, MZ-V9E2T0B**. Logical A/B telemetry-to-socket bindings remain unknown. |
| Photo-confirmed, November 13 review | IMG_4538 supports ATXPWR1 24-pin occupied, ATX12V1 EPS 8-pin occupied and ATX12V2 four-pin empty. The PSU-side 18+10-pin plugs are split ends of the motherboard ATX cable. |
| User-confirmed, November 13 | GFX_12V1 is empty. This is the motherboard auxiliary socket, not the GPU card's power input. |
| Photo-confirmed | Existing Noctua four-pin plugs on FAN1/FAN2 are seated on pins 1–4. This verifies those particular plugs' in-situ fit, not universal compatibility or physical keying. |
| Historical photo-confirmed and user-confirmed | FAN3 was empty/free in the cleaning photo; FAN3 / LED_FAN3 silkscreen is visible. Superseded by the subsequently reported hub connection below. |
| User-confirmed, November 13 | FAN4–FAN7 are all visibly empty. This supersedes the earlier photo-inferred empty status; the confirmation is from physical inspection/photos, not missing tach readings. |
| User-confirmed, November 13 | Four **Kingston KSM32RD4/32HDR**, **32 GB each**, in **A1/B1/G1/H1**; **C1/D1/E1/F1 empty**. 128 GB is the total, not a single module's capacity. Rated DDR4-3200 does not establish current running speed. Original NH-U9 cooler fans use FAN1/FAN2. Case front USB cable is on USB3_3_4. |
| User-confirmed, November 13 | Rear LAN1/LAN2/dedicated BMC LAN are connected; no rear USB, display or serial devices. Switch destination was previously reported. The PSU AC cord is separate. `REAR_OTHER` is a logical group, not a vendor designator. |
| Historical user-reported wiring, photographed label | Former Molex chain A: six BoK BDM12025S fans, 120 mm reported, 12 V / 0.10 A per label; three front plus three middle. Replaced on November 12; no longer the installed front/middle inventory. |
| User-installed and reported, November 12 | Six Noctua **NF-P12 redux-1700 PWM**, **120 × 25 mm**, three front plus three middle. Rated maximum **1700 RPM / 0.09 A** per fan; specifications are not measurements. Micro Center SKU 062398. Hub-port mapping beyond the subsequently identified tach-return fan remains untraced. Redux light-grey frames/darker cool-grey blades follow the supplied product photo; the beige/brown CPU cooler and the rear pair retain their prior appearance. No vendor photo is bundled. |
| User-installed and reported; wiring/location confirmed November 13 | All six redux fans use a **Thermalright ARGB 8 Group Fan HUB/Controller**, Mfr part **ARGB FAN HUB X8**, Micro Center product 710163 / SKU 025247. A **dedicated PSU SATA harness** supplies it; PWM/tach lead on **FAN3**. Hub lies between motherboard and middle fan wall, near case centerline and FAN1–FAN3; exact coordinates are approximate. Other per-port mappings remain untraced. Product name does not establish an RGB connection. |
| User-confirmed, November 13 | The hub lead is on FAN3, seated like the FAN1/FAN2 plugs with two of six pins exposed. The PSU-side middle fan, **middle-fan-3**, supplies the hub's single tach return. Only that physical fan is bound to the FAN3 snapshot in its popup; the other five speeds remain unmeasured. Other hub-port assignments remain untraced. In-situ fit does not establish universal keying. |
| User-confirmed, November 13 | All six redux fans blow front to rear. Both rear fans exhaust out the back. Both CPU-cooler fans are the originals supplied with the NH-U9 TR4-SP3 and move air **from the PSU side toward the GPU side**, not front to rear. These are confirmed orientations, not measured airflow rates or thermal simulation results. |
| Relayed BMC observation | FAN3 is approximately **1100 RPM**; the hub passes back **one tach**, not six individually measured fan speeds. Exact capture time is unavailable; the relay was received November 13. BMC lower alarm is reported as **100 RPM**. No live query or control change was made for this update. |
| Manufacturer chassis specification + user-confirmed original fans | Molex chain B: two rear **80 mm** BoK fans. The [Rosewill RSV-L4500U manual](https://c1.neweggimages.com/IMAttachment/UserManual/User%20Manual-1741922402096.pdf) specifies rear 80 mm fans, and the user confirms both are factory-original. Width is specification-based, **not photo-measured**. Thickness and exact model remain **UNVERIFIED**; `BDM180255` is only a tentative transcription. Molex wiring and label 12 V / 0.1 A / 2000 RPM are reported; rated RPM is not a measurement, and no tach is connected. |
| Listing-based PSU identity | Corsair HX1000i **CP-9020259-NA / RPS0131 family**. Identification is listing-based, not read from the installed label. The current retail title does not establish a newer ATX certification for this unit. |
| User-confirmed, November 13 | **Three separate SATA power harnesses, four HDDs each**; a **fourth SATA harness dedicated to the hub**; **one separate Molex harness for both rear fans**. This supersedes the old one-harness-for-12-HDDs suspicion and stale port counts. Individual PSU port IDs, cable part numbers, load limits and spare-port counts remain unverified. **PSU USB/iCUE is not connected**. Do not infer modular-cable compatibility from connector shape or package quantities. |
| Photo-confirmed / inferred | IMG_4570 shows **PANEL1** with readable **POWER SW** and other switch/LED plugs. The red/white/green/black lower-edge flat cable is likely part of that loom; exact continuity and individual pin assignments remain untraced. The earlier USB 2.0 suggestion was not established. |
| User-confirmed, November 13 | **12 installed HDDs**, three five-bay cages, **bottom bay empty in each front-view left/center/right cage**. Each cage contains four drives; no drives being added. Logical-drive-to-bay and individual data-cable mapping remain unknown. |
| User-confirmed, November 13 | **No separate temperature probes** on TR1/TR2. Component-temperature snapshots are not air measurements. |

User-reported occupied headers remain inferred rather than independently
confirmed unless explicitly user-confirmed. For an unmodified inspection map,
fan-planning counts now show **four confirmed-free headers (FAN4–FAN7),
three confirmed occupied headers (FAN1–FAN3), and none with unverified occupancy**.
FAN1/FAN2 plugs are photo-confirmed; the user explicitly confirms FAN3's hub
lead and FAN4–FAN7's empty state in the November 13 walkthrough. The one hub
tach is bound to middle-fan-3 using the user's physical identification, not
deduced from the RPM reading. Electrical limits, universal connector keying
and independent BMC control groups are still not established by occupancy.
The six front/middle fans use reported SATA hub power plus FAN3 control/tach;
the unchanged rear pair remains unmonitored on Molex chain B.
Aside from the relayed FAN3 tach, no new telemetry, rear-fan thickness or exact
rear-fan model is inferred. HDD harness grouping is confirmed, but individual
power connector/cable part-number and logical-drive-to-bay bindings are not.
Existing saved/imported annotations still take precedence over defaults;
the latest supplied FAN3 record is visible separately without overwriting notes.

### Chassis drawing boundaries

The front is on the left and rear I/O on the right. Component and case-part
positions, dimensions and mounting offsets are approximate, even when the
component's identity or electrical slot is confirmed. GPU/HBA shapes illustrate
user-confirmed PCIE4 GPU placement, PCIE1 HBA placement and PCIE3/PCIE2
obstruction, not measured cooler footprints.
Connector focus reveals sockets visually; it does not mean they are physically
accessible beneath a card. M.2 outlines retain their perpendicular-to-slot
direction; NVMe A/B readings are not assigned to a socket.

Fan faces are unfolded for recognition, not shown at their physical mounting
angles. Airflow directions come from user confirmation, not geometry. The three
front-view cages are unfolded down the scene; each has four filled bays and an
outlined bottom bay per the walkthrough. Logical disk identities, exact cable
routes and clearances are not inferred. Saved/imported annotations are preserved
unchanged; this is not a schema migration.

### Part documentation

Each physical part's popup links its manual or datasheet; inventory cards expose
the same references. URLs and qualifications live in `partReferences` in
`board.mjs`. Except for the explicitly qualified AMD download below, linked
PDFs were opened and matched to their stated product or family; vendor
files/artwork are not bundled. The references include the
Noctua cooler installation guide and redux specifications, exact Kingston
datasheet, Samsung 990 EVO revision 1.1 datasheet, WD Red Plus product brief,
Rosewill chassis manual and Corsair HXi manual for the CP-9020259 family.

The Gigabyte PDF is a **generic graphics installation guide**, accompanied by
the model-specific support page. The Broadcom 9300-8i guide is explicitly
**candidate-model documentation**, not proof of the installed controller.
Thermalright publishes an x8 hub PDF link, but it returned **HTTP 404** during
verification; its official product page is linked with that limitation instead.
No x8 IR variant documentation is substituted. Manufacturer specifications and
PDF references do not turn inferred hardware identities into confirmed facts.
AMD's published EPYC 7003 family PDF could not be retrieved by the validation
client; its link is labeled download-unverified and accompanied by the exact
7313P specification page.

## Sources and interpretation

- [Official ASRock Rack manual](https://download.asrock.com/Manual/ROMED8-2T.pdf),
  internal revision **1.30**, published **April 2026**. The first PDF page still
  says version 1.0 / February 2022; the revision page immediately following it
  identifies the current document. This is the same URL linked by the
  [original build spreadsheet](https://docs.google.com/spreadsheets/d/1a9_hTTfLwj4i5QM6DRrcjBHGdSeFhbTYq9LyS3mX0mE/edit).
  Verified download: 3,520,633 bytes, SHA-256
  `9ccde5548e447d1e74408a2bfe246450d8291c10bb250fc178df0e310775a613`.
- Layout identifiers: printed pp. 7–8 / PDF pp. 14–15. Fan pins: printed p. 30 /
  PDF p. 37. PCIE2 lane selection: printed p. 26 / PDF p. 33. Mini-SAS HD SATA
  connectors: printed p. 29 / PDF p. 36. Auxiliary CPU power: printed p. 31 /
  PDF p. 38. Thermal headers: printed p. 32 / PDF p. 39. Some internal
  cross-references in the manual still point at an earlier layout page.
- Reported inventory and logical storage layout come from the coordinating
  server-inspection session on November 12, 2026, not the outdated spreadsheet:
  RTX 2070 SUPER rather than RTX 3060; 12 HDDs rather than 16.
- Sanitized November 12 observations come from existing Prometheus hwmon
  metrics and read-only BMC sensor output. These were separate readings, not
  a synchronized capture; their timestamps are intentionally date-only.
  NVMe A/B label logical devices, **not** known M.2 sockets. Secondary NVMe
  sensor labels are retained without assuming which internal part they measure.
  BMC FAN1/FAN2 RPM identifies tach channels, not attached physical fans.
- The later FAN3 BMC return was relayed on November 13 with no exact capture
  time. It is shown separately as approximate, not backdated to the November 12
  sensor snapshot. The user subsequently requested applying that return to all
  six animations as an assumption, without claiming six measured readings.

The vendor PDF and any rendered reference images stay in private session
artifacts, not this public repository. All shipped visuals are original,
deliberately simplified schematics: no vendor artwork, scale guarantee,
physical pin-1 orientation or mounting/wiring instructions. Most connector
types deliberately have no pin-level map until independently checked.

### Fan connector boundaries

FAN1–FAN3 are the right-edge upper cluster, top to bottom, beside the lower
DIMM bank and OCuLink connectors. FAN4–FAN7 are the right-edge lower cluster,
top to bottom, below SATA_4_7. The schematic preserves this grouping while
deliberately simplifying distances.

The verified six-pin functions are: **1 ground, 2 fan supply, 3 primary tach,
4 speed control, 5 secondary tach, 6 not connected**. The original connector
reference visualization follows the manual's drawing, with pin 1 on the right
and two bars along the housing's top edge: the left bar reaches just past
pin 4's center, and the right bar starts just right of pin 3's center and ends
at pin 1's center. Their gap is roughly one pin wide, over pin 3. The manual's
text does **not** identify these bars as keying. Physical keying, pin-1
orientation and the cable mating-side view remain unverified; this is not a
board-rotation instruction. Confirm the actual header, never shift or force a plug.

Pins 1–4 match the usual four-pin PWM fan signal roles. Photos provide
in-situ fit evidence for the existing Noctua plugs at FAN1/FAN2 only;
generic mechanical compatibility and physical keying are not established
for every plug. The manual does not explicitly specify three-pin DC speed-control
support, independent control across seven headers, or the shared power
budget. It states a fan maximum of **5 A / 60 W**, without explicitly resolving
per-header versus combined limits. Cable/splitter ratings and startup current
still need checking. Do not use this ambiguous maximum as a shopping budget.
An extra tach input is not a second independently controlled fan output.

## Temperature estimates

The observed snapshot has **no verified, located air probes**. CPU, NVMe,
motherboard and LAN component temperatures are not air-temperature readings,
so no observed air overlay is produced.

Synthetic mode uses invented inlet/outlet air temperatures of 24/39 degrees C.
The sample slider performs piecewise linear interpolation along a normalized
front-to-rear axis. It excludes component sensors, stale probes, mixed
provenance, invalid positions and duplicate probe positions; it requires two
probes and never extrapolates beyond them. This is a visual estimate, **not CFD,
airflow measurement, a calibrated thermal model or a safe-temperature
prediction**. Even the airflow direction is an unverified assumption.

## Inspection checklist

With the system powered off and unplugged, photograph rather than rewire:

1. Board revision and wide top-down view with rear-I/O orientation.
2. FAN1–FAN7 labels and plugs; each cable's actual fan or splitter branches,
   fan model, power source, connector/keying, and airflow arrows. Six-pin
   headers can have two tach inputs; no reading does not prove an empty header.
3. GPU/HBA PCIe slot labels; HBA model; M2_1/M2_2 drive labels and heatsinks.
   Record the PCIE2 selection jumpers without moving them.
4. SATA_0_3 / SATA_4_7 breakouts and HBA-to-drive-bay routing; actual drive
   count, DIMM population, front-panel cables and any thermal probes.

Serial numbers are unnecessary. Leave untraced connections unknown.

## Synthetic performance study

The **SIMULATED** strip toggles CPU, memory, storage, GPU, network, temperature
and fan overlays independently. **All / None** shows or hides all layers;
**Metrics - DEMO** opens the performance lab, including explicit show/hide-all
temperature controls, individual chart visibility and layout reset. Drag a
card's grip, or focus it and use arrow keys (Shift moves farther). Charts can
move anywhere inside the visible background, including beyond the chassis and
SVG drawing bounds. Default placement avoids installed components, visible
connector outlines, fixed sensor badges and other cards, using clear perimeter
space before accepting overlap when space is exhausted. GPU/CPU cards get the
nearby open case space; NVMe and memory cards prefer the right perimeter, and
HDD charts prefer the left. Saved manual placements remain authoritative.
Temperature badges stay by their reference
hardware. CPU FAN1 sits on the PSU-side cooler fan and FAN2 on the GPU-side fan.
Case fans have one standardized readout per bank (front three, middle three,
rear pair), without duplicate per-fan numeric captions. Both three-fan badges
use the same FAN3 channel, not independent measurements. Snapshot/manual motion
previews update these bank readouts as well as artwork; histories remain
explicitly synthetic. Hide/show fan speeds also covers the GPU fan percentage.
Narrow screens and landscape windows up to 1800 px wide dock cards in a
horizontally scrollable tray instead of crowding the hardware. Hardware filters retain
only relevant overlays; connector inspection hides the overlay hit targets.
Click a chart title, sensor badge, or a component's performance button for
detailed graphs in a dismissible dialog.

Changing numbers occupy dedicated rows and fixed series columns, with tabular
digits and non-wrapping readouts. Capacity, clock and memory summaries keep
their label/value lines separate so updates do not resize cards or shift plots.

The lab includes CPU totals and 16-core/32-thread views, non-overlapping memory
composition and swap (including a swap bar on the memory card), physical-disk
busy time/read/write/latency/queue depth and a twelve-HDD comparison table,
prominent filesystem fullness, GPU graphics/copy/encode/decode/dedicated and
host-allocation graphs, network receive/send, and illustrative sensor/fan
histories. Hover a plot to inspect past samples. Choose mixed, idle, transcode
or transfer scenarios and windows from 1 minute to 24 hours; changing scenarios regenerates
the entire invented history. **Play / Pause** controls one-second updates.
Reduced Motion starts playback paused; Play is an explicit opt-in. Hidden
browser tabs do not advance the simulated clock. Default histories are CPU/GPU/
network 2 minutes, memory 15 minutes, temperatures 30 minutes, fans 5 minutes,
and storage 2 hours. Choices persist per view family rather than changing all
graphs together. Long histories use at most 301 point samples, not peak-preserving
aggregation or real retained measurements. A production collector should use
appropriate downsampling and retention; these synthetic histories need no server.

RX/TX and GPU-activity/encode overlays each share one explicit y-axis and
consistent displayed units. Activity axes default to the peak of all overlaid
series in the selected window plus the current reading, with zero baseline,
headroom and rounded limits. Small transfers use kB/s or B/s (and corresponding
bit units), rather than rounding to zero MB/s. Temperature plots use a padded
window range. Percentages stay 0–100%; memory, VRAM and storage amounts retain
their capacity scales, and clocks/fans retain reference scales.
**Layers → Graph y-axis scaling** switches back to fixed reference axes.
AUTO/FIXED labels and numeric axes make scale changes explicit; a throughput
axis ceiling does not claim link capacity. Old layouts default to adaptive
activity axes without discarding positions or annotations.

The GPU card separates its prominent used/total/percent VRAM allocation and
capacity-scaled VRAM history from the 0–100% engine activity/encode history.
Allocated memory can persist while engines are idle; it does not prove that
the GPU is busy. GPU power appears separately. 3D/copy/decode remain separate
detail plots. General GPU utilization
is neither 3D-only activity nor SM occupancy, and different engines must not be
summed. CPU details include temperature plus FAN1 (PSU side) and FAN2 (GPU side);
the card compares clock with the rated 3.7 GHz boost ceiling and 3 GHz base,
not a guaranteed all-core frequency. Network details include the shared onboard
LAN sensor, not invented per-port temperatures.

Sensor tooltips and detail notes distinguish component references from known
probe sites. CPU Tctl comes from internal processor sensors, not cooler/air
temperature, and is not automatically Tdie or the BMC CPU reading
([Linux k10temp documentation](https://docs.kernel.org/hwmon/k10temp.html)).
The GPU core reading belongs to GPU silicon. The motherboard MB sensor's
physical position is unknown; its badge explicitly marks an unknown-site board
reference. LAN references an original X550 outline near PCIE5/PCIE6 following the
official motherboard layout, not the RJ45 jacks; the exact BMC LAN sensor
implementation remains unverified. Each NVMe exposes its own SMART temperature
information, but composite/secondary channels are not guaranteed located
controller/NAND probes. Individual HDD SMART temperatures depend on
drive/controller support. NVMe and HDD badges remain grouped until physical
socket/bay assignments are verified.

GPU details and a shroud-side badge include one synthetic fan-speed percentage,
not invented RPM or three independently measured fans. NVIDIA
[NVML fan queries](https://docs.nvidia.com/deploy/archive/R535/nvml-api/group__nvmlDeviceQueries.html)
report **intended speed** as a percentage; this does not prove physical rotation.
The demo uses a 0–100% graph scale; it is not a universal NVML bound.
Actual fan channel count, RPM support and zero-RPM behavior on this GPU/driver
still need a later read-only capability check. No server query was made.

Two NVMe cards distinguish root/swap from `/data` cache **and ordinary extents**.
Both anchor to the M.2 group, without guessing socket assignments. Cache
occupancy is a synthetic used-block metric in this demo, not filesystem fullness or LV
allocation. Storage details trace the existing snapshot's partitions, mdadm,
volume groups, internal cache/origin LVs and mounts, preserving spare/member
roles. Raw HDDs have no individual filesystem-fullness percentage.

Temperature badges/plots use icons and colors for cold, cool, moderate, warm,
hot and dangerous. These component-specific **illustrative UI bands are not
verified vendor operating limits, calibrated warnings or a safety system**.

All performance values and histories are **synthetic, not live**. Linux names
come from the separate inventory snapshot, not fresh collection. HDD and NVMe
badges show group temperature ranges without assigning devices to bays/sockets.
FAN3 is one hub-return channel applied to six animations by user assumption;
rear RPMs are assumed constant, with no tach. Shared/host GPU memory uses an
illustrative graph scale, not a physical pool limit. Generic NVIDIA utilization
cannot be relabeled as 3D; unsupported Linux counters must remain unavailable.
There is no polling, collector, production service, fan control or deployment.

`metric-model.mjs` owns deterministic signals, channel metadata/ranges,
accounting, history generation and plotting/formatting helpers; `metrics.mjs`
owns the map/lab controls. Plotting preserves missing samples as gaps, not
zeroes. Preferences use the separate `homeserver.hardware-metrics.v1` browser
key: annotation storage, import/export and the observed snapshot are untouched.
Preference payload v2 migrates the existing visibility/layout choices without
changing inspection annotations.

Linux collection references: [per-interface statistics](https://docs.kernel.org/networking/statistics.html)
(including physical bond members) and [per-block-device I/O counters](https://docs.kernel.org/admin-guide/iostats.html)
(including mdadm's underlying disks). Rates require deltas and reset handling;
do not double-count stacked logical/physical layers. Future private identities
should prefer disk WWN/by-id or NVMe namespace identifiers, with serial/model
fallback, and each NIC's permanent hardware MAC plus PCI path rather than its
current bond-assigned MAC. Actual identifiers and SMART temperatures are not
newly collected or published here. [AMD's 7313P specification](https://www.amd.com/en/products/processors/server/epyc/7003-series/amd-epyc-7313p.html)
confirms the clock reference.

## Persistent-product foundation

The separation between board geometry (`board.mjs`), annotation schema and
interpolation (`model.mjs`), and browser UI (`app.mjs`) is intentional. A future
service can use the same schema with private server-side storage rather than
browser-local storage; keep Prometheus as the time-series system.

Next stages, **not implemented or deployed here**: an authenticated read-only
API with allowlisted Prometheus queries, stable sensor-to-component bindings
independent of changing device names, fresh/stale timestamps, and optional
IPMI/SMART/NVIDIA collectors. Existing metrics cover CPU/NVMe temperatures,
memory/filesystem capacity and mdraid state; no IPMI, GPU or SMART exporter was
found in the current scrape configuration. New collectors, Compose/NPM/
Authelia/Homepage integration and deployments require separate approval.
The frontend must never receive BMC credentials or unrestricted PromQL/network
access. Air estimates should remain unavailable until suitable probes,
locations and assumptions are documented.
