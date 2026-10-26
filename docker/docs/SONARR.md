# Sonarr

## Queue maintenance (`sonarr-maint`)

`sonarr-maint` (`compose.starr.yml`, built from the shared `dockerfiles/arr-maint/` image (common engine in `arr_maint.py`, Sonarr rules in `sonarr.py`))
checks Sonarr's queue every 30 minutes. Sonarr lists one queue row per episode,
so the script groups rows by download. It only acts on downloads that have been
stuck for at least 20 minutes (`GRACE_MINUTES`), so Sonarr's own import and
failure handling gets the first try.

| Stuck pattern | Fix |
|---------------|-----|
| Import pending because the file's episode numbering doesn't match the grab, common with anime absolute numbers (`[HatSubs] One Piece 1162` parsed as 11x62, or "Invalid season or episode"). Applies only when there is exactly one file, the grab was for exactly one episode, and every rejection is a numbering one | Manual import into the grabbed episode, using the grab's quality and languages (copy for torrents to keep hardlinks, move for usenet) |
| Downloaded the same release that is already in the library | Blocklist and remove |
| Every file rejected as "not an upgrade" | Blocklist and remove |
| Failed download | Blocklist and remove (Sonarr searches again) |
| Dead torrent: no connected seeds for 24 h (`STALL_HOURS`) and either below 5%, including stuck on "downloading metadata", or partly done with availability below 1 and no activity for 24 h (Sonarr's qBittorrent categories) | Blocklist and remove (Sonarr searches again) |
| "Not grabbed by Sonarr" entries | Remove from the queue (the download is kept) |
| Torrent with no series match whose files were already imported by hand (hardlink count > 1) | Remove from the queue (the download is kept and keeps seeding) |
| Missing monitored episodes | `MissingEpisodeSearch` at most every 168 h (`MISSING_SEARCH_HOURS`, `0` disables) |

Quality, language and custom-format rejections are never overridden. In
particular, the English-dub anime profiles' strict audio requirements are
intentional. Anything else, such as files that match a different series or a
multi-file download with rejections, is posted once to ntfy
(`homeserver-alerts`) as "Sonarr: needs attention". A failing run alerts at high
priority, and repeats of the same error at most every 6 hours.

These need no help: Sonarr blocklists usenet "repair failed" and "incomplete"
downloads and grabs another release on its own. Torrent "stalled" warnings are
left alone until the dead-torrent rule applies, so they don't trigger alerts.

The container reads Sonarr's API key from its `config.xml` (read-only), uses the
qBittorrent's `QUSER`/`QPASS` credentials, and keeps its state in `${DATA}/sonarr-maint`.
It mounts `/data` read-only to check hardlinks; Sonarr performs the imports.

```bash
docker logs -f sonarr-maint                                                  # what it did
docker compose run --rm -e DRY=1 -e ONCE=1 -e GRACE_MINUTES=0 sonarr-maint   # preview one run
```

## SABnzbd settings

- Duplicate detection is **off** (`no_dupes`, `no_series_dupes` and
  `no_smart_dupes` are all 0). With smart duplicate detection on, upgrade grabs
  of episodes already in SABnzbd's history failed as "Duplicate NZB".
- Each Sonarr SABnzbd client (Anime, Bollywood, TV) uses **Recent Priority =
  High** and **Older Priority = Normal**, so new episodes download ahead of
  backfill and Radarr's remux upgrades. Older backfill waiting in SABnzbd is
  expected.
