# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

Personal [Recyclarr](https://github.com/recyclarr/recyclarr) configuration that syncs [TRaSH Guides](https://trash-guides.info/) quality profiles and custom formats to Sonarr and Radarr.

## Key Files

- `recyclarr.yml` — Entry point. Defines Sonarr/Radarr instances, quality definitions, media naming, and `include` directives.
- `includes/sonarr/quality-profiles.yml` — All Sonarr quality profile definitions.
- `includes/sonarr/custom-formats.yml` — All Sonarr custom format assignments (uses YAML anchors for profile lists).
- `includes/radarr/quality-profiles.yml` — All Radarr quality profile definitions.
- `includes/radarr/custom-formats.yml` — All Radarr custom format assignments (uses YAML anchors for profile lists).
- `settings.yml` — Instance connection settings. Rarely changes.
- `secrets.yml` — Gitignored. Contains API keys and URLs. Copy from `secrets.yml.example` to create.

## Configuration Structure

`recyclarr.yml` defines two instances (`sonarr.series` and `radarr.movie`), each with:
- `base_url` / `api_key` — Instance connection (via `!secret` tags resolved from `secrets.yml`)
- `quality_definition` — Quality size limits (`series` or `movie`)
- `include` — References to files in `includes/` for quality profiles and custom formats
- `media_naming` — Naming scheme references

Include files use recyclarr's simplified structure (no service type or instance name).
YAML anchors (`&name` / `*name`) are used in custom format files to deduplicate repeated `assign_scores_to` profile lists.

## Profiles Defined

11 profiles in each app (Sonarr and Radarr):

| Profile | Purpose |
|---|---|
| `480p`, `576p`, `720p`, `1080p`, `2160p` | Standard resolution tiers |
| `720p or 1080p`, `1080p or 2160p` | Multi-resolution |
| `anime-sonarr` / `anime-radarr` | Anime with BD/Web tier scoring |
| `at-most-480p`, `at-most-720p`, `at-most-1080p` | Restrictive upper-bound profiles |

## Anime Language Strategy

Language CFs (`Language: Not Original`, `Language: Not English`) are **only assigned to standard (non-anime) profiles**. They are intentionally excluded from all anime profiles because Sonarr/Radarr's `LanguageSpecification` is unreliable for anime—it frequently misidentifies dual-audio releases as single-language.

Anime profiles rely on anime-specific CFs for language preference instead:
- **Regular Anime**: `Dubs Only` (−10000) penalizes dub-only releases; `Anime Raws` (−10000) penalizes raw releases. Quality tiers naturally prefer Japanese fansub groups.
- **Anime (Dub)**: `Dubs Only` (+10000 override) and `Anime Dual Audio` (+5000 override) strongly prefer English content. Releases without English score much lower and lose to upgrades.

## Deployment

```sh
rsync -av --exclude='.git' --exclude='secrets.yml.example' \
  recyclarr.yml settings.yml includes/ \
  user@server:/path/to/recyclarr/config/
```

`secrets.yml` must be managed on the server directly — never synced from this repo.

## References

- [TRaSH Guides](https://trash-guides.info/) — Source for valid `trash_ids` and recommended scores
- [Recyclarr Wiki](https://recyclarr.dev/wiki/) — Config schema and options reference
- [Config Schema](https://raw.githubusercontent.com/recyclarr/recyclarr/master/schemas/config-schema.json) — Referenced in `recyclarr.yml` for validation
