# Environment layout and private reconciliation

`docker/sample.env` is the canonical section, comment and key order for
`docker/.env`. Only values should differ. A quoted multiline production value
can occupy more physical lines than its placeholder. Keep credentials out of
Git, agent conversations and command output, including exception tracebacks.
`.gitignore` is not an access-control boundary.

Host identity settings are named `HOST_UID` and `HOST_GID`. Container-side
names such as `PUID`, `PGID`, `USER_UID`, `USER_GID`, `PLEX_UID` and `PLEX_GID`
must remain as specified by each image. The host names avoid shell-special
`UID`/`GID`, but this file must still never be sourced as a shell script.

## Safety boundary

Run `docker/scripts/reconcile-env.py` **on the server**. Its deterministic code
reads values locally; an agent should see only names and status messages.
Never upload `.env`, backups or resolved Compose configuration. Do not use
`source .env`, `set -x`, `docker compose config` without output capture, or
`docker inspect` to share diagnostics: these can execute content or expose keys.

The helper preserves every existing literal value, including quoting, empty
strings and multiline values. It adopts comments from the reviewed template,
not potentially sensitive comments in production. It refuses duplicate keys,
unsupported syntax, production-only keys, unexpected additions, concurrent
edits and changes to retained effective values or resolved Compose settings.
It does not generate passwords or rotate credentials.

Variables used by external or older integrations stay in the template's
retained sections until their removal is separately investigated. Being absent
from Compose is not evidence that a credential is safe to delete.

## Server workflow

Use the main Compose entry point throughout. The helper requires Python 3.9+
and Docker Compose v2 with JSON config output. On this NixOS server Python can
be supplied with `nix-shell -p python3 --run 'python3 ...'`.

First ensure the reviewed script and template are present on the server.
From `/srv/homeserver`, inventory names without printing values:

```sh
python3 docker/scripts/reconcile-env.py --inventory
```

Add production-only names to the template using blank or documented example
values, never by copying the production file. Review new template-only keys
before allowing their initial values. A dry run is the default:

```sh
python3 docker/scripts/reconcile-env.py
# If a reviewed new key is genuinely needed:
python3 docker/scripts/reconcile-env.py --allow-new NEW_KEY
```

Use the same explicit additions with `--apply` to back up and atomically replace
the file. `--template /path/to/reviewed/sample.env` allows a reviewed candidate
template to be checked before updating the server checkout's tracked template.

### Renaming an existing UID/GID installation

`--rename-host-ids` transfers each legacy `UID`/`GID` literal value to
`HOST_UID`/`HOST_GID`. It never substitutes the sample's numeric defaults.
If both the old and new name exist, or both are missing, migration is blocked.
Already-renamed settings are accepted unchanged.

Deploy this rename in two phases: first temporarily use
`${HOST_UID:-${UID}}` and `${HOST_GID:-${GID}}` in Compose so the old and new
files both work. Then run the helper with `--rename-host-ids` and any
explicitly reviewed `--allow-new` options. Only after the production file has
the new names should Compose be finalized to `${HOST_UID}` / `${HOST_GID}`.
Do not install the final strict references against an unmigrated `.env`.
Compare resolved configurations privately at each phase and coordinate with
other deployments. No container recreation is needed for this rename.

Before replacement the helper checks a private candidate using Compose's own
dotenv parser and compares the resolved main configuration. After replacement
it checks the actual configuration again, automatically restoring the original
if validation fails and no concurrent edit intervened. It never prints captured
Compose output, even on error. Run it during a quiet deployment window:
its lock serializes other reconciliations, not unrelated deploy commands.

The existing Immich services import the whole `.env`. Newly accepted keys and
the renamed host settings therefore also change environment entries for those
two services on their next recreation. The helper permits only these explicit
whole-file import changes, not changes to other existing settings. Removing
these broad imports is a separate architecture change.

## Backups, permissions and rollback

Backups default to
`~/.local/state/homeserver-env/backups/<UTC timestamp>.<random>/.env`,
outside the repository. Directories are mode `700`; files and candidates are
mode `600`. The helper verifies the exact backup bytes before replacement
and preserves production ownership. The production file must already exclude
group/other access and must not be a symlink.

These backups are **plaintext**, not encrypted. Treat them like the live file:
do not attach, commit, sync to an untrusted destination or leave additional
unprotected copies. Keep the verified pre-migration backup until satisfied;
include it only in encrypted backups. Choose retention deliberately rather
than accumulating copies forever. The script does not delete backups.

For rollback, stop overlapping updates and restore the desired private backup
to a mode-`600` temporary file alongside `docker/.env`, preserving ownership,
then rename it over `.env`. Do not print the contents or restart services just
to roll back formatting. A backup's old layout can be reconciled again later.

This workflow does not restart containers, change container identities,
move credentials to file secrets, or provide encrypted storage. Those are
separate changes. Long term, encrypted provisioning and least-privilege,
service-specific delivery can be introduced according to each image's support.
