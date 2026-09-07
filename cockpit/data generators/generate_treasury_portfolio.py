from pathlib import Path
import numpy as np
import pandas as pd


def generate_treasury_datasets(
    bank_history_path: str = "data/bank_history.csv",
    output_dir: str = "data",
    seed: int = 73,
    n_positions: int = 52,
):
    """
    Generate a synthetic EUR banking-book securities portfolio for a fictional
    European bank, plus deterministic market-risk scenarios and simplified
    interest-rate hedge options.

    The portfolio reconciles its book value to the securities balance implied
    by bank_history.csv:

        securities = total_assets - loans - hqla - 55,000

    Monetary values are EUR millions unless otherwise stated.
    """
    bank = pd.read_csv(bank_history_path, parse_dates=["date"]).sort_values("date")
    latest = bank.iloc[-1]
    as_of_date = pd.Timestamp(latest["date"])

    securities_total_m = float(
        latest["total_assets"] - latest["loans"] - latest["hqla"] - 55_000
    )

    rng = np.random.default_rng(seed)

    asset_classes = [
        "Sovereign",
        "Covered Bond",
        "Agency/Supranational",
        "Corporate Bond",
    ]
    asset_class_probs = [0.48, 0.20, 0.12, 0.20]

    countries = ["Netherlands", "Germany", "France", "Belgium", "Other EU"]
    country_probs = [0.28, 0.26, 0.22, 0.12, 0.12]

    issuers = {
        "Netherlands": {
            "Sovereign": ["Kingdom of the Netherlands"],
            "Covered Bond": ["NL Covered Bank A", "NL Covered Bank B"],
            "Agency/Supranational": ["BNG Bank", "NWB Bank"],
            "Corporate Bond": ["NL Utility A", "NL Telecom A", "NL Industrial A"],
        },
        "Germany": {
            "Sovereign": ["Federal Republic of Germany"],
            "Covered Bond": ["DE Pfandbrief Bank A", "DE Pfandbrief Bank B"],
            "Agency/Supranational": ["KfW", "NRW.Bank"],
            "Corporate Bond": ["DE Auto A", "DE Industrial A", "DE Utility A"],
        },
        "France": {
            "Sovereign": ["French Republic"],
            "Covered Bond": ["FR Covered Bank A", "FR Covered Bank B"],
            "Agency/Supranational": ["CADES", "SFIL"],
            "Corporate Bond": ["FR Energy A", "FR Telecom A", "FR Industrial A"],
        },
        "Belgium": {
            "Sovereign": ["Kingdom of Belgium"],
            "Covered Bond": ["BE Covered Bank A"],
            "Agency/Supranational": ["Flanders Funding Agency"],
            "Corporate Bond": ["BE Utility A", "BE Industrial A"],
        },
        "Other EU": {
            "Sovereign": ["Republic of Austria", "Republic of Finland", "Kingdom of Spain"],
            "Covered Bond": ["EU Covered Bank A", "EU Covered Bank B"],
            "Agency/Supranational": ["European Investment Bank", "European Union"],
            "Corporate Bond": ["EU Utility A", "EU Infrastructure A", "EU Consumer A"],
        },
    }

    rating_by_class = {
        "Sovereign": (["AAA", "AA+", "AA", "A+"], [0.42, 0.25, 0.25, 0.08]),
        "Covered Bond": (["AAA", "AA+"], [0.82, 0.18]),
        "Agency/Supranational": (["AAA", "AA+"], [0.88, 0.12]),
        "Corporate Bond": (["AA", "A", "BBB"], [0.18, 0.52, 0.30]),
    }

    spread_bps_by_rating = {
        "AAA": 28, "AA+": 38, "AA": 58, "A+": 78, "A": 95, "BBB": 145,
    }

    country_spread_bps = {
        "Germany": -8,
        "Netherlands": 0,
        "France": 28,
        "Belgium": 20,
        "Other EU": 18,
    }

    curve_tenors = np.array([0.5, 1, 2, 3, 5, 7, 10, 15], dtype=float)
    curve_yields = np.array([2.45, 2.48, 2.52, 2.60, 2.75, 2.92, 3.10, 3.30], dtype=float)

    def base_curve_yield(years: float) -> float:
        return float(np.interp(years, curve_tenors, curve_yields))

    def bond_metrics(face_m, coupon_pct, yield_pct, years):
        n = max(1, int(round(years)))
        c = coupon_pct / 100.0
        y = yield_pct / 100.0

        times = np.arange(1, n + 1, dtype=float)
        cashflows = np.full(n, face_m * c)
        cashflows[-1] += face_m

        disc = (1 + y) ** times
        pv = cashflows / disc
        price_m = pv.sum()

        macaulay = float((times * pv).sum() / price_m)
        modified = macaulay / (1 + y)
        convexity = float(
            (times * (times + 1) * pv).sum()
            / (price_m * (1 + y) ** 2)
        )

        return price_m / face_m * 100, price_m, modified, convexity

    raw_weights = rng.dirichlet(np.repeat(2.3, n_positions))
    book_values = raw_weights * securities_total_m

    rows = []

    for i in range(n_positions):
        asset_class = rng.choice(asset_classes, p=asset_class_probs)
        country = rng.choice(countries, p=country_probs)
        issuer = rng.choice(issuers[country][asset_class])

        rating_vals, rating_probs = rating_by_class[asset_class]
        rating = rng.choice(rating_vals, p=rating_probs)

        years_to_maturity = float(
            rng.choice(
                [1, 2, 3, 4, 5, 7, 8, 10, 12, 15],
                p=[0.05, 0.08, 0.12, 0.10, 0.17, 0.16, 0.08, 0.13, 0.06, 0.05],
            )
        )
        maturity_date = as_of_date + pd.DateOffset(years=int(years_to_maturity))
        base_yield = base_curve_yield(years_to_maturity)

        if asset_class == "Sovereign":
            spread_bps = max(0, country_spread_bps[country] + rng.normal(0, 5))
        else:
            class_adjustment = {
                "Covered Bond": -5,
                "Agency/Supranational": -10,
                "Corporate Bond": 15,
            }[asset_class]
            spread_bps = max(
                8,
                spread_bps_by_rating[rating]
                + country_spread_bps[country] * 0.35
                + class_adjustment
                + rng.normal(0, 7),
            )

        yield_pct = base_yield + spread_bps / 100.0
        coupon_pct = float(np.clip(yield_pct + rng.normal(0.05, 0.45), 0.25, 6.0))

        book_value_m = float(book_values[i])
        face_value_m = book_value_m

        price_pct, market_value_m, modified_duration, convexity = bond_metrics(
            face_value_m, coupon_pct, yield_pct, years_to_maturity
        )

        unrealized_pnl_m = market_value_m - book_value_m
        dv01_m_per_bp = market_value_m * modified_duration * 0.0001

        if years_to_maturity <= 2:
            maturity_bucket = "0-2Y"
        elif years_to_maturity <= 5:
            maturity_bucket = "2-5Y"
        elif years_to_maturity <= 10:
            maturity_bucket = "5-10Y"
        else:
            maturity_bucket = "10Y+"

        rows.append(
            {
                "position_id": f"TRSY_{i+1:03d}",
                "as_of_date": as_of_date.date(),
                "issuer": issuer,
                "issuer_country": country,
                "asset_class": asset_class,
                "rating": rating,
                "currency": "EUR",
                "accounting_classification": rng.choice(
                    ["FVOCI", "Amortised Cost"], p=[0.68, 0.32]
                ),
                "is_green_bond": int(
                    rng.random()
                    < (0.18 if asset_class in ["Sovereign", "Agency/Supranational"] else 0.12)
                ),
                "maturity_date": maturity_date.date(),
                "years_to_maturity": years_to_maturity,
                "maturity_bucket": maturity_bucket,
                "face_value_m": round(face_value_m, 3),
                "book_value_m": round(book_value_m, 3),
                "market_value_m": round(market_value_m, 3),
                "price_pct": round(price_pct, 4),
                "coupon_pct": round(coupon_pct, 4),
                "yield_pct": round(yield_pct, 4),
                "credit_spread_bps": round(spread_bps, 1),
                "modified_duration": round(modified_duration, 4),
                "convexity": round(convexity, 4),
                "dv01_m_per_bp": round(dv01_m_per_bp, 4),
                "unrealized_pnl_m": round(unrealized_pnl_m, 3),
            }
        )

    portfolio = pd.DataFrame(rows)

    drift = round(securities_total_m - portfolio["book_value_m"].sum(), 3)
    portfolio.loc[portfolio.index[-1], "book_value_m"] += drift
    portfolio.loc[portfolio.index[-1], "face_value_m"] += drift

    scenario_defs = [
        ("Rates +25bps", 25, 0, "Parallel EUR yield-curve increase of 25 bps."),
        ("Rates +50bps", 50, 0, "Parallel EUR yield-curve increase of 50 bps."),
        ("Rates -50bps", -50, 0, "Parallel EUR yield-curve decrease of 50 bps."),
        ("Credit spreads +75bps", 0, 75, "Credit spread widening of 75 bps on non-sovereign holdings."),
        ("Rates +50bps & spreads +75bps", 50, 75, "Combined higher-rate and credit-spread stress."),
    ]

    scenario_rows = []

    for p in portfolio.itertuples(index=False):
        for scenario_name, rate_shock_bps, credit_spread_shock_bps, desc in scenario_defs:
            spread_shock = (
                credit_spread_shock_bps if p.asset_class != "Sovereign" else 0
            )
            total_yield_shock_bps = rate_shock_bps + spread_shock
            dy = total_yield_shock_bps / 10_000.0

            pct_change = (
                -p.modified_duration * dy
                + 0.5 * p.convexity * (dy ** 2)
            )
            pnl_m = p.market_value_m * pct_change

            scenario_rows.append(
                {
                    "position_id": p.position_id,
                    "scenario_name": scenario_name,
                    "scenario_description": desc,
                    "rate_shock_bps": rate_shock_bps,
                    "credit_spread_shock_bps": spread_shock,
                    "total_yield_shock_bps": total_yield_shock_bps,
                    "base_market_value_m": round(p.market_value_m, 3),
                    "stressed_market_value_m": round(p.market_value_m + pnl_m, 3),
                    "market_value_impact_m": round(pnl_m, 3),
                    "market_value_impact_pct": round(pct_change * 100, 4),
                }
            )

    scenarios = pd.DataFrame(scenario_rows)

    # Enrich scenarios with position descriptors and distinguish economic
    # valuation impact from simplified accounting recognition.
    scenarios = scenarios.merge(
        portfolio[
            [
                "position_id",
                "issuer",
                "issuer_country",
                "asset_class",
                "rating",
                "accounting_classification",
                "maturity_bucket",
            ]
        ],
        on="position_id",
        how="left",
    )

    scenarios["economic_value_impact_m"] = scenarios["market_value_impact_m"]

    scenarios["estimated_oci_impact_m"] = scenarios.apply(
        lambda r: r["market_value_impact_m"]
        if r["accounting_classification"] == "FVOCI"
        else 0.0,
        axis=1,
    )

    scenarios["estimated_immediate_pnl_impact_m"] = 0.0
    scenarios["accounting_impact_note"] = scenarios[
        "accounting_classification"
    ].map(
        {
            "FVOCI": (
                "Prototype assumption: market-value movement is reflected in OCI; "
                "no immediate P&L impact is modelled."
            ),
            "Amortised Cost": (
                "Prototype assumption: market-rate valuation movement is economic value only; "
                "no immediate OCI/P&L impact is modelled. ECL effects are outside this scenario."
            ),
        }
    )

    scenarios = scenarios[
        [
            "position_id",
            "issuer",
            "issuer_country",
            "asset_class",
            "rating",
            "accounting_classification",
            "maturity_bucket",
            "scenario_name",
            "scenario_description",
            "rate_shock_bps",
            "credit_spread_shock_bps",
            "total_yield_shock_bps",
            "base_market_value_m",
            "stressed_market_value_m",
            "economic_value_impact_m",
            "market_value_impact_pct",
            "estimated_oci_impact_m",
            "estimated_immediate_pnl_impact_m",
            "accounting_impact_note",
        ]
    ]

    portfolio_mv = float(portfolio["market_value_m"].sum())
    portfolio_dv01 = float(portfolio["dv01_m_per_bp"].sum())
    rate50_before = float(
        scenarios.loc[
            scenarios["scenario_name"] == "Rates +50bps",
            "economic_value_impact_m",
        ].sum()
    )
    five_to_ten_dv01 = float(
        portfolio.loc[
            portfolio["maturity_bucket"] == "5-10Y",
            "dv01_m_per_bp",
        ].sum()
    )

    hedge_specs = [
        ("HEDGE_25", "25% portfolio duration hedge", portfolio_dv01 * 0.25, 5.0),
        ("HEDGE_50", "50% portfolio duration hedge", portfolio_dv01 * 0.50, 5.0),
        ("HEDGE_75", "75% portfolio duration hedge", portfolio_dv01 * 0.75, 5.0),
        ("HEDGE_5_10Y", "70% hedge of 5-10Y DV01 concentration", five_to_ten_dv01 * 0.70, 7.0),
    ]

    swap_fixed_rate_pct = 2.75
    floating_reference_pct = 2.54
    carry_spread_pct = swap_fixed_rate_pct - floating_reference_pct

    hedge_rows = []

    for hedge_id, hedge_name, target_dv01_reduction, hedge_duration in hedge_specs:
        dv01_per_1m_notional = hedge_duration * 0.0001
        notional_m = target_dv01_reduction / dv01_per_1m_notional
        post_hedge_dv01 = max(portfolio_dv01 - target_dv01_reduction, 0)

        hedge_gain_50bp_m = target_dv01_reduction * 50
        post_hedge_rate50_pnl_m = rate50_before + hedge_gain_50bp_m
        annual_carry_m = -notional_m * (carry_spread_pct / 100.0)

        hedge_rows.append(
            {
                "hedge_id": hedge_id,
                "hedge_name": hedge_name,
                "hedge_instrument": "EUR pay-fixed / receive-floating IRS",
                "assumed_swap_duration_years": hedge_duration,
                "hedge_notional_m": round(notional_m, 1),
                "target_dv01_reduction_m_per_bp": round(target_dv01_reduction, 3),
                "portfolio_dv01_before_m_per_bp": round(portfolio_dv01, 3),
                "portfolio_dv01_after_m_per_bp": round(post_hedge_dv01, 3),
                "dv01_reduction_pct": round(target_dv01_reduction / portfolio_dv01 * 100, 1),
                "rates_plus_50bp_pnl_before_m": round(rate50_before, 1),
                "estimated_hedge_gain_plus_50bp_m": round(hedge_gain_50bp_m, 1),
                "rates_plus_50bp_pnl_after_m": round(post_hedge_rate50_pnl_m, 1),
                "assumed_fixed_swap_rate_pct": swap_fixed_rate_pct,
                "assumed_floating_reference_pct": floating_reference_pct,
                "estimated_annual_carry_m": round(annual_carry_m, 1),
                "methodology_note": (
                    "Simplified DV01 hedge estimate for prototype use; does not include "
                    "full swap valuation, basis, collateral, counterparty, liquidity "
                    "or hedge-accounting effects."
                ),
            }
        )

    hedges = pd.DataFrame(hedge_rows)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    portfolio.to_csv(out / "treasury_portfolio.csv", index=False)
    scenarios.to_csv(out / "treasury_scenario_impacts.csv", index=False)
    hedges.to_csv(out / "treasury_hedge_options.csv", index=False)

    return portfolio, scenarios, hedges


if __name__ == "__main__":
    portfolio, scenarios, hedges = generate_treasury_datasets()
    print(f"Created treasury_portfolio.csv with {len(portfolio)} positions.")
    print(f"Created treasury_scenario_impacts.csv with {len(scenarios)} rows.")
    print(f"Created treasury_hedge_options.csv with {len(hedges)} options.")
