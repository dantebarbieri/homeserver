# mcp-tcad Design Spec

**Date:** 2026-05-12  
**Status:** Approved  
**Context:** Part of the home-scout pipeline. Provides AI agents (home-scout cron, Open WebUI, Claude.ai) structured access to Travis County Appraisal District property data.

---

## Problem

The home-scout agent parses Zillow emails and stores listings in SQLite, but the emails contain only price, beds/baths/sqft, and address. Scoring requires `subdivision`, `year_built`, `lot_sqft`, and school district (RRISD vs AISD) — none of which come from Zillow. TCAD's public portal (`travis.prodigycad.com`) has all of it but requires JavaScript rendering. This MCP exposes it as structured tools.

---

## API

**Backend:** `https://prod-container.trueprodigyapi.com` (TrueProdigy SaaS, public access)

### Auth flow (confirmed via HAR capture)

```
POST /trueprodigy/cadpublic/auth/token
Body: {"office": "Travis"}
→ HTTP 201, body shape: {"user": {"token": "<JWT>"}}
```

The JWT lives at `response_json["user"]["token"]` (not `response_json["token"]`), has a 5-minute TTL (`exp - iat = 300`), and is sent on subsequent calls as a raw `Authorization: <token>` header (no `Bearer ` prefix). No credentials are required to mint a token.

A handful of endpoints under `/public/config/*` (`defaultyear`, `currentyear`, `publicsite`, `propertysearch`) **do not require auth** — useful for the year-resolution helper described below.

### Response shape (every endpoint)

Every TCAD endpoint wraps its payload in a `results` envelope:

| Endpoint family | Wrapper shape |
|---|---|
| `/public/property/search?page=...` | `{"totalProperty": {"propertyCount": N}, "results": [...]}` |
| `/public/property/search` (no paging) | same as above; **a `pid`-only filter returns one row per historical year** |
| `/public/propertyaccount/{id}/{general,value,valuehistory,land,improvement,appeal}` | `{"results": [{...}]}` (one element per row) |
| `/public/propertyaccount/improvement/{id}/features` | `{"results": [{pDetailID, imprvDetailType, features: [...]}, ...]}` |
| `/public/propertyaccount/{id}/taxable` | `{"results": {"taxingUnits": [...], "estimatedTaxes": "...", "estimatedTaxesWoutExemptions": "...", "totalTaxRate": "..."}}` *(object, not list)* |
| `/public/property/{pid}/deeds` | `{"results": [...]}` (mixed order — sort ascending by `deedDt` in the tool) |
| `/public/config/{defaultyear,currentyear}` | `{"results": {"year": 2026}}` |

### Year resolution

The frontend pins each search to a specific `pYear`. Rather than `str(datetime.now().year)` (which can be wrong by up to a quarter when TCAD rolls the appraisal year), the MCP fetches `GET /public/config/defaultyear` (no auth) and caches `body.results.year` for 24 hours. If the call fails, it falls back to `datetime.now().year` and continues — degraded but functional.

### Key endpoints

| Endpoint | Method | Notes |
|----------|--------|-------|
| `/public/property/search?page=1&pageSize=N` | POST | Search by address or other filters; returns one row per match for the queried year |
| `/public/property/search` *(no query string)* | POST | Same shape; with body `{"pid":{"operator":"=","value":"<pid>"}}` returns all historical-year rows for that pid (15 rows for our test parcel: 2012–2026) |
| `/public/propertyaccount/{accountId}/general` | GET | Legal desc, zoning, owner, exemptions |
| `/public/propertyaccount/{accountId}/value` | GET | Current-year values (one row) |
| `/public/propertyaccount/{accountId}/valuehistory` | GET | **Last 5 years only** — 2022–2026 as of this writing |
| `/public/propertyaccount/{accountId}/land` | GET | Lot size, land value |
| `/public/propertyaccount/{accountId}/improvement` | GET | Year built, living area, components |
| `/public/propertyaccount/improvement/{imprvId}/features` | GET | Foundation, roof, materials — **only floor-type details (1ST/2ND) carry features**; other detail items return empty |
| `/public/propertyaccount/{accountId}/taxable` | GET | Per-taxing-unit breakdown plus aggregate totals (school district here) |
| `/public/propertyaccount/{accountId}/appeal` | GET | Protest/appeal status |
| `/public/property/{pid}/deeds` | GET | Full deed/sale history |

### Two IDs returned by search (both needed)

