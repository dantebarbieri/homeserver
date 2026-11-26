# Modem and router admin portals

| Portal | TLS upstream from NPM | Verified name | Login landing page |
|---|---|---|---|
| [Modem](https://modem.danteb.com/) | `192.168.100.1:443` | `0000BAE2ED44` | `/Login.html` |
| [Router](https://router.danteb.com/) | `192.168.50.1:8443` | `router.asus.com` | `/Main_Login.asp?redirct=false` |

These are public HTTPS hosts, **not** Tailscale-only. Like `ipmi.danteb.com`,
they use the existing wildcard DNS/certificate and require Authelia `admins`
two-factor authentication before the device login. Unlike IPMI, both verify
the upstream certificate. No router port forward to either device is needed.
If calcifer is down but the home WAN and No-Face are up, use the
[direct Tailscale routes](../../README.md#tailscale-remote-access).

## Restore the gates before publishing a host

Put these rules **first** under Authelia's `access_control.rules`. Validate the
config, restart Authelia, and check with `authelia access-control check-policy`:
an `admins` member must match `two_factor`; any other authenticated user
must match `deny`, including on static assets and POSTs.

```yaml
- domain: [modem.danteb.com, router.danteb.com]
  subject: group:admins
  policy: two_factor
- domain: [modem.danteb.com, router.danteb.com]
  policy: deny
```

In each NPM proxy host select the wildcard certificate, Force SSL, HTTP/2 and
HSTS. Leave caching, custom locations and WebSockets off. Set the *default*
destination to `http://127.0.0.1:1` (intentionally unusable). Paste the output
of `docker/scripts/device-admin-config.sh modem` or `router` into **Advanced**.
Only the explicit, auth-gated location forwards to a device. It strips the
`authelia_session` cookie and translates only the portal's own Origin/Referer;
if the Authelia cookie is renamed, update the proxy template and modem auth
subrequest before changing it.
The root redirects to the login page **after** authorization, avoiding the
modem's plain-HTTP redirect and the router's vendor-host redirect.

The S33 uses `HNAP_AUTH` and `SOAPAction` on `/HNAP1/`. Enable underscored
headers **only on the modem TLS vhost**: without `HNAP_AUTH` the login can
succeed, then the status page immediately sends the user back to the login
screen. The modem's internal auth request sends only the SSO cookie and
explicit authorization metadata to Authelia, not the device's headers or
cookies. Test the rendered config without any device or credentials using
`sh docker/tests/test-device-admin.sh` with the NPM image already available.

## Upstream trust and replacement

Each host trusts only its own public CA file in the NPM data volume
(`/data/device-admin/` inside `nginxproxymanager`). Do not import these CAs
as system-wide roots. The fingerprints below are SHA-256 of DER certificates,
recorded at enrollment (2026-11-26); runtime checks are CA **and** device
name, not an exact leaf pin.

| File | Trusted root SHA-256 | Enrolled device leaf SHA-256 |
|---|---|---|
| `modem-ca.pem` (ARRIS HWROB Device Root CA) | `acafb5ac9183fe23b4f2c7953274166fc666e25a8188ae48e809c256bb853a3d` | `59fe5cbe68037a84ece4aa500d8d6dcc4fc92513f822dbdc1425d31f9bdad587` |
| `router-ca.pem` (ASUS GT-BE98 Pro root) | `314ca1cc05c791987c17131d049d84197ce9efe12e2356cd2299033d35e27e39` | `e46426c42edac04d49cdc1407d3fa6d4b4ef044ca563b4386412bdf2869f08ca` |

A firmware change, certificate regeneration or device replacement that changes
the trust chain or name must **fail closed**; do not turn verification off to
clear a 502. A renewed leaf under the same CA and verified name can still pass.

1. Independently confirm the new device identity on the trusted local path.
   For ASUS use **Administration → System → Export Root Certificate** in the
   trusted admin session (`cert.crt` only; do **not** renew, export a key, or
   download a config backup). For ARRIS take the root from the chain served
   by the verified device; the modem also serves its intermediate. Never
   promote a root just because an unauthenticated connection offered it.
2. Hash each candidate's actual DER: `openssl x509 -in cert.pem -outform DER | openssl dgst -sha256`.
   Use a separate invocation to inspect SANs; combining `-ext` and
   `-fingerprint` on Homebrew OpenSSL 4.1 produced a different digest.
3. Stage the public root as `/data/device-admin/candidate.pem`. From **inside
   NPM**, check the real handshake before installing it. For the modem use:

   ```sh
   openssl s_client -brief -connect 192.168.100.1:443 -servername 0000BAE2ED44 \
     -verify_hostname 0000BAE2ED44 -verify_return_error -no-CApath -no-CAstore \
     -CAfile /data/device-admin/candidate.pem </dev/null
   ```

   For ASUS use `192.168.50.1:8443` and `router.asus.com` for both name flags.
   Require a zero exit with `Verification: OK`; changing just `-verify_hostname`
   to `wrong.invalid` must fail. NPM's OpenSSL 3.5 matches the ARRIS device CN
   because it has no DNS SAN. A verifier that rejects CN fallback must stay
   closed; trusting the root alone is not a substitute for the name check.
4. Back up the old public CA, atomically replace the corresponding PEM,
   then run `docker exec nginxproxymanager nginx -t` and reload NPM's nginx.
   Recheck the login page and its assets after SSO. Do not automate login:
   repeated failures lock the device account, and ASUS allows one admin
   session at a time.

From an external network, anonymous GETs to `/`, each login page and a JS
asset must return a redirect to `https://authelia.danteb.com/` without a
device upstream status in NPM's access log. For routing problems, check
`ip route get 192.168.100.1` on calcifer: it should go via `192.168.50.1`
on `bond0`, not a Docker bridge. The shared `compose_authelia` bridge is
pinned to `10.253.240.32/28` in the main Compose index. Global Docker
address pools were not changed (that would require a wider maintenance
window), so check the modem route when adding another bridge. A matching
local Compose override keeps the live pin across updates until that index is
deployed. Once both render the same subnet, the temporary `docker-compose.override.yml` containing
only that pin can be removed without recreating the network.
