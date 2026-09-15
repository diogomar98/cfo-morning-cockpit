import numpy as np
import pandas as pd


def calculate_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate cockpit metrics from raw monthly bank data."""
    result = df.copy()

    # Capital adequacy
    result["cet1_ratio_pct"] = (
        100 * result["cet1_capital"] / result["rwa"]
    )

    result["tier1_ratio_pct"] = (
        100 * (result["cet1_capital"] + result["at1_capital"]) / result["rwa"]
    )

    result["total_capital_ratio_pct"] = (
        100
        * (
            result["cet1_capital"]
            + result["at1_capital"]
            + result["tier2_capital"]
        )
        / result["rwa"]
    )

    result["leverage_ratio_pct"] = (
        100 * (result["cet1_capital"] + result["at1_capital"])
        / result["total_assets"]
    )

    result["rwa_density_pct"] = 100 * result["rwa"] / result["ead"]

    # Liquidity and balance sheet
    result["lcr_pct"] = (
        100 * result["hqla"] / result["net_cash_outflows"]
    )

    result["loan_to_deposit_pct"] = (
        100 * result["loans"] / result["deposits"]
    )

    result["deposit_growth_mom_pct"] = (
        100 * result["deposits"].pct_change()
    )

    result["deposit_growth_yoy_pct"] = (
        100 * result["deposits"].pct_change(12)
    )

    result["loan_growth_mom_pct"] = (
        100 * result["loans"].pct_change()
    )

    result["loan_growth_yoy_pct"] = (
        100 * result["loans"].pct_change(12)
    )

    # Earnings
    result["nim_pct"] = (
        100 * 12 * result["nii"] / result["loans"]
    )

    result["cost_to_income_pct"] = (
        100 * result["operating_costs"] / result["operating_income"]
    )

    result["pre_tax_profit_margin_pct"] = (
        100 * result["pre_tax_profit"] / result["operating_income"]
    )

    # Asset quality
    result["stage_3_ratio_pct"] = result["stage_3_share_pct"]

    result["coverage_ratio_pct"] = (
        100 * result["provisions"] / result["gca"]
    )

    # The generator emits the monthly IFRS 9 impairment charge directly. Fall
    # back to the month-on-month change in the allowance balance when a caller
    # passes raw data that predates that column.
    if "provision_charge" not in result.columns:
        result["provision_charge"] = result["provisions"].diff().clip(lower=0)

    result["cost_of_risk_bps"] = (
        10_000 * 12 * result["provision_charge"] / result["loans"]
    )

    # Data-quality protection: replace initial pct_change / diff NaNs.
    result = result.replace([np.inf, -np.inf], np.nan)

    return result