# Server Atlas

A local-first, dependency-free prototype for mapping the ROMED8-2T's connectors
to the hardware actually installed in the server. No deployment, server
connection, credentials, analytics, fan control or remote writes.

## Run

From the repository root:

```powershell
uv run --no-project python -m http.server 8765 --bind 127.0.0.1 --directory hardware-map
```

Open <http://127.0.0.1:8765>. Use HTTP rather than opening `index.html` directly:
the app uses native JavaScript modules. Any static HTTP server works.
Tests require Node.js and no packages:

```powershell
node --test hardware-map/model.test.mjs
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
- Compact top category buttons and connector search enter connector focus.
  Hardware dims and is disabled for pointer/keyboard selection; nonmatching
  connectors also dim and cannot intercept clicks. Choosing a category only
  filters the map; it does not open a popup. **Hardware** restores component
  selection. The compact **Connector list** provides searchable keyboard
  alternatives to the visual. Fan headers retain verified **logical** six-pin details.
  The manual-oriented board coordinates are rotated 180 degrees so rear I/O
  is on the right, with schematic spacing and upright labels. The landscape
  chassis is not a physical pin-orientation reference.
- Annotate connection target, confidence, physical occupancy (including blocked slots), evidence source
  and notes. Confirmed and inferred connections require evidence.
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
  interpolation demonstration. There is no live refresh.

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
| Photo-inferred, revised November 13 | Three exposed slots between DIMMs and GPU in IMG_4537 support the user's revised **GPU likely in PCIE4**, with PCIE7/6/5 empty and cooler apparently covering PCIE3/PCIE2. Slot labels are unreadable: PCIE4 is **not confirmed**. The earlier PCIE3 assignment and PCIE4-free report are superseded. |
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
photo-inferred PCIE4 GPU placement, confirmed PCIE1 HBA placement and apparent
PCIE3/PCIE2 obstruction, not measured cooler footprints.
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
  sensor snapshot or copied onto six physical fans.

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
