# mcp-tcad Design Spec

**Date:** 2026-05-12  
**Status:** Approved  
**Context:** Part of the home-scout pipeline. Provides AI agents (home-scout cron, Open WebUI, Claude.ai) structured access to Travis County Appraisal District property data.

---

## Problem

The home-scout agent parses Zillow emails and stores listings in SQLite, but the emails contain only price, beds/baths/sqft, and address. Scoring requires `subdivision`, `year_built`, `lot_sqft`, and school district — none of which come from Zillow. TCAD's public portal (`travis.prodigycad.com`) has all of it but requires JavaScript rendering. This MCP exposes it as structured tools.

---

## API

**Backend:** `https://prod-container.trueprodigyapi.com` (TrueProdigy SaaS, public access)

**Auth flow (confirmed via HAR capture):**
```
POST /trueprodigy/cadpublic/auth/token
Body: {"office": "Travis"}
→ JWT, 5-minute TTL, no credentials required
```
The JWT is sent as a raw `Authorization: <token>` header (no `Bearer ` prefix).

**Key endpoints:**

| Endpoint | Method | Notes |
|----------|--------|-------|
| `/public/property/search?page=1&pageSize=N` | POST | Search by address or other filters |
| `/public/propertyaccount/{accountId}/general` | GET | Legal desc, zoning, owner, exemptions |
| `/public/propertyaccount/{accountId}/value` | GET | Current year values |
| `/public/propertyaccount/{accountId}/valuehistory` | GET | Multi-year value history |
| `/public/propertyaccount/{accountId}/land` | GET | Lot size, land value |
| `/public/propertyaccount/{accountId}/improvement` | GET | Year built, living area, components |
| `/public/propertyaccount/improvement/{imprvId}/features` | GET | Foundation, roof, materials |
| `/public/propertyaccount/{accountId}/taxable` | GET | Per-taxing-unit breakdown (school district here) |
| `/public/propertyaccount/{accountId}/appeal` | GET | Protest/appeal status |
| `/public/property/{pid}/deeds` | GET | Full deed/sale history |

**Two IDs returned by search (both needed):**
- `pid` — stable property ID (used for deed history URL)
- `pAccountID` — year-specific account ID (rotates annually; use the one from the current-year search result for all other detail calls)

**Search body format:**
```json
{
  "pYear": {"operator": "=", "value": "2026"},
  "streetPrimary": {"operator": "mlike", "value": "11301 MAIDENSTONE"}
}
```
Use `str(datetime.now().year)` for pYear (the API expects a string). The `mlike` operator does partial matching. Per TCAD's search tips, strip street suffixes (Dr/St/Ln/Ave/Rd/Cv/Blvd/Ct/Trl/Way/Pl) and city/state/zip before querying.

---

## Tool Set

### `search_property(address: str, limit: int = 5) → list[dict]`

Normalizes the input address (strips suffix words, strips city/state/zip, uppercases), then calls the search endpoint. Returns a list of matching properties, each with:
- `pid`, `account_id` (pAccountID)
- `subdivision` — parsed from `legalDescription` (strip `LOT N BLK X` prefix, strip `SEC N`/`UNIT N`/`PH N` suffix, title-case)
- `lot_sqft` — `legalAcreage × 43560`, rounded to int
- `zip`, `latitude`, `longitude`
- `appraised_value`, `market_value`, `land_value`, `improvement_value`
- `zoning`
- `legal_description` (raw, for debugging)
- `full_address` (from `fullSitus`)

### `get_property_general(account_id: int) → dict`

Returns the `/general` endpoint response, restructured:
- `pid`, `account_id`, `assessment_year`
- `legal_description`, `zoning`, `market_area`, `state_code`
- `owner_name`, `owner_secondary`, `owner_pct`, `owner_mailing_address`
- `situs_address` (the property street address)
- `exemptions` (e.g. "HS - Homestead")
- `property_status`, `protest_status`
- `tax_agent`, `tax_agent_status`
- `deferral_type`, `has_deferral`

### `get_property_values(account_id: int) → dict`

Calls both `/value` and `/valuehistory` in parallel, returns:
- `current` — land_value, improvement_value, market_value, appraised_value for current year
- `history` — list of `{year, land_value, improvement_value, market_value, appraised_value}` sorted ascending

### `get_property_land(account_id: int) → dict`

Returns `/land` response:
- `size_sqft`, `size_acres`, `cost_per_sqft`, `market_value`

### `get_property_improvements(account_id: int) → dict`

