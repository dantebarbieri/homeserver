# Radarr

## Queue maintenance (`radarr-maint`)

`radarr-maint` (`compose.starr.yml`, built from the shared `dockerfiles/arr-maint/` image (common engine in `arr_maint.py`, Radarr rules in `radarr.py`))
checks Radarr's queue every 30 minutes. It only acts on items that have been
stuck for at least 20 minutes (`GRACE_MINUTES`), so Radarr's own import and
failure handling gets the first try.

| Stuck pattern | Fix |
|---------------|-----|
| Import blocked: "matched by ID, Manual Import required" (non-scene names such as `(Comedy) Netflix Originals - ...`), with exactly one file Radarr accepts | Manual import into the queued movie (copy for torrents to keep hardlinks, move for usenet) |
| Downloaded the same release that is already in the library | Blocklist and remove |
| Every file rejected as "not an upgrade", for example an AI upscale with a negative custom format score | Blocklist and remove |
| Failed download | Blocklist and remove (Radarr searches again) |
| Dead torrent: no connected seeds for 24 h (`STALL_HOURS`) and either below 5%, including stuck on "downloading metadata", or partly done with availability below 1 and no activity for 24 h (Radarr's qBittorrent categories) | Blocklist and remove |
| "Not grabbed by Radarr" entries | Remove from the queue (the download is kept) |
| Torrent with no movie match whose files were already imported by hand (hardlink count > 1) | Remove from the queue (the download is kept and keeps seeding) |
| Missing monitored movies | `MissingMoviesSearch` at most every 24 h (`MISSING_SEARCH_HOURS`) |

Anything else, such as files that match a different movie or more than one
importable file, is posted once to ntfy (`homeserver-alerts`) as "Radarr: needs
attention". A failing run alerts at high priority, and repeats of the same error
at most every 6 hours. Usenet "incomplete" and "repair failed" failures need no
help: Radarr blocklists them and grabs another release on its own.

The container reads Radarr's API key from its `config.xml` (read-only), uses the
qBittorrent's `QUSER`/`QPASS` credentials, and keeps its state in `${DATA}/radarr-maint`.
It mounts `/data` read-only to check hardlinks; Radarr performs the imports.

```bash
docker logs -f radarr-maint                                                  # what it did
docker compose run --rm -e DRY=1 -e ONCE=1 -e GRACE_MINUTES=0 radarr-maint   # preview one run
```

## SABnzbd settings

- Duplicate detection is **off** (`no_dupes`, `no_series_dupes` and
  `no_smart_dupes` are all 0). With smart duplicate detection on, every upgrade
  grab of a movie already in SABnzbd's history failed as "Duplicate NZB", and
  Radarr blocklisted good releases one after another.
- Each Radarr SABnzbd client uses **Recent Priority = High** and **Older Priority
  = Normal**, so new releases download ahead of backfill and remux upgrades.
