# Public SearXNG hardening (runbook)

The public SearXNG instance at `searxng.danteb.com` lives in
`compose.searxng.yml` (container `searxng`) but its `settings.yml`,
`limiter.toml`, and any custom files live at `${DATA}/searxng/config/` on
the server — not in this repo (gitignored). This document is the
authoritative diff to apply to that on-server config.

Apply each change, then `dcr searxng` (or `docker compose restart searxng`).

## 1. `${DATA}/searxng/config/settings.yml`

Make sure the following keys are set as below — add or change in place,
do not delete adjacent keys:

```yaml
server:
  limiter: true
  public_instance: true
  image_proxy: true
  default_http_headers:
    X-Robots-Tag: noindex, nofollow
    Referrer-Policy: no-referrer
    X-Content-Type-Options: nosniff
    X-Download-Options: noopen

search:
  formats:
    - html        # JSON / CSV / RSS removed; HTML only for the public instance.
```

**Why:** SearXNG upstream warns that exposing the JSON format on a public
instance is the #1 abuse vector. Public instances must HTML-only.

## 2. `${DATA}/searxng/config/limiter.toml` (create if missing)

```toml
[real_ip]
x_for = 1                    # we sit behind one proxy hop (NPM)
ipv4_prefix = 32
ipv6_prefix = 56

[botdetection.ip_limit]
filter_link_local = true
link_token = false

[botdetection.ip_lists]
pass_searxng_org = false
pass_ip = [
  "172.16.0.0/12",           # Docker bridge networks
  "10.8.0.0/24",             # WireGuard
  "192.168.50.0/24",         # LAN
]
```

## 3. NPM proxy host for `searxng.danteb.com`

Custom Locations or Advanced tab — block AI-crawler User-Agents and
abuse-format query strings before they reach SearXNG:

```nginx
# Block known AI-scraper user agents
if ($http_user_agent ~* "(GPTBot|ClaudeBot|CCBot|Bytespider|PerplexityBot|anthropic-ai|ChatGPT-User|Amazonbot|Diffbot|cohere-ai|Scrapy|python-requests|Go-http-client|curl)") {
    return 403;
}

# Anyone trying to abuse JSON / CSV / RSS gets a hard reject
if ($arg_format ~ "^(json|csv|rss)$") {
    return 403;
}
```

## 4. fail2ban (optional)

If you've adopted fail2ban for NPM access logs, add a jail matching 403/429
bursts on the searxng host. Pattern:
`status=(403|429) host=searxng.danteb.com` → ban for 1h after 10 hits/5min.

## 5. **Do NOT** list this instance on `searx.space`

The public-instance list is heavily scraped in 2026; benefit is low,
abuse magnet is high.

---

After applying all five steps, verify:

```sh
# Should return 403 (blocked)
curl -i 'https://searxng.danteb.com/search?q=test&format=json'
curl -i -A 'GPTBot/1.0' 'https://searxng.danteb.com/'

# Should return 200 (HTML)
curl -i 'https://searxng.danteb.com/search?q=test'
```