- `pid` — stable property ID (used for deed history URL and the historical-year search trick)
- `pAccountID` — year-specific account ID (rotates annually; use the one from the current-year search result for all other detail calls). For our test parcel `pid=164007` the `pAccountID` was `51339` in 2012 and `9221886` in 2026.

### Search body format and fallback ladder

```json
{
  "pYear": {"operator": "=", "value": "2026"},
  "streetPrimary": {"operator": "mlike", "value": "11301 MAIDENSTONE"}
}
```

`streetPrimary` is a multi-column `mlike` that searches `streetNum`, `streetName`, `streetPrefix`, `streetSuffix` together (per `/public/config/propertysearch`). The `mlike` operator is a case-insensitive substring/LIKE match, so `"11301 MAIDENSTONE"` already matches the row whose `streetPrimary` is `"11301 MAIDENSTONE DR"` without needing the suffix.

Per TCAD's "Tips for a Faster Search":

1. Don't include street suffixes (`Dr`, `St`, `Ln`, `Ave`, `Rd`, `Cv`, etc.) in the query.
2. If no results are returned, broaden the search by entering fewer words.
3. If the street number is unknown, search by street name only.

The MCP performs this as a deterministic ladder, stopping at the first attempt that returns ≥1 result (cap = 4 attempts):

| # | Strategy | Query (`streetPrimary mlike ...`) | When it runs |
|---|---|---|---|
| 1 | `exact` | `"<num> <street tokens, suffix stripped>"` | Always |
| 2 | `broadened-1` | `"<num> <street tokens minus last>"` | Step 1 returned 0 **and** street has ≥2 tokens after the number |
| 3 | `broadened-2` | `"<num> <first street token>"` | Step 2 returned 0 **and** street has ≥3 tokens after the number |
| 4 | `street-only` | `"<full street tokens>"` (drop the number) | Step 3 (or step 2 / step 1 if earlier steps were skipped) returned 0 |

`pYear` is pinned to the resolved default year on every attempt. The tool returns an envelope wrapping the chosen attempt:

```python
{
  "strategy": "exact" | "broadened-1" | "broadened-2" | "street-only" | "none",
  "query_used": "<the literal mlike value sent>",
  "totalProperty": <int from totalProperty.propertyCount>,
  "results": [...],   # may be truncated to `limit`
}
```

This lets the caller distinguish a canonical exact hit from a broadened guess. For the home-scout enrichment flow, anything other than `exact` should trigger human confirmation before writing back to `home_scout_listings`.

---

## Tool Set

### `search_property(address: str, limit: int = 5) → dict`

Normalises the input address (strips suffix words, strips everything from the first comma onward, uppercases for log readability), then runs the fallback ladder above. Returns the `{strategy, query_used, totalProperty, results}` envelope. Each entry in `results` is built from the (rich, ~90-field) search payload:

| Field | Source (API field on search result) |
|---|---|
| `pid` | `pid` |
| `account_id` | `pAccountID` |
| `subdivision` | parsed from `legalDescription` (strip `LOT N BLK X` prefix, strip `SEC N` / `UNIT N` / `PH N` suffix, title-case) |
| `lot_sqft` | `round(float(legalAcreage) * 43560)` |
| `lot`, `block`, `tract` | `lot`, `block`, `tract` (free in payload — saves a `/general` round-trip when the caller wants the legal-description components separately) |
| `geo_id`, `map_id`, `tax_office_ref`, `market_area` | `geoID`, `mapID`, `taxOfficeRef`, `marketArea` |
| `zip`, `latitude`, `longitude` | `zip`, `latitude`, `longitude` |
| `appraised_value`, `market_value`, `land_value`, `improvement_value` | `appraisedValue`, `marketValue`, `landValue`, `improvementValue` (search payload uses the short names; `/value` uses `owner*` prefixes — see `get_property_values`) |
| `zoning` | `zoning` |
| `legal_description` | `legalDescription` (raw, for debugging) |
| `full_address` | `fullSitus` |
| `street_components` | `{num, prefix, name, suffix, secondary}` from `streetNum` / `streetPrefix` / `streetName` / `streetSuffix` / `streetSecondary` |
| `owner_name` | `displayName` |
| `owner_mailing_address` | assembled from `addrDeliveryLine` + optional `addrUnitDesignator` + `addrCity` + `addrState` + `addrZip` (single-spaced) |
| `last_deed_date` | `deedDt` (ISO date, not datetime) |
| `has_arb_hearing` | `arbHearing == "Yes"` |

