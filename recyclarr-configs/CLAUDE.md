# Recyclarr configuration guidance

This directory contains the homeserver's tracked Recyclarr configuration.
See `README.md` for policy, matching limitations, validation, and the
separate approved deployment procedure.

## Layout

- `recyclarr.yml`: instances, size definitions, includes, and naming.
- `includes/{sonarr,radarr}/quality-profiles.yml`: 30 profiles per app.
- `includes/{sonarr,radarr}/custom-formats.yml`: format assignments and scores.
- `settings.yml`: local providers registered separately for each service.
- `custom-formats/english-anime-audio.json`: shared title-only English-audio
  matcher, additive to official guide resources.
- `tests/`: schema, source-order, scoring-invariant, and matcher checks.
- `secrets.yml.example`: dummy connection template. Real secrets are private.

## Policy

Keep requester-facing names unchanged: five exact resolutions, five upper
bounds, each with standard, Anime, and Anime (Dub) variants.

Standard profiles prefer remux > Blu-ray > WEB > HDTV within a resolution.
Anime groups Blu-ray encodes with remuxes, and WEB with HDTV, so anime
release tiers decide within groups. Higher resolution takes precedence
in upper-bound profiles. Use `anime-sonarr` for Sonarr and `anime-radarr`
for Radarr. Allow 4K SDR; retain standard UHD HDR preferences and the
DV-without-HDR-fallback penalty.

Anime (Dub) requires the local English-audio marker: +20000, minimum 20000,
upgrade cutoff 40000. Generic Dubs Only and Anime Dual Audio are zero in
Dub profiles, not language guarantees. Hard unwanted formats score -100000
there. Regular Anime retains the guide's dub-only penalty.

Do not use duplicate CF/profile assignments as overrides: Recyclarr keeps
the first score. Keep every non-English-marker positive score combined
below the Dub minimum, the maximum eligible score below its upgrade
cutoff, and hard rejections below the minimum even with all positives.
The tests enforce these bounds against current guide scores.

English-audio detection must fail closed on ambiguous titles. Do not
accept generic dual/dub labels or English subtitles as proof of English
audio. Add positive and negative cases for matcher changes. The JSON
regex must work in .NET, not just Python. Preserve its own rename marker
and explicit audio-language pairs to avoid losing eligibility on rename.

## Validation and deployment

Use the commands in `README.md`; tests need public guide/schema downloads
but must never read real secrets or contact production apps. Keep the
Recyclarr image version aligned in Compose and CI.

The live container mounts `${DATA}/recyclarr/config`, not this directory.
Deployment requires the entry point, settings, includes, and custom
formats together. Never sync secrets from Git. Do not run a live sync
or deploy merely because a config change was requested; preview and
deployment are separate approval steps.
