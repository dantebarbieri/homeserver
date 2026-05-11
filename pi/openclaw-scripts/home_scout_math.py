#!/usr/bin/env python3
"""home_scout_math.py — PITI / housing-math calculations.

Ported from Housing Math.xlsx (Property Inputs + PITI Calculation sheets).
Stdlib only — no numpy_financial. PMT and CUMIPMT implemented as closed-form
loops.

Usage as a module:
    from home_scout_math import PropertyInputs, estimate_piti

Usage as a script:
    python3 home_scout_math.py --selftest
    python3 home_scout_math.py --json inputs.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Core math
# ---------------------------------------------------------------------------

def pmt(rate_per_period: float, n_periods: int, principal: float) -> float:
    """Monthly mortgage payment. Equivalent to Excel PMT(rate, n, -principal)."""
    if rate_per_period == 0:
        return principal / n_periods
    return principal * rate_per_period / (1.0 - (1.0 + rate_per_period) ** -n_periods)


def cumulative_interest(rate_per_period: float, n_periods: int,
                        principal: float, start: int, end: int) -> float:
    """Total interest in amortisation periods [start, end] (1-indexed, inclusive).

    Equivalent to -CUMIPMT(rate, n, principal, start, end, 0).
    Used by the tax-strategy logic (not the PITI core); included here for
    completeness and future use.
    """
    r = rate_per_period
    payment = pmt(r, n_periods, principal)
    balance = principal
    total = 0.0
    for k in range(1, end + 1):
        interest_k = balance * r
        if k >= start:
            total += interest_k
        balance -= payment - interest_k
    return total


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------

@dataclass
class PropertyInputs:
    # House
    offer_price: float                          # Property Inputs B4
    seller_credit: float = 0.0                  # B5

    # Loan
    down_pct: float = 0.05                      # B15
    rate_apr: float = 0.064                     # B16
    term_years: int = 30                        # B17
    pmi_annual_rate: float = 0.004              # B18 (only if LTV > 80%)
    closing_costs_pct: float = 0.025            # B19
    origination_fee: float = 0.0               # B20

    # Taxes (Tax Rates sheet split — school rate gets homestead exemption applied)
    tax_rate_non_school: float = 0.01111231     # B2+B3+B4+B5: Travis+CentralHealth+ACC+CoA
    tax_rate_school: float = 0.008931           # B6: Round Rock ISD
    homestead_flag: int = 1                     # B25
    school_homestead_exemption: float = 140_000 # B26

    # Insurance
    insurance_annual: float = 5400.0            # B27

    # Ongoing monthly
    maint_reserve_pct: float = 0.012            # B38
    lawn_monthly: float = 80.0                  # B39
    pest_monthly: float = 40.0                  # B40
    hoa_monthly: float = 0.0                    # B41

    # One-time purchase costs
    inspections: float = 1500.0                 # B30
    appraisal: float = 650.0                    # B31
    moving: float = 1500.0                      # B33
    initial_repairs: float = 20_000.0           # B34
    furniture: float = 5000.0                   # B35


# ---------------------------------------------------------------------------
# PITI calculation
# ---------------------------------------------------------------------------

def estimate_piti(inp: PropertyInputs) -> dict:
    """Compute PITI, cash-to-close, and ongoing costs.

    Mirrors the PITI Calculation sheet of Housing Math.xlsx exactly.

    Returns a dict with all intermediate values so callers can display any
    component.
    """
    # Loan basics (PITI sheet B3-B6)
    loan = inp.offer_price * (1 - inp.down_pct)
    down = inp.offer_price * inp.down_pct
    ltv = 1.0 - inp.down_pct
    pmi_required = ltv > 0.80

    # P&I (B8)
    pi_monthly = pmt(inp.rate_apr / 12, inp.term_years * 12, loan)

    # Property tax (B9) — school portion gets homestead exemption
    av = inp.offer_price  # TCAD resets to offer price year 1 (B24 = B4)
    school_taxable = max(0.0, av - inp.homestead_flag * inp.school_homestead_exemption)
    tax_annual = av * inp.tax_rate_non_school + school_taxable * inp.tax_rate_school
    tax_monthly = tax_annual / 12

    # Insurance (B10)
    ins_monthly = inp.insurance_annual / 12

    # PMI (B11) — only if LTV > 80%
    pmi_monthly = (loan * inp.pmi_annual_rate / 12) if pmi_required else 0.0

    # Total PITI (B12)
    piti_monthly = pi_monthly + tax_monthly + ins_monthly + pmi_monthly

    # Ongoing (B14-B17)
    maint_monthly = inp.offer_price * inp.maint_reserve_pct / 12
    total_housing_monthly = (piti_monthly + maint_monthly
                             + inp.lawn_monthly + inp.pest_monthly + inp.hoa_monthly)

    # Cash to close (B20-B30)
    closing = inp.offer_price * inp.closing_costs_pct + inp.origination_fee
    escrow_setup = 3 * (tax_monthly + ins_monthly)   # B28: ~3 months
    lender_reserves = 2 * piti_monthly                # B29: 2 months PITI
    cash_to_close = (down + closing - inp.seller_credit
                     + inp.inspections + inp.appraisal + inp.moving
                     + inp.initial_repairs + inp.furniture
                     + escrow_setup + lender_reserves)

    return {
        "loan_balance": round(loan, 2),
        "down_payment": round(down, 2),
        "ltv": round(ltv, 4),
        "pmi_required": pmi_required,
        "pi_monthly": round(pi_monthly, 2),
        "pi_annual": round(pi_monthly * 12, 2),
        "tax_monthly": round(tax_monthly, 2),
        "tax_annual": round(tax_annual, 2),
        "insurance_monthly": round(ins_monthly, 2),
        "pmi_monthly": round(pmi_monthly, 2),
        "piti_monthly": round(piti_monthly, 2),
        "piti_annual": round(piti_monthly * 12, 2),
        "maintenance_monthly": round(maint_monthly, 2),
        "total_housing_monthly": round(total_housing_monthly, 2),
        "closing_costs": round(closing, 2),
        "cash_to_close": round(cash_to_close, 2),
    }


# ---------------------------------------------------------------------------
# Self-test (Maidenstone Dr canonical vector from Housing Math.xlsx)
# ---------------------------------------------------------------------------

def selftest() -> int:
    inp = PropertyInputs(offer_price=699_000, seller_credit=14_000)
    out = estimate_piti(inp)

    expectations = {
        "loan_balance":  664_050.00,
        "pi_monthly":      4_153.67,
        "piti_monthly":    5_888.35,
        "cash_to_close":  83_391.68,
    }

    failures = []
    for k, want in expectations.items():
        got = out[k]
        if abs(got - want) > 0.05:
            failures.append(f"  {k}: got {got:.2f}, want {want:.2f}")

    if failures:
        print("FAIL:", file=sys.stderr)
        for f in failures:
            print(f, file=sys.stderr)
        return 1

    print("home_scout_math selftest: OK")
    print(json.dumps(out, indent=2))
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true",
                    help="run canonical Maidenstone test vector and exit")
    ap.add_argument("--json", metavar="FILE",
                    help="JSON file with PropertyInputs fields; print result to stdout")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if args.json:
        with open(args.json) as f:
            data = json.load(f)
        out = estimate_piti(PropertyInputs(**data))
        json.dump(out, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
