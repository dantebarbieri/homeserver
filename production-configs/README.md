# Production Config Copies

This directory holds configuration files copied from the production server for local debugging and reference. **All contents except this README are gitignored.**

## How to Use

Copy configs from the server as needed:

```bash
# Example: copy Nginx Proxy Manager configs
scp -r homeserver:/etc/nginxproxymanager ./nginxproxymanager/

# Inspect ddclient permissions without copying its credentials
ssh server 'stat -c "uid=%u gid=%g mode=%a" /srv/docker/data/ddclient/config/ddclient.conf'
```

Subdirectories are created on demand — just copy what you need. When you're done debugging, delete the subdirectory. Git will ignore everything here except this README.

## Common Config Sources

### ddclient
- **Server source of truth**: `/srv/docker/data/ddclient/config/ddclient.conf`,
  bind-mounted as `/config/ddclient.conf` in the `ddclient` container.
  Provider configuration is managed on the server, not generated from Git.
- **Contains**: Dynamic DNS provider settings, update intervals, domain mappings
- **Secrets**: Existing `danteb.com` credentials remain in this mode-`0600`
  configuration. Do not copy the unredacted file into troubleshooting output.

#### Independent `mirklurk.wiki` DDNS

The same updater manages independent apex A and AAAA records for `mirklurk.wiki`;
neither record aliases `danteb.com`. The records must already exist in Cloudflare
with **Proxied** enabled and TTL **Auto**. Installed ddclient 4.0.0 updates only
record content, preserving proxy status and TTL; it does not create records or
support a `cloudflare-proxied` option.

The separate token needs **Zone / DNS / Edit** and **Zone / Zone / Read**, scoped
to **Include / Specific zone / mirklurk.wiki** only. Store it on the server at
`/srv/docker/data/ddclient/config/mirklurk.wiki.token`, owned by numeric UID/GID
`1000:1000`, mode `0600`, with no trailing newline. Never commit or print it.
`docker/compose.core.yml` maps `FILE__CLOUDFLARE_MIRKLURK_TOKEN` to that file's
container path; LinuxServer loads `CLOUDFLARE_MIRKLURK_TOKEN` at container startup.
Token rotation therefore requires restarting/recreating **only ddclient** using
the main Compose entry point, not the standalone category file.

The server configuration appends this single host-local stanza, leaving the
existing `danteb.com` entries unchanged:

```ini
protocol=cloudflare, \
server=api.cloudflare.com/client/v4, \
zone=mirklurk.wiki, \
login=token, \
password_env=CLOUDFLARE_MIRKLURK_TOKEN, \
use=disabled, \
usev4=webv4, \
webv4=https://ipv4.icanhazip.com, \
usev6=webv6, \
webv6=https://ipv6.icanhazip.com, \
mirklurk.wiki
```

Keep the continuation backslashes: these settings must remain host-local.
Load the token environment before activating the stanza. ddclient rereads its
configuration every 300 seconds, so a live config edit can activate without a
restart. Keep any rollback backup on the server with mode `0600`; removing only
this stanza disables the new domain's updates without changing `danteb.com`.

Verify both families in filtered updater status and verify origin content plus
proxy flags in Cloudflare. Public DNS shows Cloudflare edge addresses, not the
origin content tracked by DDNS. Proxying hides the home IP from routine lookups,
not historical or cross-domain correlation. NPM routing, certificates, and the
wiki's canonical URL are separate configuration steps; DDNS alone does not
migrate the wiki. HTTPS should use Full (strict) with a valid origin certificate.

### nginxproxymanager
- **Server path**: `/srv/docker/data/nginxproxymanager/`
- **Contains**: SQLite database, generated nginx configs, Let's Encrypt certificates, Authelia SSO integration snippets
- **Key files**:
  - `snippets/authelia-authrequest.conf` — Authelia forward-auth request config
  - `snippets/authelia-location.conf` — Authelia location block for protected routes
  - `snippets/proxy.conf` — Common proxy headers
  - `letsencrypt/` — TLS certificates (also used by Matrix Coturn for RTC)
- **Secrets**: TLS private keys, database credentials

### authelia
- **Server path**: `/srv/docker/data/authelia/`
- **Contains**: Authelia SSO configuration, user database, secrets
- **Key files**:
  - `config/configuration.yml` — Main config: access control rules, session, storage, notification providers
  - `config/users_database.yml` — Local user database (argon2id hashed passwords, groups)
  - `secrets/` — Docker secrets (session, JWT, storage password, encryption key, email password)
- **Secrets**: Hashed passwords, encryption keys, SMTP credentials

## Warning

These files contain secrets (API tokens, TLS keys, database credentials). **Never commit them to git.** The `.gitignore` at the repo root prevents this, but always double-check with `git status` before committing.
