# Recyclarr Configs

Resolution-based Sonarr and Radarr profiles, using TRaSH Guides custom formats
and a local English-anime-audio requirement. Recyclarr is pinned to **8.8.0**
in `docker/compose.starr.yml` and the validation workflow.

## Files

| Path | Purpose |
|---|---|
| `recyclarr.yml` | Instances, includes, size limits, and media naming |
| `settings.yml` | Local custom-format providers alongside the official guides |
| `includes/{sonarr,radarr}/quality-profiles.yml` | Quality ordering and upgrade policy |
| `includes/{sonarr,radarr}/custom-formats.yml` | Guide formats, scores, and eligibility |
| `custom-formats/english-anime-audio.json` | Shared release-title matcher, registered separately for each app |
| `secrets.yml.example` | Connection template; real `secrets.yml` is never committed |
| `tests/` | Schema, scoring, source-ordering, and title-matching regression checks |

## Requester-facing profiles

Each app has **30 profiles**: five exact resolutions and five "At most"
resolutions, each with standard, Anime, and Anime (Dub) variants.

- Exact: `SD - 480p`, `SD - 576p`, `HD - 720p`, `HD - 1080p`, `4K UHD - 2160p`.
- Upper bounds: `At most 480p`, `At most 576p`, `At most 720p`,
  `At most 1080p`, `At most 2160p`.
- Append ` Anime` or ` Anime (Dub)` for the anime variants.

Names are preserved so existing series, movies, and request-service mappings
keep using the same profiles. Requesters choose resolution and language
policy, not source quality.

### Source quality and upgrades

Standard profiles rank **remux > Blu-ray encode > WEB-DL/WEBRip > HDTV**
within each resolution, where those qualities exist. "At most" profiles
rank resolution first, then source. DVD/SDTV are lower-priority fallbacks
only in "At most" profiles.

Anime groups Blu-ray encodes with remuxes and WEB with HDTV; anime release
tiers choose within those groups. This lets a preferred anime encode beat
an inferior remux while still preferring Blu-ray over WEB at the same
resolution. Sonarr uses `anime-sonarr` scores; Radarr uses `anime-radarr`.

Upgrades remain enabled through the highest allowed source/group.
The custom-format cutoff is 10000 for standard/regular anime and 40000
for dubbed anime. These are headroom thresholds, not targets that must be
downloaded. They keep genuine improvements eligible rather than stopping
when the English-audio marker first matches. Equivalent releases are not
upgrades merely because a cutoff has not been reached.

Remux preference can substantially increase disk use and bandwidth.
Existing guide size limits still apply. Quality priority takes precedence
over custom-format score: a higher source can replace a lower source with
a larger tier score, provided the candidate still meets the minimum score.

### English anime dubs are required, not just preferred

Anime (Dub) accepts English-only or English-containing dual-audio releases
on equal terms. Quality and release tiers choose between eligible releases.
It does **not** fall back to Japanese-only releases while waiting for a dub.
Subtitles may still be present; the requirement concerns spoken audio.

The local **English Anime Audio** format accepts:

- Explicit `English Dub`, `Eng Dub`, `Dub Eng`, or `English Audio` labels.
- Explicit paired audio-language tags such as `[JA+EN]`, `[EN+JA]`, or
  `[Japanese+English]`, including the naming scheme's audio-language tags.
