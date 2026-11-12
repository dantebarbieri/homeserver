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

- Select board connectors with the original schematic, keyboard or searchable
  list. Fan headers have verified **logical** six-pin details.
- Annotate connection target, confidence, physical occupancy, evidence source
  and notes. Confirmed and inferred connections require evidence.
  Inspection defaults distinguish photo-confirmed, uncertain photo,
  user-reported and unverified observations.
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

These are relayed observations from the coordinating session, not a new
inspection of the actual photos by this app. No photos or identifying serial
numbers are bundled.

| Provenance | Observation |
| --- | --- |
| Photo-confirmed | Board silkscreen `ROMED8-2T REV 1.03`; GPU label `GV-N2070SGAMING OC-8GD rev 1.0`. |
| Photo-confirmed | GPU fan side directly above a low-profile HBA with two SFF-8643 cables. This does not identify their PCIe slot numbers. |
| Photo-confirmed | Both M.2 sockets populated without heatsinks; both onboard SATA connectors appear cabled. Logical NVMe A/B identities and cable-to-drive routing remain unknown. |
| Uncertain photo | GFX_12V1 appears empty, not certainly. It is not marked confirmed-free. |
| User-reported, unverified slot assignment | HBA in PCIE1 and GPU in PCIE2. A dual-slot card in PCIE2 could overlap PCIE1; await a slot-label photo instead of resolving this as fact. |
| User-reported | DIMMs in A1/B1/G1/H1; NH-U9 cooler fans on FAN1/FAN2; case USB 3 cable on USB3_3_4. |
| User-reported | LAN1, LAN2 and BMC LAN connected to the switch; no other rear I/O connections except PSU power. The other rear ports are a logical group, `REAR_OTHER`, not a vendor header identifier. |
| User-reported | Three front plus three middle fans, likely 120 mm, daisy-chained to an unknown endpoint. Two rear 80 mm fans are Molex-powered, fixed-speed, with no tach connection. |
| Unknown | FAN3–FAN7 occupancy; FAN4–FAN7 hidden under the GPU. The user's suspicion that they are empty and the lack of tach readings do not establish free headers. |

User-reported occupied headers remain inferred rather than independently
confirmed. Fan-planning counts therefore still show zero verified-free
headers, with FAN1/FAN2 explicitly labeled user-reported occupied. The eight
case fans are not assigned to motherboard headers. Neither photo-confirmed
M.2 occupancy nor reported cooler wiring creates new telemetry measurements.

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

Pins 1–4 match the usual four-pin PWM fan signal roles; generic four-pin
mechanical compatibility is **inferred**, not independently certified for
every plug. The manual does not explicitly specify three-pin DC speed-control
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
