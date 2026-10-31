# Kim Possible: pinned chronology

Kim Possible is intentionally **absent from Sonarr**. Its on-disk season and
episode numbers are a custom viewing order, not any upstream order. The single
source of truth is `scripts/episode-orders/kim-possible.json`: each on-disk slot
(`S02E34`) maps to an authoritative title and a TheTVDB episode ID, which stays
stable when TVDB edits its orders. Two tools read it:

| Tool | Job |
|------|-----|
| `scripts/reorder-episodes.py` | Renames files and sidecars into the pinned slots, by NFO title |
| `scripts/pin-episode-metadata.py` | Pins titles, plots, air dates and thumbnails in Plex and Jellyfin |

Change the order by editing the JSON, then run the reorder tool followed by the
pin tool.

## Ordering decisions

- Season 1 preserves the existing 21-episode order, beginning with
  *Tick-Tick-Tick*. It matches TVDB Absolute order, but no longer matches the
  current TVDB DVD listing.
- Season 2 retains the three parts of *A Sitch in Time* and finishes with
  *Showdown at the Crooked D*, then *Rewriting History*.
- Season 3 puts *And the Molerat Will Be CGI*, *Rappin' Drakken*, *Gorilla Fist*,
  and *Team Impossible* in that sequence, with the full *So the Drama* movie last.
- Season 4 preserves the existing continuity adjustments, with *Homecoming
  Upset* before *Clean Slate* and *The Cupid Effect*, and *Larry's Birthday*
  before *Oh No! Yono!*. *Graduation* remains the finale.
- The *Lilo & Stitch* crossover stays at S00E06.

This is a deliberately conservative custom chronology, not a claim that one
official ordering resolves every continuity issue. References:
[TVDB Absolute](https://www.thetvdb.com/series/kim-possible/allseasons/absolute),
[TVDB DVD](https://www.thetvdb.com/series/kim-possible/allseasons/dvd),
[episode list and production codes](https://en.wikipedia.org/wiki/List_of_Kim_Possible_episodes),
and [episode guides](https://kpfanworld.com/Guides).

## Safe reordering

The server has no system Python, so run both tools through `nix-shell`. The
reorder tool requires every video in the order file, each with a same-stem NFO
containing its correct episode title. It never infers identity from existing
episode numbers, and refuses an NFO whose TVDB `uniqueid` disagrees with the
order file. Preview first:

```bash
z /srv/homeserver
nix-shell -p python3 --run 'python3 docker/scripts/reorder-episodes.py \
  docker/scripts/episode-orders/kim-possible.json'
nix-shell -p python3 --run 'python3 docker/scripts/reorder-episodes.py \
  docker/scripts/episode-orders/kim-possible.json \
  --apply --backup /data/shared/kim-possible-upgrade/reorder-$(date +%F)'
```

`--source DIR` overrides the order file's `path`, for example a staging copy.
The backup must be a **new directory on the same filesystem** and outside the
show directory. Videos and sidecars are hardlinked, not re-encoded. The tool
refuses missing, unknown, duplicate, and combined episodes or occupied targets,
updates NFO numbering and metadata locks, moves same-stem sidecars with
their episode, and rebuilds episode paths in an existing `.plexmatch` file.
Re-running it is harmless when the collection is already ordered.
Do not run it while a downloader or media manager is modifying the files.

To undo, leave the show and backup directories at their original paths:

```bash
nix-shell -p python3 --run 'python3 docker/scripts/reorder-episodes.py \
  --restore /path/to/backup/manifest.json'
```

Undo refuses files changed since the operation. A full-directory backup is
necessary when replacing videos or moving the prepared collection to a new
path; an ordering journal alone does not undo those separate operations.

Do **not** use the retired `kim_possible_rename.py` or invert its old
`.kp_rename_manifest.json` against an already customized collection. That tool
assumed aired input numbers, so repeated use misidentifies episodes.

## Pinning metadata

Plex (with `showOrdering` = `tvdbDvd`) and Jellyfin label files from an
upstream order, so TVDB's 2026 rewrite of the DVD order put the wrong titles on
correctly ordered files. `pin-episode-metadata.py` makes the order file win:

- **Jellyfin:** writes a locked `<video>.nfo` and a `<video>-thumb.jpg`, then
  refreshes the series when a sidecar changed. NFOs are compared by field, so
  the reorder tool's reformatting is not a change.
- **Plex:** sets and locks the title, summary, air date and episode thumbnail.

Titles come from the order file; plots, air dates and images come from TVDB by
episode ID, cached in the show folder as `.pinned-episode-metadata.json` for
when TVDB is unreachable. A `NOTE` line flags a TVDB title that disagrees with
the order file, which usually means a mistyped ID. Re-running is idempotent:

```bash
z /srv/homeserver
nix-shell -p python3 --run 'python3 docker/scripts/pin-episode-metadata.py \
  docker/scripts/episode-orders/kim-possible.json --dry-run'
```

Drop `--dry-run` to apply. Re-run after reordering, a Plex "Refresh Metadata",
a library re-add, or new files. Locked fields survive a normal refresh.

## Future quality upgrades

Use an isolated aired-order staging directory outside all media-library roots
and temporarily add only that directory to Sonarr. Keep the original collection
untouched until every replacement is verified, then remove the temporary Sonarr
series without deleting files. Do not add the chronological library to Sonarr:
the series is on Sonarr's import-list exclusions (TVDB `78259`).

Check actual release identity, not just Sonarr's renamed filename: CtrlHD's
Season 4 releases number *Chasing Rufus*, *Nursery Crimes*, and *Homecoming Upset*
as E18, E19, and E20, unlike Sonarr's aired listing. Comparing embedded English
dialogue against the original episodes detects this permutation. Check runtime,
English audio/subtitles, movie cuts, and surround tracks before replacement;
a higher custom-format score alone is not sufficient.

Preserve local NFO titles, plots, and TVDB IDs; remove obsolete stream metadata
when replacing an encode. Snapshot media-server episode identities and all-user
playback data before changing paths. Lock Plex's custom episode titles, indices,
summaries, and original content GUIDs; lock Jellyfin's local metadata and restore
playback data by episode identity if its path-based IDs change.

**Plex warning:** preserving `ratingKey` alone does not preserve watch state.
A scan can rematch episodes to the changed remote order, change their GUIDs,
and merge or remove per-user watch-state records. Keep a database backup as well
as per-episode/all-user snapshots before scanning. GUID locking is available
through the metadata edit API (`guid.value` and `guid.locked`); verify both GUIDs
and playback data afterward. Do not repair a running Plex database directly.

Tdarr's TV library has a show-specific `foldersToIgnore` entry:
`/data/media/tv/Kim Possible (2002) {imdb-tt0278866}`. Retain it so the larger
H.264 sources are not immediately lossy-transcoded back to HEVC.

For API work, load credentials inside the relevant server/container process and
send authorization headers. Never print config files, environment values,
download URLs, or raw API responses containing credentials. Jellyfin requires
`Authorization: MediaBrowser Token="..."`; the older `X-Emby-Token` header may
return 401 even for a valid key.

Focused local tests (order file, both tools):

```powershell
cd docker
uv run --no-project python -m unittest tests.test_episode_orders
```
