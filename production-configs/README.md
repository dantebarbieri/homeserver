# Production Config Copies

This directory holds configuration files copied from the production server for local debugging and reference. **All contents except this README are gitignored.**

## How to Use

Copy configs from the server as needed:

```bash
# Example: copy Nginx Proxy Manager configs
scp -r homeserver:/etc/nginxproxymanager ./nginxproxymanager/

# Example: copy ddclient config
scp homeserver:/etc/ddclient/ddclient.conf ./ddclient/
```

Subdirectories are created on demand — just copy what you need. When you're done debugging, delete the subdirectory. Git will ignore everything here except this README.

## Common Config Sources

### ddclient
- **Server path**: `/etc/ddclient/ddclient.conf`
- **Contains**: Dynamic DNS provider settings, update intervals, domain mappings
- **Secrets**: API tokens for DNS provider

### nginxproxymanager
- **Server path**: `/srv/docker/data/nginxproxymanager/`
- **Contains**: SQLite database, generated nginx configs, Let's Encrypt certificates, Authelia SSO integration snippets
- **Key files**:
  - `snippets/authelia-authrequest.conf` — Authelia forward-auth request config
  - `snippets/authelia-location.conf` — Authelia location block for protected routes
  - `snippets/proxy.conf` — Common proxy headers
  - `letsencrypt/` — TLS certificates (also used by Matrix Coturn for RTC)
- **Secrets**: TLS private keys, database credentials

## Warning

These files contain secrets (API tokens, TLS keys, database credentials). **Never commit them to git.** The `.gitignore` at the repo root prevents this, but always double-check with `git status` before committing.