### `get_property_general(account_id: int) → dict`

Calls `/general`, returns one row remapped to spec field names:

| Spec field | API field |
|---|---|
| `pid`, `account_id`, `assessment_year` | `pID`, `pAccountID`, `pYear` |
| `legal_description`, `zoning`, `market_area`, `market_area_description` | `legalDescription`, `zoning`, `marketArea`, `marketAreaDescription` |
| `state_codes` | `stateCodes` (raw string — TCAD delimits with comma when more than one) |
| `use_code`, `use_code_description` | `useCd`, `useCodeDescription` |
| `owner_name`, `owner_secondary`, `owner_pct` | `name`, `nameSecondary`, `ownerPct` |
| `owner_mailing_address` | `address` (collapse runs of whitespace — TCAD's stored value contains double-spaces, e.g. `"11301 MAIDENSTONE DR  AUSTIN TX  78759-4429"`) |
| `situs_address` | `situsAddr` |
| `street_address_short` | `streetAddress` (TCAD's own suffix-stripped form, e.g. `"11301 MAIDENSTONE"`) |
| `exemptions` | `exemptionList` |
| `property_status`, `protest_status` | `propertyStatus`, `protestStatus` (often empty string) |
| `informal_date`, `formal_date` | `informalDt`, `formatlDate` *(yes — typo in upstream API)* |
| `tax_agent`, `tax_agent_status` | `agent`, `agentStatus` *(not `taxAgent`/`taxAgentStatus`)* |
| `deferral_type`, `has_deferral` | `deferralType`, `hasDeferral` |
| `audit_year` | `hsAuditYear` |

### `get_property_values(account_id: int) → dict`

Calls `/value` and `/valuehistory` in parallel. `/value` and `/valuehistory` share the same `owner*`-prefixed field names — the spec strips the prefix in the output:

```
current = {
    "land_value":           int(ownerLandValue),
    "improvement_value":    int(ownerImprovementValue),
    "market_value":         int(ownerMarketValue),
    "appraised_value":      int(ownerAppraisedValue),
    "net_appraised_value":  int(ownerNetAppraisedValue),
    "tax_limitation_value": int(ownerTaxLimitationValue),
}
history = [
    {"year": int(pYear), "land_value": ..., "improvement_value": ..., "market_value": ..., "appraised_value": ...}
    for row in valuehistory_results
]  # sorted ascending by year
```

**`/valuehistory` is documented by TCAD as a 5-year rolling window** (returned 2022–2026 in the HAR). For full history, use `get_full_value_history` below.

### `get_full_value_history(pid: int) → list[dict]`

Uses the pid-only search trick — `POST /public/property/search` (no query string) with body:

```json
{ "pid": {"operator": "=", "value": "<pid>"} }
```

— which returns one row per historical year for that pid (15 rows for our test parcel: 2012–2026, each with its own `pAccountID`). This is cheaper than calling `/valuehistory` per year and covers years pre-dating the 5-year window. Returns:

```python
[
  {"year": int(pYear), "account_id": pAccountID, "land_value": ..., "improvement_value": ..., "market_value": ..., "appraised_value": ...},
  ...
]  # sorted ascending by year
```

### `get_property_land(account_id: int) → dict`

Calls `/land`. Field renames:

| Spec field | API field |
|---|---|
| `size_sqft` | `sizeSqft` (cast to int) |
| `size_acres` | `sizeAcres` |
| `cost_per_sqft` | `costPerSqft` |
| `market_value` | `mktValue` *(note rename in source — not `marketValue`)* (cast to int) |
| `land_type`, `land_description` | `landType`, `landDescription` |

### `get_property_improvements(account_id: int) → dict`

Calls `/improvement`, then for each `pImprovementID` calls `/improvement/{id}/features` in parallel via `asyncio.gather`. Typically one improvement per residential property, so usually two HTTP calls total. Returns:

| Spec field | Source / rule |
|---|---|
| `year_built` | `min(actualYearBuilt for d in details if d.imprvDetailType in {"1ST","2ND"})`, falling back to `min(actualYearBuilt for all details)` if no floor-type entries exist. (Restricting to floor types avoids accessory components like decks or HVAC retrofits skewing the construction year.) |
| `living_area_sqft` | `livingArea` |
| `gross_building_area_sqft` | `grossBuildingArea` |
| `improvement_value` | `improvementValue` (int) |
| `description` | `imprvDescription` (e.g. `"1 FAM DWELLING"`) |
| `description_specific` | `imprvSpecificDescription` |
| `state_code` | `stateCd` |
| `components` | one entry per detail row (see below) |

Each entry in `components`:

```python
{
  "detail_id":           pDetailID,
  "type_code":           imprvDetailType,           # e.g. "1ST", "522", "095"
  "type_description":    detailTypeDescription,     # e.g. "1st Floor", "FIREPLACE"
  "class":               class_,                    # e.g. "R5"
  "area_sqft":           float(area),               # area can be a fractional value (e.g. "2.50" for BATHROOM)
  "year_built":          int(actualYearBuilt),
  "effective_year_built": int(effYearBuilt),
  "features":            {"foundation": "SLAB", "roof_style": "GABLE", ...},  # see below; empty dict for most non-floor items
  "features_raw":        ["Foundation: SLAB", "Roof Style: GABLE", ...],       # original strings for transparency
}
```

The `/improvement/{id}/features` endpoint returns a list of free-text strings, not key/value objects:

```json
{"results": [
  {"pDetailID": 66381416, "imprvDetailType": "1ST",
   "features": ["Foundation: SLAB", "Roof Style: GABLE", "Floor Factor: 1ST", "Roof Covering: COMPOSITION SHINGLE", "Shape Factor: U"]},
  ...
]}
```

Parsing rule: split each string on the **first** `": "`, snake_case the key (`"Roof Covering"` → `"roof_covering"`), keep the value verbatim. Only floor-type details (`1ST`, `2ND`, etc.) carry features in the HAR sample — the other ten detail items (HVAC, FIREPLACE, GARAGE, BATHROOM, etc.) returned no feature attachments. Components without a corresponding entry in the features response get `features = {}` and `features_raw = []`.

### `get_property_taxing_units(account_id: int) → dict`

**Reshaped from the original spec — `/taxable` returns an object with both per-unit rows and aggregate totals, not a bare list.** Returns:

```python
{
  "units": [
    {
      "name":                                taxingUnitName,
      "code":                                taxingUnitCode,
      "tax_rate":                            float(totalTaxRate),
      "taxable_value":                       int(taxableValue),
      "net_appraised_value":                 int(netAppraisedValue),
      "estimated_taxes":                     float(estimatedTaxes),
      "estimated_taxes_without_exemptions":  float(estimatedTaxesWoutExemptions),
      "arb_status":                          arbStatus,
    },
    ...
  ],
  "total_tax_rate":                       float(totalTaxRate),                       # at object root, not per unit
  "total_estimated_taxes":                float(estimatedTaxes),                     # ditto
  "total_estimated_taxes_without_exemptions": float(estimatedTaxesWoutExemptions),   # ditto
  "school_district":                      "ROUND ROCK ISD",  # or null — see below
}
```

`school_district` is a convenience derived field: the `taxingUnitName` of the unit whose name matches the regex `r"\bISD\b"` (case-insensitive). Returns `null` if no ISD unit is present. This is the canonical RRISD-vs-AISD answer for home-scout scoring — saves the caller a regex over `units[]`.

### `get_protest_information(account_id: int) → dict`

Calls `/appeal`. Field renames:

| Spec field | API field |
|---|---|
| `appeal_id` | `appealID` |
| `appeal_type` | `appealType` |
| `appeal_status` | `appealStatus` |
| `informal_date` | `informalDt` |
| `docket_date` | `docketDt` |
| `claimant_opinion_of_value` | `claimantOpinionOfValue` |
| `initial_market_value` | `initialMarketValue` |
| `final_market_value` | `finalMarketValue` |
| `board_determination` | `boardDetermination` |
| `panel_members` | `panelMembers` (list, often empty) |

### `get_property_deed_history(pid: int) → list[dict]`

Calls `/property/{pid}/deeds` and returns a list, **sorted ascending by `deed_date`** (the API returns mixed order). Each entry:

| Spec field | API field |
|---|---|
| `deed_id` | `deedID` |
| `deed_type` | `deedType` |
| `deed_description` | `deedDescription` |
| `deed_date` | `deedDt` (ISO date) |
| `seller`, `buyer` | `seller`, `buyer` |
| `instrument_num` | `instrumentNum` |
| `volume`, `book`, `page` | `volume`, `book`, `page` *(book was missing from the original spec)* |

---

## Caching

Two cached values, both refreshed lazily:

```python
_token_cache: tuple[str, float] = ("", 0.0)        # (token, expires_at_unix_seconds)
_year_cache:  tuple[int, float] = (0, 0.0)         # (year, expires_at_unix_seconds)

async def _get_token() -> str:
    token, expires_at = _token_cache
    if time.time() < expires_at - 30:              # 30s safety margin
        return token
    # POST /trueprodigy/cadpublic/auth/token  body={"office":"Travis"}
    # parse response_json["user"]["token"]; decode JWT "exp" claim for expires_at
    # update _token_cache, return new token

async def _get_year() -> int:
    year, expires_at = _year_cache
    if time.time() < expires_at:                   # 24h TTL
        return year
    try:
        # GET /public/config/defaultyear  (no auth)
        # year = response_json["results"]["year"]
        # _year_cache = (year, time.time() + 86400)
    except Exception:
        return datetime.now().year                 # degraded fallback, do not cache
    return year
```

No locking needed for either cache — asyncio is single-threaded; concurrent tool calls racing on an expired entry will both fetch a new value and the second will simply overwrite with an equally valid one.

---

## Address Normalisation

Suffix words stripped before the search query (case-insensitive):
`Dr, Drive, St, Street, Ln, Lane, Ave, Avenue, Rd, Road, Cv, Cove, Blvd, Boulevard, Ct, Court, Trl, Trail, Way, Pl, Place, Pkwy, Parkway, Hwy, Highway, Cir, Circle, Loop`

Everything from the first comma onward (city/state/zip) is stripped. Internal whitespace is collapsed to single spaces. Result is uppercased — purely for log readability; TCAD's `mlike` operator is case-insensitive, so the uppercase step has no effect on matching.

Examples:
- `"11301 Maidenstone Dr, Austin, TX"` → `"11301 MAIDENSTONE"`
- `"4202 Oak Creek Dr"` → `"4202 OAK CREEK"`

The fallback ladder (see *Search body format and fallback ladder* above) operates on the result of this normalisation.

---

## Files

```
docker/dockerfiles/mcp-tcad/
    Dockerfile        # same base as mcp-nominatim (python:3.14-slim, uvicorn on :8080)
    app.py            # ~300 lines (was ~200 before fallback ladder, two caches, full-history tool, features parser)
    requirements.txt  # fastmcp==3.2.4, httpx==0.28.1
docker/compose.mcp.yml     # add mcp-tcad service + MCP_TOKEN_TCAD secret
```

Service config in `compose.mcp.yml` follows the exact pattern of `mcp-nominatim`:
- Networks: `proxy` only (no geo network needed — TCAD is external HTTPS)
- Secret: `MCP_TOKEN_TCAD` from `${DATA}/mcp/secrets/MCP_TOKEN_TCAD`
- Environment: `AUTH_TOKEN_FILE: /run/secrets/MCP_TOKEN_TCAD`
- Healthcheck: TCP connect to port 8080
- NPM proxy host: `mcp-tcad.danteb.com`

---

## Consumers

All three use the same HTTPS endpoint (`https://mcp-tcad.danteb.com`) and the same `MCP_TOKEN_TCAD` bearer token:

1. **home-scout enrichment script** (`home_scout_enrich.py`, future) — calls `search_property` + `get_property_improvements` + `get_property_taxing_units` per listing to populate `subdivision`, `year_built`, `lot_sqft`, and `school_district` in `home_scout_listings`. Treats any `strategy != "exact"` from `search_property` as a non-canonical match requiring human confirmation before writing back.
2. **Open WebUI** — Tools → add MCP server → URL + Bearer token
3. **Claude.ai** — Settings → Integrations → remote MCP server → URL + Bearer token

---

## Out of Scope

- Caching TCAD responses at the MCP layer (handled by the enrichment script writing to SQLite)
- Commercial / multi-owner properties (this is designed for residential 78759 ZIP)
- The `home_scout_enrich.py` script itself (separate task)
- Adding `school_district` column to `home_scout_listings` schema (part of the enrich script task)
- Coordinate lookup (`/gama/coordinatelookup`) and parcel shape geometry (`/gama/parcelshapes`, `/gama/tiles/...`) — the search payload already exposes `latitude`/`longitude`, which is sufficient for home-scout scoring
- The `shownoticelink` endpoint (used by TCAD's own UI to render a notice button)
- The `clientinformation` endpoint (TCAD branding metadata)
