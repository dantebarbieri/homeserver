# Server cooling and hardware

Findings and decisions from the November 2026 overheating investigation. The
Mac Studio is documented separately in [`macos/DECISIONS.md`](../macos/DECISIONS.md).

**Intent (Dante):** the server should stay cool without constant fan surges
during heavy GPU/CPU work such as Whisper subtitling and Tdarr encoding, with a
plan for spare and additional drives.

Manuals: [ROMED8-2T user manual](https://download.asrock.com/Manual/ROMED8-2T.pdf),
[ROMED8-2T BMC guide](https://download.asrock.com/Manual/IPMI/ROMED8-2T.pdf).

## Hardware facts

Read-only SSH, BMC, Prometheus, SMART and event-log review; no server or BMC
configuration was changed.

- AMD EPYC 7313P on an ASRock Rack ROMED8-2T (rev 1.03), 128 GB RAM, Corsair
  HX1000i, Rosewill RSV-L4500U case.
- RTX 2070 SUPER in PCIE3. It is intentional: the EPYC would not POST with the
  RTX 3060. The HBA sits in PCIE1, directly under the GPU's intake.
- Two Samsung 990 EVO 2 TB NVMe drives without heatsinks, under the GPU overhang.
- Disks: 12 × WD80EFPX 8 TB. `md0` is RAID6 with 11 active members and 1 hot
  spare, which is complete. RAID6 spreads parity across all members; there are
  no dedicated parity disks. Four extra drives in the build spreadsheet were
  never array members. The BMC does not inventory HDDs. `/data` is XFS on LVM,
  about 66 TB, about 81 % used in November 2026.
- Fans: six Noctua NF-P12 redux-1700 PWM fans (front and middle) on a
  SATA-powered Thermalright ARGB 8-group hub connected to FAN3. The BMC sees one
  tach reading for the hub (about 1100 RPM). The rear 80 mm fans are still
  Molex, so they are neither controlled nor monitored.
- Historical peaks before the changes: CPU Tctl 85.5 °C, one NVMe sensor about
  106 °C, HDDs 47–51 °C, repeated BMC 55 °C motherboard warnings. The sustained
  load then was four CPU Tdarr encoders, not Whisper.

## Decisions

| Decision | Chosen | Why | By |
|---|---|---|---|
| First response | Clean out dust, give the closet clearance, add controllable fans | Evidence pointed to airflow plus sustained CPU encoding, not a failing part | Agent advice; Dante cleaned and moved the server |
| Fans | The Noctua fans and hub above | Molex fans cannot be controlled or monitored | Dante bought and installed them (an agent had suggested a SilverStone CPF04 hub) |
| HDDs | No new drives | Only three free bays; 12 drives is the intended count | Dante |
| Encoding | Keep quality-first CPU `libx265` | [Hardware encoders give less quality per byte](../macos/DECISIONS.md#offload-video-encoding-tdarr) | Dante |

## Incident: drives lost power after the fan install

Six drives lost SATA power and the server booted into emergency mode. Dante
reseated the power cable, and the array and `/data` came back intact. When
drives drop after hardware work, check power and data cables before any
`mdadm` or XFS repair.

## Server Atlas (hardware map)

An interactive map of the board, connectors and fans: the static
`hardware-map/` app on branch `dantebarbieri-server-hardware-map` (not merged,
no PR, not deployed). Facts are marked verified, inferred or unknown; the
manual's artwork is not committed. Commit `8a7f08e` drew the six Noctua fans and
the FAN3 hub. Next is a component-by-component walkthrough with Dante to
resolve the unknowns and link manuals. After that, the goal is live sensor data
(temperatures, fan speeds, capacities) graphed beside each component.

## Open items

1. Find the cause of the fan surges under real load: which BMC sensor drives
   FAN3 and how its fan curve is set.
2. NVMe heat: one sensor reached about 78 °C under boot I/O. Measure clearance
   under the GPU before buying heatsinks.
3. Replace or verify the rear 80 mm Molex fans. FAN4–7 and the HDD power harness
   are unverified.
4. Finish the Atlas walkthrough, then add live sensors.
