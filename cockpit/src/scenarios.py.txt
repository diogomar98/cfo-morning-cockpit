import pandas as pd

from src.metrics import calculate_metrics


def run_scenario(
    history: pd.DataFrame,
    rate_shock_bps: int = 0,
    deposit_outflow_pct: float = 0.0,
    stage_2_increase_pct_points: float = 0.0,
    stage_3_increase_pct_points: float = 0.0,
) -> pd.DataFrame:
    """
    Apply an illustrative shock to the latest bank state.

    The output contains the baseline latest month plus a stressed month.
    Monetary values are EUR millions.
    """
    baseline = history.iloc[-1].copy()
    stressed = baseline.copy()

    rate_shock_pct = rate_shock_bps / 100

    # Interest-rate shock: assets reprice faster than deposits.
    stressed["ecb_rate_pct"] += rate_shock_pct
    stressed["avg_loan_yield_pct"] += 0.60 * rate_shock_pct
    stressed["avg_deposit_cost_pct"] += 0.35 * rate_shock_pct

    stressed["nii"] = (
        stressed["loans"] * (stressed["avg_loan_yield_pct"] / 100) / 12
        - stressed["deposits"] * (stressed["avg_deposit_cost_pct"] / 100) / 12
    )

    stressed["operating_income"] = (
        stressed["nii"]
        + stressed["fee_income"]
        + (baseline["operating_income"] - baseline["nii"] - baseline["fee_income"])
    )

    # Deposit outflow: deposits fall and HQLA is used to meet part of the outflow.
    deposit_outflow = stressed["deposits"] * deposit_outflow_pct / 100
    stressed["deposits"] -= deposit_outflow
    stressed["hqla"] -= deposit_outflow * 0.70
    stressed["net_cash_outflows"] += deposit_outflow * 0.20

    # Credit deterioration: migrate the portfolio between IFRS 9 stages.
    stressed["stage_2_share_pct"] += stage_2_increase_pct_points
    stressed["stage_3_share_pct"] += stage_3_increase_pct_points
    stressed["stage_1_share_pct"] = (
        100
        - stressed["stage_2_share_pct"]
        - stressed["stage_3_share_pct"]
    )

    # Increase total provisions and RWA as credit risk deteriorates.
    credit_loss_add_on = (
        stressed["ead"]
        * (
            0.0015 * stage_2_increase_pct_points
            + 0.0060 * stage_3_increase_pct_points
        )
    )

    stressed["provisions"] += credit_loss_add_on
    stressed["rwa"] += stressed["ead"] * (
        0.004 * stage_2_increase_pct_points
        + 0.012 * stage_3_increase_pct_points
    )

    # Provision charge reduces profit and CET1 capital.
    stressed["pre_tax_profit"] -= credit_loss_add_on
    stressed["cet1_capital"] -= credit_loss_add_on * 0.75

    stressed["total_assets"] = (
        stressed["total_assets"]
        - deposit_outflow * 0.70
    )

    comparison = pd.DataFrame(
        [baseline, stressed],
        index=["Baseline", "Scenario"],
    )

    return calculate_metrics(comparison)