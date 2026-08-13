# Model Recipe Applications

Four independent implementations of `dantebarbieri/recipe-app-ai` run side by side for UX evaluation. Their build contexts use full commit SHAs, so a moved branch cannot silently change a deployed image.

| Service | Source branch | Commit | Internal port | Storage | Public URL |
|---|---|---|---:|---|---|
| `recipe-gpt-sol` | `dantebarbieri-gpt-5-6-sol` | `470a0d760133e32dd3ee4618d5681bc4bc51a6eb` | 3011 | `${DATA}/recipe-gpt-sol` (SQLite) | `https://gpt-sol.recipe.danteb.com` |
| `recipe-gemini` | `dantebarbieri-gemini-3-1-pro` | `42b6eaffacba8a7b31d16c38994ebd6386b45207` | 3012 | `${DATA}/recipe-gemini/recipes` (JSON documents) | `https://gemini.recipe.danteb.com` |
| `recipe-claude` | `dantebarbieri-claude-opus-5` | `c9009e1205011cc05b8854864809d4625b0a3146` | 3013 | `${DATA}/recipe-claude/recipes` (JSON documents) | `https://claude.recipe.danteb.com` |
| `recipe-grok` | `dantebarbieri-grok-4-5` | `5eab0518fa271615f8b4b584de2e29f02b2c5017` | 3014 | `${DATA}/recipe-grok/recipes` (JSON documents) | `https://grok.recipe.danteb.com` |

The applications publish no host ports. Nginx Proxy Manager reaches their unique ports over the shared `proxy` network. The proxy hosts use one exact-name SAN certificate and the standard Authelia forward-auth snippets because none of the applications has built-in authentication.

## Initial deployment

Run from `/srv/homeserver/docker`:

```bash
sudo ./scripts/prepare-recipe-app-storage.sh
docker compose build recipe-gpt-sol recipe-gemini recipe-claude recipe-grok
docker compose up -d recipe-gpt-sol recipe-gemini recipe-claude recipe-grok
./scripts/configure-recipe-app-proxies.sh
```

The ownership helper uses the runtime UIDs from the pinned images. Recheck those IDs before changing a base image. On an empty volume, GPT-5.6 Sol, Claude Opus 5, and Grok 4.5 create their implementation-provided demo recipes; Gemini starts empty. Do not copy recipes between implementations when evaluating them.

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

The public URLs should return the Authelia redirect before login and the application landing page after login. The following invalid requests exercise each JSON API's schema validation without creating data:

```bash
curl -i -X POST -H 'Content-Type: application/json' -d '{}' \
  http://recipe-gpt-sol:3011/api/recipes
curl -i -X POST -H 'Content-Type: application/json' -d '{}' \
  http://recipe-claude:3013/api/recipes
curl -i -X POST -H 'Content-Type: application/json' -d '{}' \
  http://recipe-grok:3014/api/recipes
```

GPT-5.6 Sol returns 422; Claude Opus 5 and Grok 4.5 return 400. Gemini only exposes a Next.js Server Action, so validate it non-destructively by submitting an incomplete form in the browser and confirming the client validation prevents the save.

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
