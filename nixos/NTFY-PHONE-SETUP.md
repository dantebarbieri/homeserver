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

## Test It

From the server, send a test notification:

```bash
# Using the ntfy-notify helper (installed system-wide)
ntfy-notify "Test Alert" "Hello from homeserver!" default "tada"

# Or with raw curl
curl -H "Title: Test" -d "It works!" https://ntfy.danteb.com/homeserver-alerts
```

You should receive a push notification on your phone within seconds.

## Customizing

The ntfy URL and topic are defined at the top of `configuration.nix`:

```nix
ntfyUrl   = "https://ntfy.danteb.com";
ntfyTopic = "homeserver-alerts";
```

Change these and run `doas nixos-rebuild switch` to update all scripts
and services.

## Security Note

The `homeserver-alerts` topic is **open** — anyone who knows the URL can
subscribe (read) or publish (write). If you want to restrict access,
configure [ntfy access control](https://docs.ntfy.sh/config/#access-control)
in your ntfy container's config at `${DATA}/ntfy/config/server.yml`.
