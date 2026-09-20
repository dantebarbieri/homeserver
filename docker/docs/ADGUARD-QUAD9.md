# Quad9 DoH transport workaround

AdGuard Home v0.107.79 intermittently logged `unexpected EOF` against
`https://dns10.quad9.net/dns-query`, including after the host reboot. Other
upstreams and local DNS resolution remained functional. The failures occurred
within tens of milliseconds, not at the configured ten-second timeout.

Direct certificate-checked HTTP/2 requests worked over IPv4 and IPv6, including
connection reuse. Forced HTTP/1.1 returned 505, but AdGuard's DNS transport
enables HTTP/2, so that difference alone does not prove the intermittent cause.
See [AdguardTeam/AdGuardHome#8311](https://github.com/AdguardTeam/AdGuardHome/issues/8311).

The reversible workaround changes only the Quad9 transport:

```diff
- https://dns10.quad9.net/dns-query
+ tls://dns10.quad9.net
```

`dns10` is Quad9's **unfiltered** service. Do not substitute `dns.quad9.net`,
which changes filtering policy. Keep Cloudflare, Google, bootstrap DNS, fallbacks,
IPv6, load balancing and timeouts unchanged. No router settings are involved.

## Deployment and rollback

First verify TLS certificates and complete A/AAAA DNS-over-TLS exchanges on port
853 from the server, including connection reuse. Merely opening TCP port 853
does not validate DNS or TLS.

The private production file is
`/srv/docker/data/adguardhome/confdir/AdGuardHome.yaml`. Do not copy it into Git.
`scripts/adguard-quad9-dot.py` checks the exact upstream entry without displaying
the configuration. Its default mode does not write anything. With `--apply`,
it refuses to edit a running `adguardhome`, creates a mode-600 sibling backup,
preserves the original ownership/mode, and atomically replaces only that URL.

During an authorized maintenance window, stop **only** `adguardhome` using the
main Compose entry point, apply the migration, then start it again. DNS is briefly
unavailable while the container is stopped. If migration fails, restart the
unchanged container rather than leaving DNS down. Validate configuration,
client A/AAAA answers, and upstream error logs after restart. Observe normal
traffic for at least 30 minutes; a clean short probe is not proof that an
intermittent problem is permanently fixed.

To roll back, stop the container, restore the private
`AdGuardHome.yaml.pre-quad9-dot.<UTC timestamp>` backup to `AdGuardHome.yaml`,
preserving the live file's ownership and mode, then start the same service.
Do not restore an old backup over unrelated later UI configuration changes.

The pre-existing plaintext fallback resolvers are deliberately unchanged; changing
that privacy/failure policy needs a separate decision.
