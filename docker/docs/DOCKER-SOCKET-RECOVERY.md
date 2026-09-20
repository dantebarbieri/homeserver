# Docker socket recovery after daemon restarts

Docker live-restore preserves running containers when the daemon restarts, but
individual socket bind mounts can retain the replaced socket's old inode.
Homepage can keep serving HTTP while Docker status checks fail; Alloy loses log
collection; cAdvisor can export old samples that Prometheus rejects; and the VPN
namespace watcher cannot receive events to repair a future namespace mismatch.
An HTTP scrape being `up` does not establish that its metrics are fresh.

## Targeted recovery helper

`scripts/reconcile-docker-socket-consumers.sh` is intended for a host systemd oneshot
after `docker.service` starts or restarts. It refreshes only these known services
in Compose project **`compose`**, in this order:

1. `homepage`
2. `alloy`
3. `cadvisor`
4. `vpn-netns-watcher`

Immediately before each recreation, it queries Docker for running, non-one-off
containers with the exact project and service labels. Stopped, paused, absent,
other-project, and unrelated service containers are not selected. There is no
automatic rollback: enumeration or recreation failure stops processing, reports
the affected service, and exits nonzero. Services already refreshed remain so.

The helper uses the main `/srv/homeserver/docker/docker-compose.yml`, never a
category file, with an explicit project name and directory. Each selected service
is recreated serially with:

```text
up --no-deps --force-recreate --pull never --no-build -d <service>
```

No dependencies or unrelated containers are started/recreated. No images are
pulled or built, and no volumes/images are pruned. **Recreation does apply the
currently checked-out Compose configuration and `.env`, and uses locally
available image tags.** A tag already changed by a previous pull/build can resolve
to a different image than the old container used. This is not an in-place socket
remount or a guarantee of identical configuration/image identity. It causes a
brief interruption for each selected consumer.

Do not replace this recovery with a broad `/run` bind mount, remove meaningful
socket health checks, or set Prometheus `honor_timestamps: false` to disguise stale
metrics. The helper verifies command success, not full application readiness;
afterward check Homepage health, Alloy/watcher connection errors, and cAdvisor
sample freshness.

## Host lifecycle integration

Recommended `docker-socket-consumers.service` shape (the NixOS configuration owns
the actual unit):

```ini
[Unit]
Description=Refresh running Docker socket consumers
Requires=docker.service
After=docker.service
PartOf=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/srv/homeserver/docker
ExecStart=/absolute/path/to/bash /absolute/store/path/to/reconcile-docker-socket-consumers.sh
TimeoutStartSec=30min

[Install]
WantedBy=docker.service
```

`RemainAfterExit` keeps the oneshot active so `PartOf` propagates a later Docker
stop/restart; `After` orders recovery after the daemon is ready. Use an absolute
Bash executable and a store-pinned copy of the helper in `ExecStart`
(`"${pkgs.bash}/bin/bash ${../docker/scripts/reconcile-docker-socket-consumers.sh}"`
in NixOS). The service PATH must provide **Docker with the Compose plugin and
`flock` from util-linux**; the parent unit also includes coreutils. Run under the host account with
Docker access and permission to read the checkout/`.env` and open the lock file
(normally the existing root-owned system service context).

Both this helper and **the entire `docker-compose-update` operation**, including
checkout changes, must use the same exclusive lock:

```text
/run/lock/homeserver-compose.lock
```

The helper opens file descriptor 9 and waits at most 600 seconds using
`flock --exclusive --timeout 600 9`. The updater must acquire the same lock before
changing Git or invoking Compose. Do not wrap the helper in a second acquisition
of its own lock. Ensure `/run/lock` exists; do not unlink the lock file while
either job can run, because replacement defeats inode-based locking.

The lock serializes cooperating host jobs. Manual Docker/Compose operations and
the independent VPN watcher do not acquire it: avoid concurrent administrative
stops or deployments during recovery. Selection is rechecked immediately before
each recreation, but Docker provides no atomic “recreate only if still running”
operation covering an uncoordinated stop between that check and `compose up`.

`COMPOSE_DIR` and `COMPOSE_LOCK_FILE` can override the defaults for isolated tests
or alternate checkouts; the production unit should retain the defaults above.
Do not invoke the helper during a read-only audit: it deliberately recreates
containers. Adding these local files alone does not repair an existing outage;
deployment and production recovery require separate authorization.

## Local tests

The tests use mocked Docker and flock commands, never a Docker daemon. Fixtures
are created and removed under `docker/tests`, not in system temporary storage.

```bash
bash -n docker/scripts/reconcile-docker-socket-consumers.sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s docker/tests -p 'test_reconcile_docker_socket_consumers.py'
```
