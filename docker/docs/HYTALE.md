# Hytale authentication recovery

The `hytale-server` service uses the persistent `compose_hytale-server` volume.
Do not remove that volume, its worlds, or `/data/.machine-id` during recovery.
Use the main Compose entry point in `/srv/homeserver/docker`.

## Downloader versus game-server authentication

There are two independent authentication stages:

1. The official downloader uses `/data/.hytale-downloader-credentials.json`
   to check/download releases before Java starts.
2. The game server authenticates player connections after Java starts. The
   documented console flow is `/auth persistence Encrypted`, then
   `/auth login device`.

An `invalid_grant` error explicitly saying the refresh token expired while
fetching the game-assets manifest is a **downloader** failure. Repeated restarts,
an image rollback, or the game server's `/auth` command cannot renew that expired
grant. It needs the owner's interactive device login.

## Safe recovery procedure

Stop the already-failing service during reauthorization to avoid its restart
loop. Preserve the old credential file as a private backup; never print its
contents, copy it into this repository, or paste tokens into chat.

The installed downloader supports `-credentials-path`, `-skip-update-check`
and `-print-version`. Run it as a one-off Compose container with the same data
volume, using a **new, nonexistent credential filename in a mode-700 directory**
and a restrictive `umask 077`. The entrypoint is:

```text
/data/.hytale-downloader/hytale-downloader
```

Request `-print-version` rather than a download while authorizing. Follow its
official browser URL/device-code instructions yourself. Only after successful
authentication and a successful version query should the new credential file
replace the expired one; retain the private backup, use mode 600, and preserve
the container user's ownership. Failed or canceled authorization must leave
the original credential file and game data untouched.

Then start only `hytale-server` using the main Compose configuration and check
startup and authentication status. A second game-server login may be needed;
use its console flow only after the downloader stage succeeds. Do not switch
to offline/insecure authentication or disable update checks to hide the error.

Upstream references:

- [Image configuration and authentication](https://github.com/Hybrowse/hytale-server-docker/blob/main/docs/image/configuration.md)
- [Troubleshooting](https://github.com/Hybrowse/hytale-server-docker/blob/main/docs/image/troubleshooting.md)
