# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

Personal [Recyclarr](https://github.com/recyclarr/recyclarr) configuration that syncs [TRaSH Guides](https://trash-guides.info/) quality profiles and custom formats to Sonarr and Radarr.

## Key Files

- `recyclarr.yml` — The main file you'll iterate on. Contains all quality profiles, custom format assignments, and score overrides for both Sonarr and Radarr.
- `settings.yml` — Instance connection settings. Rarely changes.
- `secrets.yml` — Gitignored. Contains API keys and URLs. Copy from `secrets.yml.example` to create.

## Configuration Structure

`recyclarr.yml` is divided into two top-level sections:

- `sonarr:` — TV show quality profiles, custom formats, and media naming (plex-tvdb)
- `radarr:` — Movie quality profiles, custom formats, and media naming (plex-tmdb)

Both sections follow the same pattern:
1. `quality_definition` — Sets the quality size limits (`series` or `movie`)
2. `quality_profiles` — Named profiles with `min_format_score`, `quality_sort`, and `qualities` lists
3. `custom_formats` — Lists of `trash_ids` mapped to profiles with score assignments
4. `media_naming` — Naming scheme references

Sensitive values use `!secret <key>` YAML tag (e.g., `!secret sonarr_apikey`), resolved from `secrets.yml`.

## Profiles Defined

11 profiles in each app (Sonarr and Radarr):

| Profile | Purpose |
|---|---|
| `480p`, `576p`, `720p`, `1080p`, `2160p` | Standard resolution tiers |
| `720p or 1080p`, `1080p or 2160p` | Multi-resolution |
| `anime-sonarr` / `anime-radarr` | Anime with BD/Web tier scoring |
| `at-most-480p`, `at-most-720p`, `at-most-1080p` | Restrictive upper-bound profiles |

## Deployment

```sh
rsync -av --exclude='.git' --exclude='secrets.yml.example' \
  recyclarr.yml settings.yml \
  user@server:/path/to/recyclarr/config/
```

`secrets.yml` must be managed on the server directly — never synced from this repo.

## References

- [TRaSH Guides](https://trash-guides.info/) — Source for valid `trash_ids` and recommended scores
- [Recyclarr Wiki](https://recyclarr.dev/wiki/) — Config schema and options reference
- [Config Schema](https://raw.githubusercontent.com/recyclarr/recyclarr/master/schemas/config-schema.json) — Referenced in `recyclarr.yml` for validation