Calls `/improvement`, then calls `/improvement/{imprvId}/features` for each improvement in parallel (`asyncio.gather`). Typically one improvement per residential property, so usually two HTTP calls total. Returns:
- `year_built` — `min(actualYearBuilt)` across all detail items (earliest component = construction year)
- `living_area_sqft` — from `livingArea`
- `gross_building_area_sqft` — from `grossBuildingArea`
- `improvement_value`
- `description` (e.g. "1 FAM DWELLING")
- `components` — list of detail items: `{type_description, area_sqft, year_built, features: [...]}`

### `get_property_taxing_units(account_id: int) → dict`

Returns `/taxable` response as a list of taxing units, each with:
- `name`, `code`
- `tax_rate`, `taxable_value`, `net_appraised_value`
- `estimated_taxes`, `estimated_taxes_without_exemptions`

**Note:** School district is identified here by name (e.g. "ROUND ROCK ISD" or "AUSTIN ISD"). This is the canonical source for RRISD vs AISD determination for home-scout scoring — no separate school district lookup needed.

### `get_protest_information(account_id: int) → dict`

Returns `/appeal` response:
- `appeal_id`, `appeal_type`, `appeal_status`
- `informal_date`, `docket_date`
- `claimant_opinion_of_value`, `initial_market_value`, `final_market_value`
- `board_determination`

### `get_property_deed_history(pid: int) → list[dict]`

Returns `/property/{pid}/deeds` as a list of deeds:
- `deed_type`, `deed_description`
- `deed_date`, `seller`, `buyer`
- `instrument_num`, `volume`, `page`

---

## Token Caching

```python
_token_cache: tuple[str, float] = ("", 0.0)  # (token, expires_at)

async def _get_token() -> str:
    global _token_cache
    token, expires_at = _token_cache
    if time.time() < expires_at - 30:   # 30s margin
        return token
    # POST /trueprodigy/cadpublic/auth/token {"office":"Travis"}
    # update _token_cache, return new token
```

No locking needed — asyncio is single-threaded; concurrent tool calls racing on an expired token will both fetch a new one and the second will simply overwrite with an equally valid token.

---

## Address Normalization

Suffix words stripped before the search query (case-insensitive):
`Dr, Drive, St, Street, Ln, Lane, Ave, Avenue, Rd, Road, Cv, Cove, Blvd, Boulevard, Ct, Court, Trl, Trail, Way, Pl, Place, Pkwy, Parkway, Hwy, Highway, Cir, Circle, Loop`

Everything from the first comma onward (city/state/zip) is stripped. Result is uppercased.

Examples:
- `"11301 Maidenstone Dr, Austin, TX"` → `"11301 MAIDENSTONE"`
- `"4202 Oak Creek Dr"` → `"4202 OAK CREEK"`

---

## Files

```
docker/dockerfiles/mcp-tcad/
    Dockerfile        # same base as mcp-nominatim (python:3.14-slim, uvicorn on :8080)
    app.py            # ~200 lines
    requirements.txt  # fastmcp==3.2.4, httpx==0.28.1
docker/compose.mcp.yml     # add mcp-tcad service + MCP_TOKEN_TCAD secret
```

Service config in `compose.mcp.yml` follows the exact pattern of `mcp-nominatim`:
- Networks: `proxy` + (no geo network needed — TCAD is external HTTPS)
- Secret: `MCP_TOKEN_TCAD` from `${DATA}/mcp/secrets/MCP_TOKEN_TCAD`
- Environment: `AUTH_TOKEN_FILE: /run/secrets/MCP_TOKEN_TCAD`
- Healthcheck: TCP connect to port 8080
- NPM proxy host: `mcp-tcad.danteb.com`

---

## Consumers

All three use the same HTTPS endpoint (`https://mcp-tcad.danteb.com`) and the same `MCP_TOKEN_TCAD` bearer token:

1. **home-scout enrichment script** (`home_scout_enrich.py`, future) — calls `search_property` + `get_property_improvements` + `get_property_taxing_units` per listing to populate `subdivision`, `year_built`, `lot_sqft`, and school district in `home_scout_listings`
2. **Open WebUI** — Tools → add MCP server → URL + Bearer token
3. **Claude.ai** — Settings → Integrations → remote MCP server → URL + Bearer token

---

## Out of Scope

- Caching TCAD responses at the MCP layer (handled by the enrichment script writing to SQLite)
- Commercial/multi-owner properties (this is designed for residential 78759 ZIP)
- The `home_scout_enrich.py` script itself (separate task)
- Adding `school_district` column to `home_scout_listings` schema (part of the enrich script task)
