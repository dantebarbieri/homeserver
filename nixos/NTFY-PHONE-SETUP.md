# ntfy Phone Notification Setup

Your homeserver sends push notifications via your self-hosted
[ntfy](https://ntfy.sh) instance at **<https://ntfy.danteb.com>**.

## Topic

All server alerts are published to a single topic:

```
homeserver-alerts
```

## Subscribe on Your Phone

### Android

1. Install **ntfy** from [Google Play](https://play.google.com/store/apps/details?id=io.heckel.ntfy) or [F-Droid](https://f-droid.org/packages/io.heckel.ntfy/).
2. Open the app → tap **+** (Add subscription).
3. Enter the **topic name**: `homeserver-alerts`
4. Tap the settings icon and set **Use another server** →
   `https://ntfy.danteb.com`
5. Save.

### iOS

1. Install **ntfy** from the [App Store](https://apps.apple.com/us/app/ntfy/id1625396347).
2. Open the app → tap **+**.
3. Enter `homeserver-alerts` as the topic.
4. Set the server to `https://ntfy.danteb.com`.
5. Subscribe.

## What Triggers Notifications

| Source | Trigger | Priority |
|---|---|---|
| **smartd** | SMART attribute failure, temperature warning, self-test error | high |
| **mdadm event** | Drive failure, degraded array, spare missing, rebuild | urgent/high |
| **drive-health-check** (every 6 h) | Degraded RAID, LVM health issues, missing PVs | urgent |
| **mdadm-scrub** (weekly Sun 2 AM) | Parity check started | low |
| **docker-interrupted-containers** (every Docker start) | Containers a daemon start stopped were restarted (default) or could not be (high) | default/high |
| **Any unit with `ntfy-failure@`** | Backups, offsite sync, updates and other jobs failing | high |

## When ntfy itself is down

ntfy runs in Docker, so a Docker outage also takes down the alert channel.
Alerts sent by root through `ntfy-notify` are queued in `/var/lib/ntfy-spool`;
interactive alerts from `danteb` are queued in `~/.local/state/ntfy-spool`.
`ntfy-spool-flush` retries both every five minutes once ntfy is back, reading
the user queue as `danteb`. Check the queues with `sudo ls /var/lib/ntfy-spool`
and `ls ~/.local/state/ntfy-spool`. Alerts cannot be queued if storage is full
or inaccessible; the command reports this failure.

## Test It

From the server, send a test notification:

```bash
# Using the ntfy-notify helper (installed system-wide)
ntfy-notify "Test Alert" "Hello from homeserver!" default "tada"
```

You should receive a push notification on your phone within seconds.

## Customizing

The ntfy URL and topic are defined in `lib/shared.nix`:

```nix
ntfyUrl   = "https://ntfy.danteb.com";
ntfyTopic = "homeserver-alerts";
```

Change these and run `sudo nixos-rebuild switch` to update all scripts
and services.

## Security Note

Subscriptions are intended to remain publicly readable, so never include
secrets in notifications. The intended policy restricts writes to the server's
publisher token; verify the live
[ntfy access control](https://docs.ntfy.sh/config/#access-control) settings
in `${DATA}/ntfy/config/server.yml` before relying on that restriction.
`ntfy-notify` reads the token from
`/srv/docker/data/ntfy/secrets/publisher-token`; never copy it into the repo.
