# Minecraft server isolation

All three Minecraft servers are intentional and use separate named volumes:

| Server | Compose service | World volume | Host port |
|---|---|---|---|
| Vanilla Hardcore | `minecraft-server` | `compose_minecraft-server` | 36677 |
| Matcha Flavored (Fabric) | `matcha-minecraft-server` | `compose_matcha-minecraft-server` | 36678 |
| RLCraft | `rlcraft-minecraft-server` | `compose_rlcraft-minecraft-server` | 36676 |

Hardcore explicitly uses `TYPE: VANILLA`, an empty resource-pack URL/checksum and
disabled resource-pack enforcement; it has no configured datapacks or Modrinth
projects. Matcha owns the Matcha datapack, Easy Shulker Boxes and Bundle
Upgrade configuration. RLCraft uses its existing CurseForge configuration.
Use the main Compose entry point; do not share or rename these world volumes.

## Hardcore's stale Matcha files

On October 7, 2026, Hardcore still had a July 27 Modrinth manifest, five Fabric
mods and `world/datapacks/Matcha_Flavoured.zip` in its own volume. These were
persisted leftovers, not a shared mount or the current Compose configuration.
The incompatible datapack prevented world loading. Its persisted
`server.properties` also still required the old Matcha client resource pack;
the explicit empty resource-pack settings clear that leftover on startup.

With Hardcore stopped, its complete world, original `level.dat`, Modrinth
manifest, mods and server properties were backed up under
`/srv/homeserver/production-configs/hardcore-vanilla-2026-10-07/`.
The old pack/mod files were moved, not deleted, into
`/data/maintenance-backups/vanilla-2026-10-07/` inside the Hardcore volume.

The saved world's `Data.DataPacks.Enabled` list was changed from
`["vanilla", "file/Matcha_Flavoured.zip"]` to `["vanilla"]` with a typed NBT editor.
All other NBT values and the file's ownership/mode were checked unchanged before
startup. Region/player files were not edited or regenerated. Matcha and RLCraft
were not restarted.

When removing any future unwanted datapack, back up and stop the affected server
first. Removing just its ZIP can leave a stale enabled-pack reference in
`level.dat`. Do not reset the world or clear another server's datapacks as a
shortcut. A rollback must restore the matching world snapshot and quarantined
pack/mod state while Hardcore is stopped.
