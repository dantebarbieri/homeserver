# Model Recipe Applications

Four independent implementations of `dantebarbieri/recipe-app-ai` run side by side for UX evaluation. Their build contexts use full commit SHAs, so a moved branch cannot silently change a deployed image.

| Service | Source branch | Commit | Internal port | Storage | Public URL |
|---|---|---|---:|---|---|
| `recipe-gpt-sol` | `dantebarbieri-gpt-5-6-sol` | `470a0d760133e32dd3ee4618d5681bc4bc51a6eb` | 3011 | `${DATA}/recipe-gpt-sol` (SQLite) | `https://gpt-sol.recipe.danteb.com` |
| `recipe-gemini` | `dantebarbieri-gemini-3-1-pro` | `42b6eaffacba8a7b31d16c38994ebd6386b45207` | 3012 | `${DATA}/recipe-gemini/recipes` (JSON documents) | `https://gemini.recipe.danteb.com` |
| `recipe-claude` | `dantebarbieri-claude-opus-5` | `c9009e1205011cc05b8854864809d4625b0a3146` | 3013 | `${DATA}/recipe-claude` (JSON documents under `recipes/`) | `https://claude.recipe.danteb.com` |
| `recipe-grok` | `dantebarbieri-grok-4-5` | `5eab0518fa271615f8b4b584de2e29f02b2c5017` | 3014 | `${DATA}/recipe-grok/recipes` (JSON documents) | `https://grok.recipe.danteb.com` |

The applications publish no host ports. Nginx Proxy Manager reaches their unique ports over the shared `proxy` network. The four demo sites are intentionally public and have no application or proxy authentication.

## Initial deployment

Run from `/srv/homeserver/docker`:

```bash
./scripts/prepare-recipe-app-storage.sh
docker compose build recipe-gpt-sol recipe-gemini recipe-claude recipe-grok
docker compose up -d recipe-gpt-sol recipe-gemini recipe-claude recipe-grok
./scripts/configure-recipe-app-proxies.sh
```

The ownership helper uses the runtime UIDs from the pinned images. Recheck those IDs before changing a base image. On an empty volume, GPT-5.6 Sol, Claude Opus 5, and Grok 4.5 create their implementation-provided demo recipes; Gemini starts empty. Do not copy recipes between implementations when evaluating them.

The pinned Grok image contains a CRLF-encoded `/entrypoint.sh`, which Linux cannot execute directly. Compose mounts `scripts/recipe-grok-entrypoint.sh`, an LF-normalized copy of the same seed-on-empty logic, until the pinned source commit changes.

## Nginx Proxy Manager provisioning

`scripts/configure-recipe-app-proxies.sh` provisions the NPM state through the REST API; the four hosts were not entered manually. The outer script uses Docker to re-execute itself inside `bmc-ip-monitor`, which already has `curl`, `jq`, the NPM credentials, and access to NPM's internal network. It then:

1. Authenticates with `POST /api/tokens`.
2. Reuses the exact-name Let's Encrypt SAN certificate when its domain set matches, or creates it with `POST /api/nginx/certificates` when absent.
3. Finds each exact domain with `GET /api/nginx/proxy-hosts`.
4. Updates an existing host with `PUT /api/nginx/proxy-hosts/<id>`, creates it with `POST /api/nginx/proxy-hosts` when absent, and refuses to choose when duplicate matches exist.

The desired host and certificate settings are tracked in the script. NPM's generated records remain in `${DATA}/nginxproxymanager/data`, with certificate material in `${DATA}/nginxproxymanager/letsencrypt`; no generated NPM database or certificate files are committed. Re-running the script is idempotent: it reuses the SAN certificate and updates the same exact-domain hosts instead of creating duplicates.

| Domain | Upstream |
|---|---|
| `gpt-sol.recipe.danteb.com` | `http://recipe-gpt-sol:3011` |
| `gemini.recipe.danteb.com` | `http://recipe-gemini:3012` |
| `claude.recipe.danteb.com` | `http://recipe-claude:3013` |
| `grok.recipe.danteb.com` | `http://recipe-grok:3014` |

## Validation

Container health:

```bash
docker compose ps recipe-gpt-sol recipe-gemini recipe-claude recipe-grok
docker inspect recipe-gpt-sol recipe-gemini recipe-claude recipe-grok \
  --format '{{.Name}} restart={{.HostConfig.RestartPolicy.Name}} health={{.State.Health.Status}}'
```

Read-only application checks from the proxy network:

```bash
docker exec nginxproxymanager curl -fsS http://recipe-gpt-sol:3011/api/health
docker exec nginxproxymanager curl -fsS http://recipe-gemini:3012/ >/dev/null
docker exec nginxproxymanager curl -fsS http://recipe-claude:3013/api/health
docker exec nginxproxymanager curl -fsS http://recipe-grok:3014/api/recipes
```

Each public URL should return its application landing page directly over HTTPS without an authentication redirect. The following invalid requests exercise each JSON API's schema validation without creating data:

```bash
curl -i -X POST -H 'Content-Type: application/json' -d '{}' \
  http://recipe-gpt-sol:3011/api/recipes
curl -i -X POST -H 'Content-Type: application/json' -d '{}' \
  http://recipe-claude:3013/api/recipes
curl -i -X POST -H 'Content-Type: application/json' -d '{}' \
  http://recipe-grok:3014/api/recipes
```

GPT-5.6 Sol and Claude Opus 5 return 422; Grok 4.5 returns 400. Gemini only exposes a Next.js Server Action, so validate it non-destructively by submitting an incomplete form in the browser and confirming the client validation prevents the save.

## Backup and restore

All four bind mounts are included in the existing daily encrypted rclone sync of `/srv/docker/data`. For a transactionally consistent manual snapshot, briefly stop the four applications before archiving their directories:

```bash
docker compose stop recipe-gpt-sol recipe-gemini recipe-claude recipe-grok
sudo tar -C /srv/docker/data -czf /data/automated-backups/recipe-apps-$(date +%F).tgz \
  recipe-gpt-sol recipe-gemini recipe-claude recipe-grok
docker compose start recipe-gpt-sol recipe-gemini recipe-claude recipe-grok
```

Restore only while the affected application is stopped, preserve the directory ownership listed in `prepare-recipe-app-storage.sh`, then start it and repeat the health and read checks.

## Update and rollback

To update one implementation, change its image tag, full SHA build context, revision label, and this document in the same commit. Build and health-check that service before merging.

Rollback the homeserver commit (or restore the prior image tag and SHA), restore its matching data snapshot if the application changed the on-disk schema, then rebuild and recreate only that service:

```bash
docker compose build <service>
docker compose up -d --force-recreate <service>
```
