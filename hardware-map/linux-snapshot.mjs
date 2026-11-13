// Sanitized read-only observations, not stable hardware identities or live state.
const hdds = [
  ["sda", "hba-controller"], ["sdb", "hba-controller"], ["sdc", "hba-controller"], ["sdd", "hba-controller"],
  ["sde", "sata-controller-a"], ["sdf", "sata-controller-a"], ["sdg", "sata-controller-a"],
  ["sdh", "sata-controller-b"], ["sdi", "sata-controller-b"], ["sdj", "sata-controller-b"],
  ["sdk", "sata-controller-b"], ["sdl", "sata-controller-a"],
];
const hddIds = hdds.map(([id]) => id);
const sataIds = hdds.filter(([, controller]) => controller !== "hba-controller").map(([id]) => id);
const parent = (id, relation) => ({ id, relation });
const lv = (id, mapperName, sizeBytes, summary, parents, aliases = []) => ({
  id, label: `/dev/mapper/${mapperName}`, aliases: [`/dev/${id}`, ...aliases], kind: "LVM / device-mapper",
  sizeBytes, summary, parents,
});

export const linuxSnapshot = {
  schemaVersion: 1,
  capturedAt: "2026-11-13T12:39:12-06:00",
  source: "Read-only SSH: lsblk, /proc/mdstat, sysfs block/PCI/network dependencies, findmnt.",
  note: "Collected 12:37–12:39 CST, not atomically or live. /dev/sdX, NVMe numbering and interface names can change; they are snapshot aliases, not permanent disk identities. No serials, WWNs, MAC/IP addresses or credentials are bundled.",
  limitations: "Privileged lvs and LVM metadata were not accessible without a password. Internal LV roles below follow kernel mapper names and dependencies; exact extent allocation and current cache mode are not independently verified. nvme1n1 backs ordinary /data extents as well as cache: /data is not entirely RAID-protected.",
  nodes: [
    { id: "hba-controller", label: "HBA · PCI 0000:81:00.0", kind: "Storage controller", summary: "mpt3sas · PCI 1000:0097; exact board SKU remains unverified" },
    { id: "sata-controller-a", label: "Onboard SATA · PCI 0000:49:00.0", kind: "Storage controller", summary: "ahci · PCI 1022:7901; SATA header/breakout assignments untraced" },
    { id: "sata-controller-b", label: "Onboard SATA · PCI 0000:4a:00.0", kind: "Storage controller", summary: "ahci · PCI 1022:7901; SATA header/breakout assignments untraced" },
    ...hdds.flatMap(([id, controller]) => [
      { id, label: `/dev/${id}`, kind: "Physical HDD", sizeBytes: 8001563222016, model: "WDC WD80EFPX-68C4ZN0", summary: "Physical bay unassigned", parents: [parent(controller, "Attached to")] },
      { id: `${id}1`, label: `/dev/${id}1`, kind: "RAID-member partition", sizeBytes: 8001561821184, parents: [parent(id, "Partition of")] },
    ]),
    { id: "md0", label: "/dev/md0", kind: "mdadm RAID6", sizeBytes: 72012838993920, summary: "LVM physical volume for vg_redundant" },
    { id: "nvme0n1", label: "/dev/nvme0n1", kind: "Physical NVMe", sizeBytes: 2000398934016, model: "Samsung SSD 990 EVO 2TB", summary: "OS / root / swap · PCI 0000:41:00.0; M.2 socket unassigned" },
    { id: "nvme0n1p1", label: "/dev/nvme0n1p1", kind: "Partition", sizeBytes: 536870912, summary: "vfat mounted at /boot", parents: [parent("nvme0n1", "Partition of")] },
    { id: "nvme0n1p2", label: "/dev/nvme0n1p2", kind: "Partition", sizeBytes: 511705088, summary: "ext2 · no mountpoint observed", parents: [parent("nvme0n1", "Partition of")] },
    { id: "nvme0n1p3", label: "/dev/nvme0n1p3", kind: "LVM physical-volume partition", sizeBytes: 1999349219328, parents: [parent("nvme0n1", "Partition of")] },
    { id: "nvme1n1", label: "/dev/nvme1n1", kind: "Physical NVMe", sizeBytes: 2000398934016, model: "Samsung SSD 990 EVO 2TB", summary: "Cache AND ordinary /data backing · PCI 0000:01:00.0; M.2 socket unassigned" },
    { id: "nvme1n1p1", label: "/dev/nvme1n1p1", kind: "LVM physical-volume partition", sizeBytes: 2000397795328, parents: [parent("nvme1n1", "Partition of")] },
    { id: "homeserver-vg", label: "homeserver-vg", kind: "LVM volume group", parents: [parent("nvme0n1p3", "Physical volume")] },
    { id: "vg_redundant", label: "vg_redundant", kind: "LVM volume group", parents: [parent("md0", "Physical volume"), parent("nvme1n1p1", "Physical volume")] },
    lv("dm-0", "homeserver--vg-swap", 127997575168, "Swap", [parent("nvme0n1p3", "Kernel backing device"), parent("homeserver-vg", "Member of VG")], ["/dev/homeserver-vg/swap"]),
    lv("dm-1", "homeserver--vg-root", 1871347449856, "ext4 mounted at / and /nix/store", [parent("nvme0n1p3", "Kernel backing device"), parent("homeserver-vg", "Member of VG")], ["/dev/homeserver-vg/root"]),
    lv("dm-2", "vg_redundant-cache_pool_data_cpool_cdata", 1979124285440, "Internal cache-data LV", [parent("nvme1n1p1", "Cache backing device")]),
    lv("dm-3", "vg_redundant-cache_pool_data_cpool_cmeta", 46137344, "Internal cache-metadata LV", [parent("nvme1n1p1", "Cache backing device")]),
    lv("dm-4", "vg_redundant-lv_data_corig", 72034012889088, "Original data LV: md0 PLUS NVMe extents, not RAID-only", [parent("md0", "Ordinary data backing"), parent("nvme1n1p1", "Ordinary data backing")]),
    { ...lv("dm-5", "vg_redundant-lv_data", 72034012889088, "Cached data LV · XFS /data", [parent("dm-4", "Data origin"), parent("dm-2", "Cache data"), parent("dm-3", "Cache metadata"), parent("vg_redundant", "Member of VG")]), aliases: ["/dev/dm-5", "/dev/vg_redundant/lv_data"] },
    { id: "data-filesystem", label: "/data", kind: "Mounted XFS filesystem", sizeBytes: 72031875891200, usedBytes: 58141624541184, summary: "Filesystem capacity differs from underlying block-device capacity", parents: [parent("dm-5", "Mounted from")] },
    { id: "enp66s0f0", label: "enp66s0f0", kind: "Physical 10GbE interface", summary: "Intel X550 / ixgbe · PCI 0000:42:00.0 · link up, 10,000 Mb/s full duplex; LAN1/LAN2 binding unassigned" },
    { id: "enp66s0f1", label: "enp66s0f1", kind: "Physical 10GbE interface", summary: "Intel X550 / ixgbe · PCI 0000:42:00.1 · link up, 10,000 Mb/s full duplex; LAN1/LAN2 binding unassigned" },
    { id: "bond0", label: "bond0", kind: "Linux network bond" },
    { id: "enp72s0f3u2u3c2", label: "enp72s0f3u2u3c2", kind: "USB virtual Ethernet interface", summary: "American Megatrends Inc. / Virtual Ethernet / cdc_ether · down. Separate from Intel ports; not an identification of the dedicated BMC LAN socket." },
  ],
  raids: [{
    id: "md0", level: "RAID6", raidDisks: 11, state: "clean", degraded: 0, syncAction: "idle",
    members: [
      ["sda1", "in_sync", 7], ["sdb1", "in_sync", 10], ["sdc1", "in_sync", 9],
      ["sdd1", "in_sync", 8], ["sde1", "spare", null], ["sdf1", "in_sync", 1],
      ["sdg1", "in_sync", 3], ["sdh1", "in_sync", 5], ["sdi1", "in_sync", 4],
      ["sdj1", "in_sync", 6], ["sdk1", "in_sync", 2], ["sdl1", "in_sync", 0],
    ].map(([id, state, slot]) => ({ id, state, slot })),
  }],
  bonds: [{ id: "bond0", mode: "active-backup", activeSlave: "enp66s0f1", members: ["enp66s0f0", "enp66s0f1"] }],
  associations: [
    { targets: ["disk-bays", "disks"], nodes: hddIds, note: "These are the twelve installed HDDs as Linux sees them. None is assigned to a specific cage/bay; list order is NOT physical placement." },
    { targets: ["hba", "PCIE1"], nodes: ["hba-controller", "sda", "sdb", "sdc", "sdd"], note: "Kernel sysfs paths attach these four HDDs to the mpt3sas controller. PCIE1 is the user-confirmed HBA location; the exact board SKU is still not established." },
    { targets: ["SATA_0_3", "SATA_4_7"], nodes: sataIds, note: "Eight HDDs use onboard ahci controllers. The split between these two physical breakout headers is not traced; these are candidates, not eight connections on this header." },
    { targets: ["drive-M2_1", "drive-M2_2", "M2_1", "M2_2"], nodes: ["nvme0n1", "nvme1n1"], note: "Both Linux NVMe devices are known, but their M2_1/M2_2 socket assignments are not. Older sensor labels NVMe A/B are also unbound; do not identify a socket by list order." },
    { targets: ["network-ports", "rear-io"], nodes: ["enp66s0f0", "enp66s0f1", "bond0", "enp72s0f3u2u3c2"], note: "Two Intel interfaces form bond0; the AMI USB virtual NIC is separate. LAN1/LAN2-to-interface pairing is not established, and the dedicated BMC LAN has no host-interface binding." },
    { targets: ["LAN1", "LAN2"], nodes: ["enp66s0f0", "enp66s0f1", "bond0"], note: "Both Intel interfaces are connected and bonded. The physical LAN1/LAN2-to-interface pairing has not been independently established; PCI function number is not proof of port labeling." },
    { targets: ["IPMI_LAN1"], nodes: ["enp72s0f3u2u3c2"], note: "The dedicated BMC LAN is managed separately by the BMC, not as a Linux host NIC. This observed USB virtual interface is separate context, NOT a binding to the rear BMC LAN socket." },
  ],
};
