# Retired Model Recipe Applications

The four model-generated experiments are retired:

| Service | Former public URL | Retained data |
|---|---|---|
| `recipe-gpt-sol` | `https://gpt-sol.recipe.danteb.com` | `${DATA}/recipe-gpt-sol` |
| `recipe-gemini` | `https://gemini.recipe.danteb.com` | `${DATA}/recipe-gemini` |
| `recipe-claude` | `https://claude.recipe.danteb.com` | `${DATA}/recipe-claude` |
| `recipe-grok` | `https://grok.recipe.danteb.com` | `${DATA}/recipe-grok` |

The handwritten **Recipe Collection** is the `recipe` service at
`https://recipe.danteb.com`, defined in `compose.websites.yml`. Its source,
container, proxy host and `${DATA}/recipe` data must remain intact.

The experiment Compose file, Homepage entries and provisioning helpers have
been removed. After deploying this change, retire only the four named
containers and their four exact-domain NPM proxy hosts. Use NPM's supported
REST API or UI, not direct database edits. Remove their shared TLS certificate
only after confirming its domain set is exactly the four retired domains and
that no remaining proxy, redirection or dead host references it.

Keep the bind-mounted data directories and existing backups unless the owner
separately requests data deletion. Do not use `docker compose down`, volume
deletion or a global prune for this cleanup. A regular `up -d` alone does not
remove old containers whose service definitions have been deleted.

The former immutable source SHAs and deployment instructions remain in Git
history if an experiment needs to be restored.
