#!/usr/bin/env python3
"""home_scout_score.py — apply hard filters and weighted scoring to recent listings.

Reads home_scout_listings rows seen within --since window, applies hard filters
from HOME.md, computes tier 1-5, emits one JSON line per non-rejected listing
to stdout (sorted by score descending). Also updates score/tier/rejected_reason
back into the DB.

Usage:
    python3 home_scout_score.py [--since=2d] [--all]

--since: look-back window matching the fetch window (default: 2d)
--all: score all rows that have no tier yet (regardless of last_seen_at)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass

# Import the math module from the same scripts directory.
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)
from home_scout_math import PropertyInputs, estimate_piti  # noqa: E402

DB_PATH = "/var/lib/openclaw/state.db"
SKILL_DIR = os.path.expanduser(
    "~/.openclaw/workspace/skills/home-scout"
)


# ---------------------------------------------------------------------------
# Minimal YAML parsers (stdlib only — no PyYAML on this pi)
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    """Parse flat key: scalar YAML (no nesting, no sequences)."""
    cfg: dict = {}
    with open(path) as f:
        for raw in f:
            line = raw.split("#")[0].strip()
            if not line or ":" not in line:
                continue
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if not k:
                continue
            if v.lower() in ("true", "yes"):
                cfg[k] = True
            elif v.lower() in ("false", "no"):
                cfg[k] = False
            else:
                try:
                    cfg[k] = int(v)
                except ValueError:
                    try:
                        cfg[k] = float(v)
                    except ValueError:
                        cfg[k] = v
    return cfg


def load_neighborhoods(path: str) -> tuple[dict[str, list[str]], str]:
    """Parse the flat-list neighborhoods.yaml.

    Returns (tier_aliases, unknown_tier) where tier_aliases maps
    tier letter → [lowercase alias, ...].
    """
    tiers: dict[str, list[str]] = {}
    unknown_tier = "C"
    current_tier: str | None = None

    with open(path) as f:
        for raw in f:
            line = raw.split("#")[0].rstrip()
            stripped = line.lstrip()
            if not stripped:
                continue
            if ":" in stripped and not stripped.startswith("-"):
                k, _, v = stripped.partition(":")
                k, v = k.strip(), v.strip()
                if k == "unknown_tier":
                    unknown_tier = v.strip()
                elif k in ("A", "B", "C", "D", "X"):
                    current_tier = k
                    tiers.setdefault(k, [])
            elif stripped.startswith("- ") and current_tier is not None:
                alias = stripped[2:].strip().lower()
                if alias:
                    tiers[current_tier].append(alias)

    return tiers, unknown_tier


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

TIER_SCORES: dict[str, float] = {
    "A": 1.00, "B": 0.75, "C": 0.50, "D": 0.25, "X": 0.00
}

# MVP weights (school zone 20% redistributed proportionally among the others)
WEIGHTS = {
    "nbhd": 0.375,   # 30/80
    "year": 0.250,   # 20/80
    "psf":  0.1875,  # 15/80
    "lot":  0.0625,  # 5/80
    "dom":  0.0625,  # 5/80
    "beds": 0.0625,  # 5/80
}


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _lookup_neighborhood(subdivision: str | None,
                         tier_aliases: dict[str, list[str]],
                         unknown_tier: str) -> tuple[float, str]:
    """Return (score, tier_letter) for a subdivision name."""
    if not subdivision:
        t = unknown_tier
        return TIER_SCORES.get(t, 0.5), t
    sub_lower = subdivision.lower()
    for tier_letter in ("A", "B", "C", "D", "X"):
        for alias in tier_aliases.get(tier_letter, []):
            if alias in sub_lower:
                return TIER_SCORES[tier_letter], tier_letter
    t = unknown_tier
    return TIER_SCORES.get(t, 0.5), t


def _year_score(year_built: int | None) -> float:
    if year_built is None:
        return 0.5
    if year_built >= 2000:
        return 1.0
    if year_built >= 1985:
        # Linear: 1985 → 0.0, 2000 → 1.0
        return (year_built - 1985) / 15.0
    return 0.0


def _dom_score(dom: int | None) -> float:
    if dom is None:
        return 0.5
    return _clamp01(1.0 - dom / 14.0)


def _lot_score(lot_sqft: int | None) -> float:
    if lot_sqft is None:
        return 0.5
    target_sqft = 0.20 * 43_560  # 0.20 acres
    return _clamp01(lot_sqft / target_sqft)


def _bed_score(beds: int | None) -> float:
    if beds is None:
        return 0.5
    return _clamp01(beds / 4.0)


def _psf_score(list_price: int | None, sqft: int | None, median_psf: float) -> float:
    if not list_price or not sqft or sqft == 0:
        return 0.5
    psf = list_price / sqft
    # score = 1 at psf == 0; score = 0 at psf == 2*median
    return _clamp01((2 * median_psf - psf) / median_psf)


def _score_to_tier(score: float) -> int:
    if score >= 0.85:
        return 1
    if score >= 0.70:
        return 2
    if score >= 0.55:
        return 3
    if score >= 0.40:
        return 4
    return 5


# ---------------------------------------------------------------------------
# Per-listing processing
# ---------------------------------------------------------------------------

_LISTING_COLS = (
    "zillow_id", "url", "address", "subdivision", "zip",
    "list_price", "last_price", "price_changed_at",
    "sqft", "lot_sqft", "beds", "baths", "year_built",
    "hoa_monthly", "days_on_market", "listing_status",
)


def process_listing(row: tuple, cfg: dict,
                    tier_aliases: dict[str, list[str]],
                    unknown_tier: str) -> dict:
    """Score one listing row. Returns a dict with all fields.

    Sets 'rejected_reason' if a hard filter fires; 'tier' and 'score' otherwise.
    """
    d = dict(zip(_LISTING_COLS, row))

    # --- Hard filters ---
    lp = d["list_price"]
    yb = d["year_built"]
    hoa = d["hoa_monthly"]
    dom = d["days_on_market"]

    if lp and lp > 1_100_000:
        return {**d, "rejected_reason": "over_budget", "tier": 5, "score": 0.0}

    if yb and yb < 1985:
        lot_acres = (d["lot_sqft"] / 43_560) if d["lot_sqft"] else 0.0
        if not (lot_acres >= 0.25 and lp and lp <= 750_000):
            return {**d, "rejected_reason": "pre_1985", "tier": 5, "score": 0.0}

    if hoa and hoa > 400:
        return {**d, "rejected_reason": "high_hoa", "tier": 5, "score": 0.0}

    if dom and dom > 60 and not d["price_changed_at"]:
        return {**d, "rejected_reason": "stale", "tier": 5, "score": 0.0}

    # --- Neighborhood lookup ---
    nbhd_score, tier_letter = _lookup_neighborhood(
        d["subdivision"], tier_aliases, unknown_tier
    )
    if tier_letter == "X":
        return {**d, "rejected_reason": "non_residential", "tier": 5, "score": 0.0}

    # --- Soft sub-scores ---
    year_sc = _year_score(yb)
    psf_sc = _psf_score(lp, d["sqft"], cfg.get("neighborhood_median_psf", 340))
    lot_sc = _lot_score(d["lot_sqft"])
    dom_sc = _dom_score(dom)
    bed_sc = _bed_score(d["beds"])

    score = (
        WEIGHTS["nbhd"] * nbhd_score
        + WEIGHTS["year"] * year_sc
        + WEIGHTS["psf"]  * psf_sc
        + WEIGHTS["lot"]  * lot_sc
        + WEIGHTS["dom"]  * dom_sc
        + WEIGHTS["beds"] * bed_sc
    )

    tier = _score_to_tier(score)

    # --- Housing math ---
    math_kwargs = {
        k: cfg[k] for k in (
            "down_pct", "rate_apr", "term_years", "pmi_annual_rate",
            "closing_costs_pct", "origination_fee",
            "tax_rate_non_school", "tax_rate_school",
            "homestead_flag", "school_homestead_exemption",
            "insurance_annual", "maint_reserve_pct",
            "lawn_monthly", "pest_monthly",
            "inspections", "appraisal", "moving", "initial_repairs", "furniture",
        )
        if k in cfg
    }
    math_inp = PropertyInputs(
        offer_price=float(lp or 0),
        hoa_monthly=float(hoa or 0),
        **math_kwargs,
    )
    math_out = estimate_piti(math_inp)

    psf = round((lp / d["sqft"]), 0) if (lp and d["sqft"]) else None
    lot_acres = round(d["lot_sqft"] / 43_560, 3) if d["lot_sqft"] else None

    return {
        **d,
        "rejected_reason": None,
        "tier": tier,
        "score": round(score, 3),
        "nbhd_tier": tier_letter,
        "psf": psf,
        "lot_acres": lot_acres,
        "reasons": {
            "nbhd_score": round(nbhd_score, 3),
            "year_score": round(year_sc, 3),
            "psf_score": round(psf_sc, 3),
            "lot_score": round(lot_sc, 3),
            "dom_score": round(dom_sc, 3),
            "bed_score": round(bed_sc, 3),
        },
        "piti_monthly": math_out["piti_monthly"],
        "cash_to_close": math_out["cash_to_close"],
        "piti_to_gross": round(math_out["piti_monthly"] / max(1, cfg.get("gross_monthly", 28248)), 3),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", default="2d",
                    help="look-back window matching the fetch window (default: 2d)")
    ap.add_argument("--all", action="store_true",
                    help="score all rows without a tier, regardless of last_seen_at")
    args = ap.parse_args()

    config_path = os.path.join(SKILL_DIR, "config.yaml")
    nbhd_path = os.path.join(SKILL_DIR, "neighborhoods.yaml")

    if not os.path.isfile(config_path):
        print(f"config.yaml not found at {config_path}", file=sys.stderr)
        return 1
    if not os.path.isfile(nbhd_path):
        print(f"neighborhoods.yaml not found at {nbhd_path}", file=sys.stderr)
        return 1

    cfg = load_config(config_path)
    tier_aliases, unknown_tier = load_neighborhoods(nbhd_path)

    conn = sqlite3.connect(DB_PATH)

    if args.all:
        where = "WHERE tier IS NULL"
        params: tuple = ()
    else:
        where = "WHERE last_seen_at >= datetime('now', ?)"
        params = (f"-{args.since.replace('d', ' days').replace('h', ' hours')}",)

    rows = conn.execute(
        f"SELECT {', '.join(_LISTING_COLS)} FROM home_scout_listings {where}",
        params,
    ).fetchall()

    if not rows:
        return 0

    results = [process_listing(r, cfg, tier_aliases, unknown_tier) for r in rows]

    # Persist score/tier/rejected_reason back to DB
    for res in results:
        conn.execute(
            "UPDATE home_scout_listings SET score = ?, tier = ?, rejected_reason = ? WHERE zillow_id = ?",
            (res["score"], res["tier"], res["rejected_reason"], res["zillow_id"]),
        )
    conn.commit()

    # Emit non-rejected listings sorted by score descending
    live = [r for r in results if not r["rejected_reason"]]
    live.sort(key=lambda r: r["score"], reverse=True)

    for r in live:
        # Clean up non-serialisable items
        out = {k: v for k, v in r.items() if v is not None or k in ("rejected_reason",)}
        print(json.dumps(out))

    # Stats to stderr for cron log
    rejected = [r for r in results if r["rejected_reason"]]
    print(
        f"home_scout_score: {len(live)} live, {len(rejected)} rejected "
        f"({', '.join(f\"{r['rejected_reason']}:{r['zillow_id']}\" for r in rejected[:5])})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
