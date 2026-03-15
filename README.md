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

## AI-Assisted Development

This repo is intentionally small so that AI coding tools (Claude Code, Copilot, etc.) can load the full context. When making changes:

- **recyclarr.yml** is the main file you'll iterate on — quality profiles, custom format assignments, and score overrides all live here.
- **settings.yml** rarely changes unless you add/remove instances.
- Refer to the [TRaSH Guides](https://trash-guides.info/) and [Recyclarr Wiki](https://recyclarr.dev/) for valid custom format Trash IDs and configuration options.

## Deployment

After editing configs locally, sync them to your server:

```sh
# Example: rsync to server
rsync -av --exclude='.git' --exclude='secrets.yml.example' \
  recyclarr.yml settings.yml configs/ includes/ \
  user@server:/path/to/recyclarr/config/
```

> **Note:** You'll still need to manage `secrets.yml` on the server directly.
