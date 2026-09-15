from pathlib import Path

import numpy as np
import pandas as pd


def generate_bank_history(months: int = 48, seed: int = 42) -> pd.DataFrame:
    """
    Create synthetic monthly data for a fictional European universal bank.
    Monetary values are in EUR millions unless stated otherwise.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end="2026-08-31", periods=months, freq="ME")

    rows = []

    # Opening balance-sheet values in EUR millions
    loans = 300_000
    deposits = 335_000
    hqla = 78_000
    securities = 95_000
    wholesale_funding = 70_000
    cet1_capital = 26_000
    at1_capital = 5_500
    tier2_capital = 4_000
    operating_costs = 390


    # Post-tax distribution assumptions.
    tax_rate = 0.25
    dividend_payout_ratio = 0.60

    # Interest-rate and credit-risk starting assumptions
    ecb_rate = 3.50
    avg_loan_yield = 4.60
    avg_deposit_cost = 1.80
    stage_2_share = 0.075
    stage_3_share = 0.025

    for i, date in enumerate(dates):
        # A modest downward rate cycle from the middle of the history.
        if i > months * 0.55:
            ecb_rate += rng.normal(-0.06, 0.035)
        else:
            ecb_rate += rng.normal(0.01, 0.035)

        ecb_rate = float(np.clip(ecb_rate, 1.50, 4.50))

        # Balance-sheet growth and movements.
        loan_growth_rate = rng.normal(0.0030, 0.0025)
        deposit_growth_rate = rng.normal(0.0022, 0.0035)

        loans *= 1 + loan_growth_rate
        deposits *= 1 + deposit_growth_rate

        # Add an identifiable deposit-stress event for the story.
        if i == months - 7:
            deposits *= 0.965

        deposit_movement = deposits - (rows[-1]["deposits"] if rows else 335_000)

        # Credit quality gradually weakens when rates are high.
        stage_2_share += 0.0005 * max(ecb_rate - 2.50, 0) + rng.normal(0, 0.0010)
        stage_3_share += 0.00015 * max(ecb_rate - 3.00, 0) + rng.normal(0, 0.0003)

        stage_2_share = float(np.clip(stage_2_share, 0.04, 0.16))
        stage_3_share = float(np.clip(stage_3_share, 0.015, 0.06))
        stage_1_share = 1 - stage_2_share - stage_3_share

        # Gross carrying amount: simplified as the on-balance-sheet lending book.
        gca = loans

        # EAD includes a modest credit-conversion amount from off-balance-sheet facilities.
        ead = gca * 1.08

        # IFRS 9-style expected-loss assumptions.
        pd_stage_1 = 0.007
        pd_stage_2 = 0.055
        pd_stage_3 = 1.00
        lgd_stage_1 = 0.30
        lgd_stage_2 = 0.38
        lgd_stage_3 = 0.45

        provisions = (
            ead * stage_1_share * pd_stage_1 * lgd_stage_1
            + ead * stage_2_share * pd_stage_2 * lgd_stage_2
            + ead * stage_3_share * pd_stage_3 * lgd_stage_3
        )

        # Credit RWA approximation: linked to riskiness and exposure.
        average_risk_weight = (
            0.42
            + 0.30 * stage_2_share
            + 0.70 * stage_3_share
        )
        credit_rwa = ead * average_risk_weight
        operational_rwa = 16_000
        market_rwa = 7_000
        rwa = credit_rwa + operational_rwa + market_rwa

        # HQLA and stressed outflows determine LCR.
        hqla *= 1 + rng.normal(0.001, 0.015)
        net_cash_outflows = (
            0.10 * deposits
            + 0.25 * wholesale_funding
            + rng.normal(0, 1_000)
        )
        net_cash_outflows = max(net_cash_outflows, 1)

        # Interest-rate pass-through: deposit costs reprice more slowly.
        avg_loan_yield += 0.25 * (ecb_rate - avg_loan_yield + 1.1) + rng.normal(0, 0.035)
        avg_deposit_cost += 0.18 * (ecb_rate - avg_deposit_cost - 0.8) + rng.normal(0, 0.025)

        avg_loan_yield = float(np.clip(avg_loan_yield, 2.5, 7.0))
        avg_deposit_cost = float(np.clip(avg_deposit_cost, 0.3, 4.5))

        monthly_interest_income = loans * (avg_loan_yield / 100) / 12
        monthly_interest_expense = deposits * (avg_deposit_cost / 100) / 12
        nii = monthly_interest_income - monthly_interest_expense

        fee_income = loans * 0.0035 / 12
        other_income = 180 + rng.normal(0, 15)
        operating_income = nii + fee_income + other_income

        operating_costs *= 1 + rng.normal(0.0015, 0.006)
        monthly_provision_charge = max(
            0,
            provisions - (rows[-1]["provisions"] if rows else provisions * 0.98)
        )

        pre_tax_profit = operating_income - operating_costs - monthly_provision_charge

        # Losses are not sheltered by tax; profits are taxed and partly paid out.
        tax_expense = max(pre_tax_profit, 0) * tax_rate
        net_profit = pre_tax_profit - tax_expense
        dividends = max(net_profit, 0) * dividend_payout_ratio
        retained_earnings = net_profit - dividends

        cet1_capital += retained_earnings

        total_assets = loans + hqla + securities + 55_000
        total_liabilities = deposits + wholesale_funding + 80_000

        rows.append(
            {
                "date": date,
                "loans": loans,
                "deposits": deposits,
                "deposit_movement": deposit_movement,
                "loan_growth_mom_pct": loan_growth_rate * 100,
                "gca": gca,
                "ead": ead,
                "provisions": provisions,
                "stage_1_share_pct": stage_1_share * 100,
                "stage_2_share_pct": stage_2_share * 100,
                "stage_3_share_pct": stage_3_share * 100,
                "rwa": rwa,
                "cet1_capital": cet1_capital,
                "at1_capital": at1_capital,
                "tier2_capital": tier2_capital,
                "hqla": hqla,
                "net_cash_outflows": net_cash_outflows,
                "ecb_rate_pct": ecb_rate,
                "avg_loan_yield_pct": avg_loan_yield,
                "avg_deposit_cost_pct": avg_deposit_cost,
                "nii": nii,
                "fee_income": fee_income,
                "other_income": other_income,
                "operating_income": operating_income,
                "operating_costs": operating_costs,
                "provision_charge": monthly_provision_charge,
                "pre_tax_profit": pre_tax_profit,
                "tax_expense": tax_expense,
                "net_profit": net_profit,
                "dividends": dividends,
                "retained_earnings": retained_earnings,
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
            }
        )

    return pd.DataFrame(rows).set_index("date")


if __name__ == "__main__":
    output_path = Path("data/bank_history.csv")
    output_path.parent.mkdir(exist_ok=True)

    bank_history = generate_bank_history()
    bank_history.to_csv(output_path)

    print(f"Created {output_path} with {len(bank_history)} monthly observations.")