- `FuniDub` and the bracketed/suffixed `Golumpa` release group.
  [Golumpa's FuniDub releases](https://amenzb.moe/release-groups/golumpa?page=3)
  provide the initial verified group convention; this is not a general
  allowlist of every group in TRaSH's Dubs Only format.
- The format's own `[English Anime Audio]` rename marker, so eligibility
  survives renaming when the original English-audio title text is lost.

Bare `Dubbed`, `Dual Audio`, `Multi Audio`, `English`, and English-subtitle
labels are insufficient. Contradictory sub-only, Japanese-only, non-English
dub, no-English-audio, and English-commentary labels are rejected even
when an English marker or an allowlisted group is present.

This is deliberately conservative release-title matching, **not inspection
of audio tracks before downloading**. Mislabeled releases remain possible;
legitimate unlabelled dubs can be rejected. Add support for a new convention
only with English-audio evidence and positive/negative title cases.
`tests/english-audio-cases.json` uses representative Pokemon/Sonic X titles,
not a claim that any particular indexed release has been verified.

| Dub policy | Score |
|---|---:|
| English Anime Audio | +20000 |
| Minimum accepted format score | 20000 |
| Generic Dubs Only / Anime Dual Audio | 0 |
| Hard unwanted formats (LQ, raws, AV1, etc.) | -100000 |
| Upgrade-until format score | 40000 |

One English eligibility marker is assigned once per profile. All other
positive scores combined must remain below 20000; the tests check this
against current guide data. Thus even a worst-case sum cannot qualify a
sub-only release, finish upgrades, or cancel a hard rejection. Recyclarr
keeps the **first** assignment for duplicate CF/profile pairs, so duplicates
are forbidden by the regression checks rather than used as overrides.

Regular Anime retains the guide's dub-only penalty and neutral dual-audio
score. Anime profiles do not use generic LanguageSpecification-based
language penalties because they can misidentify dual-audio releases.

### 4K SDR and Dolby Vision

4K SDR is allowed in both apps. Standard UHD profiles retain positive HDR
preferences and **DV (w/o HDR fallback) = -10000**, but do not demand HDR.
This avoids rejecting legitimate SDR masters, including animation.

DV protection is title/source matching, not inspection of the video's
Dolby Vision profile. A Profile 5 file has no HDR10-compatible base layer
and may need a properly tone-mapped version for incompatible clients.
See [Plex playback](../docker/docs/PLEX.md).

## Validation without production access

From the monorepo root:

```sh
uv run --no-project --with-requirements recyclarr-configs/tests/requirements.txt \
  python -B -m unittest discover -s recyclarr-configs/tests -v
uv run --no-project --with-requirements recyclarr-configs/tests/requirements.txt \
  yamllint -c recyclarr-configs/.yamllint.yml recyclarr-configs/
```

The tests download public guide data and the pinned Recyclarr schemas.
They need internet access but no API keys or Sonarr/Radarr connection.
CI also exercises the matcher with .NET's regex engine and loads both
providers with the pinned Recyclarr image in a temporary directory using
dummy secrets. It never runs a production sync.

## Deployment is a separate, approved operation

The container mounts `${DATA}/recyclarr/config` as `/config`; it does **not**
mount this tracked directory. A Git pull alone does not deploy these
profile files. Keep the real secrets at
`${DATA}/recyclarr/config/secrets.yml`, mode `600`, owned by the configured
container UID. Use the internal URLs `http://sonarr:8989` and
`http://radarr:7878`, not localhost. No secrets belong in this repository.

After approval, first back up the deployed configuration (including the
previous `settings.yml`, includes, and private secrets) and the apps'
existing profiles. Copy **all four** tracked config components together;
the English requirement cannot work without the local provider file:

```sh
# Run from the monorepo root on the workstation.
# Use the server's actual DATA path if it differs from /srv/docker/data.
rsync -av \
  recyclarr-configs/recyclarr.yml recyclarr-configs/settings.yml \
  recyclarr-configs/includes recyclarr-configs/custom-formats \
  user@server:/srv/docker/data/recyclarr/config/
```

Source directory names have no trailing slash so `includes/` and
`custom-formats/` are preserved under the destination. This copies no
secrets, runtime state, or test files.

Then, on the server, use the **main Compose entry point**:

```sh
z /srv/homeserver/docker
docker compose run --rm recyclarr sync --preview
# Review source ordering, thresholds, local format, and proposed changes.
# Only after approving that preview:
docker compose run --rm recyclarr sync
```

Review particularly any pending WEB-to-Blu-ray/remux upgrades and the Dub
minimum score. Sync updates profiles and naming settings; it does not
immediately replace every existing sub-only file. Previously downloaded
files remain until a qualifying upgrade is found; use targeted searches
after approval if a specific existing series needs replacement.
