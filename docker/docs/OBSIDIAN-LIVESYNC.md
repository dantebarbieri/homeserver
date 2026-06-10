# Obsidian Self-hosted LiveSync (CouchDB)

Real-time, end-to-end-encrypted sync of an Obsidian vault between desktop and
iPhone using the community plugin
[**obsidian-livesync**](https://github.com/vrtmrz/obsidian-livesync) against a
self-hosted CouchDB. Replaces first-party Obsidian Sync ($48/yr).

- **Service:** `couchdb` in `compose.utilities.yml` (`couchdb:3` image)
- **Config:** `docker/couchdb/local.ini` (mounted read-only into
  `/opt/couchdb/etc/local.d/`)
- **Data:** named volume `couchdb-data` → `/opt/couchdb/data`
- **Public URL:** `https://couchdb.danteb.com` (via Nginx Proxy Manager)
- **Vault:** the `docs/` folder of the separate **WorldForge** repo (that repo
  is not touched by this setup — this only stands up the server)

The admin credentials live in `.env` as `COUCHDB_USER` / `COUCHDB_PASSWORD`
(placeholders in `sample.env`). The same user/password are entered in the
LiveSync plugin.

---

## 1. Configure `.env`

On the server, set the credentials in `/srv/homeserver/docker/.env`:

```bash
COUCHDB_USER=obsidian
COUCHDB_PASSWORD='<openssl rand -hex 24>'   # avoid URL-breaking characters
```

## 2. Start the service

Always from the `docker/` directory, via the main entrypoint (never
`-f compose.utilities.yml`, which creates the wrong networks):

```bash
cd /srv/homeserver/docker
docker compose up -d couchdb
docker compose logs -f couchdb     # confirm clean startup
```

`local.ini` sets `[couchdb] single_node = true`, so CouchDB **auto-creates** the
system databases (`_users`, `_replicator`, `_global_changes`) on first start —
no manual cluster setup needed.

## 3. Reverse proxy (Nginx Proxy Manager)

Create a **Proxy Host** in NPM (proxy hosts are managed in the NPM web UI, not
in this repo):

- **Domain:** `couchdb.danteb.com`
- **Scheme / Forward Host / Port:** `http` → `couchdb` → `5984`
- **Websockets Support:** ON (LiveSync uses CouchDB `_changes` continuous feeds)
- **Block Common Exploits:** OFF (it interferes with large replication POST
  bodies and `_bulk_docs`)
- **SSL:** request a Let's Encrypt cert, Force SSL, HTTP/2 — mobile Obsidian
  requires a valid TLS endpoint. Do **not** expose plain HTTP to the internet.

DNS: `*.danteb.com` is already a wildcard CNAME, so no Cloudflare change is
needed — only the NPM proxy host.

> Naming note: per the repo subdomain convention (concept over implementation,
> e.g. `git` not `forgejo`) you may optionally add an NPM **redirection host**
> `obsidian.danteb.com` → `couchdb.danteb.com`. The primary host stays
> `couchdb.danteb.com` to match the verification command below.

## 4. (Optional) Re-assert config via REST

`local.ini` already applies every required setting declaratively. If you ever
need to (re)apply them against a running node — or you installed CouchDB without
the mounted `local.ini` — run the official initializer:

```bash
curl -s https://raw.githubusercontent.com/vrtmrz/obsidian-livesync/main/utils/couchdb/couchdb-init.sh \
  | hostname=https://couchdb.danteb.com username="$COUCHDB_USER" password="$COUCHDB_PASSWORD" bash
```

## 5. Verify

```bash
# Liveness (no auth required) — must return {"status":"ok"}
curl -s https://couchdb.danteb.com/_up

# Authenticated welcome — must return the CouchDB version banner
curl -s -u "$COUCHDB_USER:$COUCHDB_PASSWORD" https://couchdb.danteb.com/

# System DBs exist (created by single_node = true)
curl -s -u "$COUCHDB_USER:$COUCHDB_PASSWORD" https://couchdb.danteb.com/_all_dbs
# => [..., "_replicator", "_users", "_global_changes"]
```

---

## 6. LiveSync plugin settings

The vault database is created automatically on first replication — just pick a
name (e.g. `worldforge`) and use it consistently on every device.

### Recommended: Setup wizard / setup URI (do this once on desktop)

The maintainer recommends configuring via the **Setup wizard** rather than by
hand, because it also sets the recommended advanced options. Generate a setup
URI on the desktop and import it on the phone:

```bash
export hostname=https://couchdb.danteb.com
export database=worldforge          # the remote DB name (your choice)
export username="$COUCHDB_USER"
export password="$COUCHDB_PASSWORD"
export passphrase='<your E2EE passphrase>'   # end-to-end encryption secret
deno run -A https://raw.githubusercontent.com/vrtmrz/obsidian-livesync/main/utils/flyio/generate_setupuri.ts
```

This prints an `obsidian://setuplivesync?settings=...` URI and a short
**setup-URI passphrase** (e.g. `patient-haze`). On each device: install
Self-hosted LiveSync → command palette → **"Use the copied setup URI"** → paste
the URI → type the setup-URI passphrase → answer `yes` / `Set it up` → finish
with `Keep them disabled` → `Reload app without save`.

> The **E2EE passphrase** (`passphrase`) encrypts the vault contents and must be
> identical on every device. The **setup-URI passphrase** only protects the URI
> in transit and is different by design — type it manually, don't paste it.

### Manual values (if not using the wizard)

In **Settings → Self-hosted LiveSync → Remote Database configuration**:

| Field | Value |
|-------|-------|
| Remote Type | `CouchDB` |
| URI | `https://couchdb.danteb.com` |
| Username | value of `COUCHDB_USER` (e.g. `obsidian`) |
| Password | value of `COUCHDB_PASSWORD` |
| Database name | `worldforge` (must match on all devices) |
| End-to-End Encryption | **On**, set a passphrase (same on every device) |
| Path Obfuscation | optional (recommended On for privacy) |

Click **Test Database Connection** then **Check database configuration** — both
should pass. Then enable **LiveSync** (or your preferred sync mode) and run
**Sync now** from the first (desktop) device that holds the vault content.
