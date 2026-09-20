# Recyclarr Configs

Personal [Recyclarr](https://github.com/recyclarr/recyclarr) configuration for syncing TRaSH Guides quality profiles and custom formats to Sonarr and Radarr.

## Repository Structure

```
.
├── recyclarr.yml          # Main configuration (quality profiles, custom formats, etc.)
├── settings.yml           # Instance connection settings (URLs, API key references)
├── secrets.yml.example    # Template for secrets — copy to secrets.yml and fill in
├── configs/               # Additional split config files (optional)
├── includes/              # Reusable YAML fragments (optional)
└── README.md
```

## Setup

1. Clone this repo.
2. Copy the secrets template and fill in your API keys:
   ```sh
   cp secrets.yml.example secrets.yml
   # Edit secrets.yml with your actual API keys and instance URLs
   ```
3. Deploy the config files to your Recyclarr config directory on your server (typically `~/.config/recyclarr/` or the Docker volume mount).

## Secrets

`secrets.yml` is gitignored and must never be committed. It contains API keys and instance URLs. See `secrets.yml.example` for the expected structure.

On this server the file is `/srv/homeserver/recyclarr-configs/secrets.yml`,
also mounted as `/config/secrets.yml` in the Recyclarr container. Keep it mode
`600`, owned by the container's UID 1000. The template uses the internal Docker
URLs `http://sonarr:8989` and `http://radarr:7878`; replace only the API-key
placeholders with values from each application's **Settings > General**.
Dummy keys allow configuration parsing but cannot authenticate a sync.
Deploy the committed custom-format configuration before a full sync: an older
configuration with `reset_unmatched_scores` can clear a manually applied score.

## Dolby Vision playback compatibility

The standard `4K UHD - 2160p` and `At most 2160p` profiles in both apps assign
TRaSH's **DV (w/o HDR fallback)** custom format its default **-10000** score.
This penalizes DV-only WEB releases while retaining the existing preference
for Dolby Vision releases that also advertise HDR fallback. It does not
change anime scoring or modify already-downloaded files.

This is release-title/source matching, not an inspection of the video's Dolby
Vision profile, so it is a prevention layer rather than a playback guarantee.
In particular, a Dolby Vision Profile 5 file has no HDR10-compatible base
layer and may need a separate, properly tone-mapped compatibility version.
See [Plex playback](../docker/docs/PLEX.md) for that distinction.

## AI-Assisted Development

This repo is intentionally small so that AI coding tools (Claude Code, Copilot, etc.) can load the full context. When making changes:

- **recyclarr.yml** is the main file you'll iterate on — quality profiles, custom format assignments, and score overrides all live here.
- **settings.yml** rarely changes unless you add/remove instances.
- Refer to the [TRaSH Guides](https://trash-guides.info/) and [Recyclarr Wiki](https://recyclarr.dev/) for valid custom format Trash IDs and configuration options.

## Deployment

The recyclarr container runs via the [homeserver-docker](https://github.com/dantebarbieri/homeserver-docker) repo, with config mounted at `${DATA}/recyclarr/config:/config`.

After editing configs locally, sync them to the server and run recyclarr:

```sh
# 1. Copy configs to the server's recyclarr config directory
rsync -av --exclude='.git' --exclude='secrets.yml.example' \
  recyclarr.yml settings.yml includes/ \
  user@server:$DATA/recyclarr/config/

# 2. Run recyclarr sync (from the docker repo directory on the server)
docker compose -f compose.starr.yml run --rm recyclarr sync
```

Or to only sync one service:

```sh
docker compose -f compose.starr.yml run --rm recyclarr sync sonarr
docker compose -f compose.starr.yml run --rm recyclarr sync radarr
```

> **Note:** `secrets.yml` must be managed on the server directly — never committed to this repo.
