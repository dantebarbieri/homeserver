# Prowlarr custom definitions

Two indexers use repo-managed variants of Prowlarr's upstream (Cardigann)
definitions. Each variant is derived from the upstream definition Prowlarr has
installed, by an awk program in `docker/prowlarr/`; only the changes below
differ from upstream.

| Indexer (Prowlarr ID) | `definitionFile` | Derived from | Change |
|-----------------------|------------------|--------------|--------|
| Internet Archive (`1`) | `internetarchive-homeserver` | `internetarchive` | Browser User-Agent on searches |
| Nyaa.si (`3`) | `nyaasi-anime-homeserver` | `nyaasi` | Anime-only capabilities and Category dropdown |

## Installing and keeping them current

From `docker/`:

```bash
bash scripts/setup-prowlarr-definitions.sh            # install or refresh
bash scripts/setup-prowlarr-definitions.sh --dry-run  # show what would change
```

The script derives each variant inside the `prowlarr` container from
`/config/Definitions/<upstream>.yml` and writes it to
`/config/Definitions/Custom/<name>.yml` (unique file and indexer names avoid
collisions; the Custom directory survives container recreation and Prowlarr's
own definition updates). It replaces only definitions whose derived content
changed, printing the diff, then runs Prowlarr's *Indexer Definition Update*
task, which clears its definition cache. No Compose change or restart is
needed.

Prowlarr refreshes the upstream definitions itself, so a frozen copy would
silently miss upstream parser fixes. The daily `docker-compose-update` unit
(`nixos/modules/docker.nix`) therefore reruns the script after deploying, so
each variant follows upstream within a day and repo edits to the awk programs
deploy like any other change.

Each awk program asserts the upstream structure it edits. If upstream changes
shape, the installed variant is kept, the script exits non-zero, and the
update unit fails so ntfy reports it. Review the new upstream definition
(`docker exec prowlarr cat /config/Definitions/<upstream>.yml`), adjust the
awk program and its tests, and rerun.

### Activating on an indexer

Production already uses both variants; this is only needed on a fresh
install. Reuse the existing indexer rather than adding a duplicate:
GET `/api/v1/indexer/<id>`, change only the `fields[].value` entries listed
below, POST the complete resource to `/api/v1/indexer/test`, then PUT it to
`/api/v1/indexer/<id>`, authenticating with `X-Api-Key`. Preserve the ID,
name, settings, tags and application mappings, and run Test again after
saving to clear any failure backoff.

| Indexer | Fields | Rollback |
|---------|--------|----------|
| Internet Archive | `definitionFile=internetarchive-homeserver` | `definitionFile=internetarchive` |
| Nyaa.si | `definitionFile=nyaasi-anime-homeserver`, `cat-id=0` (Anime) | `definitionFile=nyaasi`, `cat-id=1` |

The narrowed Nyaa dropdown has different option indices from the stock one,
hence the different `cat-id` values. Switch an indexer back before deleting
its variant or removing it from the script.

## Internet Archive: User-Agent

Internet Archive accepts TLS but stalls search requests carrying Prowlarr's
default User-Agent. On 2026-10-25, identical requests from the Prowlarr
container timed out after 20 seconds with that agent but returned HTTP 200 in
0.58 seconds with a Firefox agent; on 2026-10-31 (Prowlarr 2.7.0) they took
23.4 seconds versus 0.49 seconds. This is not a FlareSolverr challenge;
Internet Archive has no proxy tag. The variant adds a Firefox User-Agent to
search requests only. If upstream starts setting request headers itself, the
script stops and asks for a review of whether the workaround is still needed.
Related report:
[Prowlarr/Indexers#1104](https://github.com/Prowlarr/Indexers/pull/1104)
(closed without merging).

## Nyaa: anime only

On 2026-10-25, Nyaa reached Prowlarr's configured **700 queries per rolling
24 hours**. The local query-limit log explained that day's temporary
unavailability; it was not evidence of a Nyaa IP ban. Keep this guardrail.
FlareSolverr and a different User-Agent do not address a local quota.

Selecting **Anime** in Nyaa's upstream Category setting does not narrow the
capabilities Prowlarr advertises. The stock definition still claims music,
books, software and live-action support. This allows irrelevant requests,
including music searches, to consume the same daily allowance.

The variant retains all anime subcategories and both TV/anime and movie
mappings, removes unrelated categories and music/book search modes, and
limits the Category dropdown to anime. It preserves upstream parsing, request
delay, search paths, RSS pagination, magnets and title compatibility options.

Sonarr's Nyaa indexer remains tagged `anime-tv`; Radarr's remains tagged
`anime-movies`. Keep both absolute-episode and season/episode-format
searches, automatic and interactive searches, and RSS enabled. Do not
change global app sync categories or disable the extra search format just
to reduce traffic: doing so can lose useful anime releases or season packs.
Lidarr has no Nyaa indexer, and the narrowed capabilities prevent music
sync or category-based music searches from selecting it.

This eliminates irrelevant requests, not all high-volume searches. Anime
title aliases, both naming formats, RSS and bulk backlog searches still
use the allowance. Broad TV/movie categories and uncategorized manual
searches cannot identify whether a title is anime; app tags remain the
content-routing guardrail.

## Tests

```bash
cd docker && python3 -m unittest tests.test_setup_prowlarr_definitions
```

The awk tests need `awk`; the installer tests also need a POSIX system and
run it against a mock `docker`.
