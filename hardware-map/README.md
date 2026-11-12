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
  in a 15-bay count illustration. Click hardware for its details and evidence;
  related connector buttons open the corresponding connection record.
- Use **Expand workspace** (Escape to exit) for a near-full-screen map and
  details panel. Zoom is independent of annotations. On narrow screens the
  map scrolls horizontally, with details below rather than crushed labels.
- Compact top category buttons and connector search enter connector focus.
  Hardware dims and is disabled for pointer/keyboard selection; nonmatching
  connectors also dim and cannot intercept clicks. **Hardware** restores
  component selection. Fan headers retain verified **logical** six-pin details.
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

## Cleaning inspection, November 12, 2026

Inventory evidence below was relayed by the coordinating session. Private
inspection photo sheets were also viewed for this UI revision's colors and
general case arrangement: green PCB, black/blue slots, silver chassis and
heatsinks, dark cards/fans/PSU, beige/brown Noctua frames. This does not upgrade
reported connections to confirmed ones. No photos or identifying serial
numbers are bundled.

| Provenance | Observation |
| --- | --- |
| Photo-confirmed | Board silkscreen `ROMED8-2T REV 1.03`; GPU label `GV-N2070SGAMING OC-8GD rev 1.0`. |
| User-confirmed, photo-consistent | GPU in PCIE3, with its 2.5-slot cooler physically blocking PCIE2. HBA in PCIE1, directly at the GPU fan intake. This supersedes the earlier unverified GPU-in-PCIE2 report. |
| User-reported | PCIE4–PCIE7 free. The schematic follows the manual: PCIE7 nearest CPU/DIMMs, PCIE1 at the bottom board edge. |
| Photo-confirmed | Both M.2 sockets right of PCIE7's end contain bare Samsung 2280 drives without heatsinks. Drives run perpendicular to the slots across the PCIE6→PCIE2 rows. Both onboard SATA connectors appear cabled; logical A/B identities and cable-to-drive routing remain unknown. |
| Photo observation, unmeasured | GPU shroud overhangs both M.2 drives with a visible gap estimated as a few mm. This is not a measured clearance or a verified heatsink allowance. Drive outlines in the schematic show orientation, not dimensions or exact shroud extent. |
| Uncertain photo | GFX_12V1 appears empty, not certainly. It is not marked confirmed-free. |
| Photo-confirmed | Existing Noctua four-pin plugs on FAN1/FAN2 are seated on pins 1–4. This verifies those particular plugs' in-situ fit, not universal compatibility or physical keying. |
| Photo-confirmed and user-confirmed | FAN3 is empty/free; FAN3 / LED_FAN3 silkscreen is visible. |
| Photo-inferred | FAN4–FAN7 appear empty under the GPU overhang, but are not confirmed-free. No tach reading is not itself proof of a free header. |
| User-reported | DIMMs in A1/B1/G1/H1; NH-U9 cooler fans on FAN1/FAN2; case USB 3 cable on USB3_3_4. |
| User-reported | LAN1, LAN2 and BMC LAN connected to the switch; no other rear I/O connections except PSU power. The other rear ports are a logical group, `REAR_OTHER`, not a vendor header identifier. |
| User-reported wiring, photographed label | Molex chain A: six BoK BDM12025S fans, 120 mm reported, 12 V / 0.10 A per label; three front plus three middle. None use motherboard headers or tach connections. |
| Manufacturer chassis specification + user-confirmed original fans | Molex chain B: two rear **80 mm** BoK fans. The [Rosewill RSV-L4500U manual](https://c1.neweggimages.com/IMAttachment/UserManual/User%20Manual-1741922402096.pdf) specifies rear 80 mm fans, and the user confirms both are factory-original. Width is specification-based, **not photo-measured**. Thickness and exact model remain **UNVERIFIED**; `BDM180255` is only a tentative transcription. Molex wiring and label 12 V / 0.1 A / 2000 RPM are reported; rated RPM is not a measurement, and no tach is connected. |
| User-reported | HX1000i PSU-side ports used: all motherboard ports, 1 CPU, 1 PCIe and 3 SATA/PATA. User suspects one SATA/PATA harness powers all 12 HDDs; upstream routing and splitter topology remain untraced. Two SATA/PATA feed the Molex fan chains. Free: 2 SATA/PATA and 4 PCIe/CPU. These counts do not verify electrical loads or individual internal board-header wiring. |
| User-reported | The observed case pin header is board-to-case, not a fan connector; its exact designator is unverified. |
| Photo-inferred | Red/white/green/black flat cable along the lower board edge under the GPU is possibly internal USB 2.0. No specific header, pinout or USB identity is confirmed. |
| User-confirmed | 12 HDDs is the true installed count; the case has 15 bays, leaving three empty. No drives are being added. Individual bay mapping and the locations of the empty bays remain unknown. |

User-reported occupied headers remain inferred rather than independently
confirmed unless explicitly user-confirmed. For an unmodified inspection map,
fan-planning counts show **one confirmed-free header (FAN3), two
photo-confirmed occupied headers (FAN1/FAN2), and four unverified headers
(FAN4–FAN7)**. Photo-inferred empty headers do not count as verified free.
The eight case fans use reported Molex chains, not motherboard headers.
No new telemetry readings, rear-fan thickness or exact rear-fan model are
inferred from these observations. HDD splitter topology remains untraced.

### Chassis drawing boundaries

The front is on the left and rear I/O on the right. Component and case-part
positions, dimensions and mounting offsets are approximate, even when the
component's identity or electrical slot is confirmed. GPU/HBA shapes illustrate
PCIE3/PCIE1 placement and PCIE2 blockage, not measured cooler footprints.
Connector focus reveals sockets visually; it does not mean they are physically
accessible beneath a card. M.2 outlines retain their perpendicular-to-slot
direction; NVMe A/B readings are not assigned to a socket.

Fan faces are unfolded for recognition, not shown at their physical mounting
angles or as verified airflow directions. Filled/outlined drive marks illustrate
12 occupied / three empty bays only, not a per-cage population claim. No
cable routing, actual bay identity, splitter topology or component clearance
is inferred from the illustration. Existing saved/imported annotations are
preserved unchanged; this is a visual revision, not a schema migration.

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
