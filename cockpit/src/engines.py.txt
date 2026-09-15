"""
The two decision engines behind the Horizon and What-If modules.

Both are deterministic and anchored on the certified actuals, so a CFO can
challenge every assumption. Neither is a forecast, a budget or management
guidance.
"""

import pandas as pd

# How much of the latest 30-day repricing momentum is carried into each
# projected month. Momentum halves each step rather than persisting, because a
# repricing move observed over one month does not repeat indefinitely.
REPRICING_DECAY = [0.50, 0.25, 0.125, 0.0625]

# Guard rails on extrapolated growth, so one unusual month cannot compound.
MAX_MONTHLY_ASSET_GROWTH = 0.02
MAX_MONTHLY_DEPOSIT_GROWTH = 0.03

BASELINE_METHOD = (
    "Latest certified NIM and balance sheet; earning assets follow the median "
    "of the latest 3 monthly moves; deposits use the latest 30D growth rate; "
    "only 50% of the latest 30D loan/deposit repricing is carried into the "
    "first projected month, and that repricing momentum halves each month "
    "after."
)


def build_horizon_baseline(
    monthly_nim,
    months_ahead,
    current_loans_m,
    current_deposits_m,
    current_loan_rate_pct,
    current_deposit_rate_pct,
    loan_rate_30d_bps,
    deposit_rate_30d_bps,
    deposit_growth_30d_pct,
):
    """
    A momentum-decay run-rate baseline for NIM.

    It answers one narrow question: if the latest balance-sheet trend continues
    and the most recent repricing momentum fades progressively, where does the
    current run rate land?

    Returns the actual-plus-baseline path and a dict of headline metrics.
    """
    numeric_columns = ["nim_pct", "monthly_nii_m", "avg_interest_earning_assets_m"]

    local = monthly_nim.copy().sort_values("month")
    for column in numeric_columns:
        local[column] = pd.to_numeric(local[column], errors="coerce")
    local = local.dropna(subset=numeric_columns)

    if local.empty:
        return pd.DataFrame(), {}

    latest = local.iloc[-1]
    latest_month = pd.Timestamp(latest["month"]).to_period("M").to_timestamp()
    latest_nim = float(latest["nim_pct"])

    # Median of the last three moves, so a single outlier month does not set
    # the trajectory.
    assets = local["avg_interest_earning_assets_m"].astype(float)
    growth_series = (
        assets.pct_change().replace([float("inf"), float("-inf")], pd.NA).dropna()
    )
    monthly_asset_growth = (
        float(growth_series.tail(3).median()) if not growth_series.empty else 0.0
    )
    monthly_asset_growth = max(
        -MAX_MONTHLY_ASSET_GROWTH, min(MAX_MONTHLY_ASSET_GROWTH, monthly_asset_growth)
    )

    monthly_deposit_growth = max(
        -MAX_MONTHLY_DEPOSIT_GROWTH,
        min(MAX_MONTHLY_DEPOSIT_GROWTH, float(deposit_growth_30d_pct) / 100.0),
    )

    # The simplified loan-minus-deposit spread does not reproduce the whole of
    # NII. The residual holds everything else constant so the projection starts
    # from the certified level rather than from the simplification.
    base_annual_nii = latest_nim / 100.0 * float(current_loans_m)
    simplified_base_nii = (
        float(current_loans_m) * float(current_loan_rate_pct) / 100.0
        - float(current_deposits_m) * float(current_deposit_rate_pct) / 100.0
    )
    residual_annual_nii = base_annual_nii - simplified_base_nii

    rows = [
        {
            "month": pd.Timestamp(row["month"]).to_period("M").to_timestamp(),
            "month_label": pd.Timestamp(row["month"]).strftime("%b"),
            "nim_pct": float(row["nim_pct"]),
            "monthly_nii_m": float(row["monthly_nii_m"]),
            "avg_interest_earning_assets_m": float(
                row["avg_interest_earning_assets_m"]
            ),
            "series": "Actual",
            "loan_rate_pct": None,
            "deposit_rate_pct": None,
        }
        for _, row in local.iterrows()
    ]

    projected_assets = float(current_loans_m)
    projected_deposits = float(current_deposits_m)
    projected_loan_rate = float(current_loan_rate_pct)
    projected_deposit_rate = float(current_deposit_rate_pct)
    forecast_nii_total = 0.0

    for step in range(1, months_ahead + 1):
        month = latest_month + pd.offsets.MonthBegin(step)
        decay = REPRICING_DECAY[min(step - 1, len(REPRICING_DECAY) - 1)]

        projected_assets *= 1.0 + monthly_asset_growth
        projected_deposits *= 1.0 + monthly_deposit_growth

        projected_loan_rate += (float(loan_rate_30d_bps) / 100.0) * decay
        projected_deposit_rate += (float(deposit_rate_30d_bps) / 100.0) * decay

        annual_nii = (
            projected_assets * projected_loan_rate / 100.0
            - projected_deposits * projected_deposit_rate / 100.0
            + residual_annual_nii
        )

        forecast_nim = (
            annual_nii / projected_assets * 100.0 if projected_assets else latest_nim
        )

        days = int(pd.Period(month, freq="M").days_in_month)
        forecast_nii = annual_nii * days / 365.0
        forecast_nii_total += forecast_nii

        rows.append(
            {
                "month": month,
                "month_label": month.strftime("%b"),
                "nim_pct": forecast_nim,
                "monthly_nii_m": forecast_nii,
                "avg_interest_earning_assets_m": projected_assets,
                "series": "Baseline",
                "loan_rate_pct": projected_loan_rate,
                "deposit_rate_pct": projected_deposit_rate,
            }
        )

    output = pd.DataFrame(rows).sort_values("month").reset_index(drop=True)

    actual_nii_ytd = float(local["monthly_nii_m"].sum())
    year_end_nim = float(output.iloc[-1]["nim_pct"])

    forward = output[output["series"] == "Baseline"]
    first_forward_nim = (
        float(forward.iloc[0]["nim_pct"]) if not forward.empty else latest_nim
    )

    metrics = {
        "latest_nim_pct": latest_nim,
        "year_end_nim_pct": year_end_nim,
        "current_to_year_end_bps": (year_end_nim - latest_nim) * 100.0,
        "first_month_nim_change_bps": (first_forward_nim - latest_nim) * 100.0,
        "trailing_asset_growth_pct": monthly_asset_growth * 100.0,
        "deposit_growth_run_rate_pct": monthly_deposit_growth * 100.0,
        "forecast_nii_remaining_m": forecast_nii_total,
        "full_year_nii_m": actual_nii_ytd + forecast_nii_total,
        "actual_nii_ytd_m": actual_nii_ytd,
        "actual_months": int(len(local)),
        "residual_annual_nii_m": residual_annual_nii,
        "baseline_method": BASELINE_METHOD,
    }

    return output, metrics


def calculate_scenario(
    current_nim_pct,
    current_loans_m,
    current_deposits_m,
    current_loan_rate_pct,
    current_deposit_rate_pct,
    ecb_shock_bps,
    deposit_balance_shock_pct,
    horizon_days,
    loan_beta_pct=35.0,
    deposit_beta_pct=55.0,
    replacement_funding_rate_pct=3.25,
):
    """
    A governed balance-sheet shock, anchored on the certified position.

    Loan and deposit rates reprice at their own betas, scaled by how far into
    the year the horizon reaches. Deposits that leave are replaced at wholesale
    funding cost, which is what usually dominates a deposit-outflow scenario.
    """
    horizon_factor = max(0.0, min(1.0, float(horizon_days) / 365.0))

    loan_beta = float(loan_beta_pct) / 100.0
    deposit_beta = float(deposit_beta_pct) / 100.0

    base_loan_rate = float(current_loan_rate_pct)
    base_deposit_rate = float(current_deposit_rate_pct)
    base_loans = float(current_loans_m)
    base_deposits = float(current_deposits_m)

    loan_rate_change_pp = float(ecb_shock_bps) / 100.0 * loan_beta * horizon_factor
    deposit_rate_change_pp = (
        float(ecb_shock_bps) / 100.0 * deposit_beta * horizon_factor
    )

    scenario_loan_rate = base_loan_rate + loan_rate_change_pp
    scenario_deposit_rate = base_deposit_rate + deposit_rate_change_pp

    scenario_deposits = base_deposits * (
        1.0 + float(deposit_balance_shock_pct) / 100.0
    )
    lost_deposits_m = max(0.0, base_deposits - scenario_deposits)
    added_deposits_m = max(0.0, scenario_deposits - base_deposits)

    base_annual_nii_m = float(current_nim_pct) / 100.0 * base_loans
    loan_repricing_impact_m = base_loans * loan_rate_change_pp / 100.0

    base_deposit_expense_m = base_deposits * base_deposit_rate / 100.0
    scenario_deposit_expense_m = scenario_deposits * scenario_deposit_rate / 100.0
    replacement_funding_expense_m = (
        lost_deposits_m * float(replacement_funding_rate_pct) / 100.0
    )

    funding_cost_change_m = (
        scenario_deposit_expense_m
        + replacement_funding_expense_m
        - base_deposit_expense_m
    )

    scenario_annual_nii_m = (
        base_annual_nii_m + loan_repricing_impact_m - funding_cost_change_m
    )
    annual_nii_impact_m = scenario_annual_nii_m - base_annual_nii_m

    scenario_nim_pct = (
        scenario_annual_nii_m / base_loans * 100.0
        if base_loans
        else float(current_nim_pct)
    )

    return {
        "current_annual_nii_m": base_annual_nii_m,
        "scenario_annual_nii_m": scenario_annual_nii_m,
        "annual_nii_impact_m": annual_nii_impact_m,
        "horizon_nii_impact_m": annual_nii_impact_m * horizon_factor,
        "current_nim_pct": float(current_nim_pct),
        "scenario_nim_pct": scenario_nim_pct,
        "nim_impact_bps": (scenario_nim_pct - float(current_nim_pct)) * 100.0,
        "current_loan_rate_pct": base_loan_rate,
        "scenario_loan_rate_pct": scenario_loan_rate,
        "current_deposit_rate_pct": base_deposit_rate,
        "scenario_deposit_rate_pct": scenario_deposit_rate,
        "loan_repricing_impact_m": loan_repricing_impact_m,
        "funding_cost_change_m": funding_cost_change_m,
        "lost_deposits_m": lost_deposits_m,
        "added_deposits_m": added_deposits_m,
        "replacement_funding_expense_m": replacement_funding_expense_m,
        "horizon_factor": horizon_factor,
    }


# How far either pass-through beta could plausibly sit from the assumption.
BETA_UNCERTAINTY_PP = 15.0


def scenario_beta_range(**scenario_inputs):
    """
    The scenario result across the plausible range of pass-through betas.
    The betas are the least observable assumptions in the engine, so the
    scenario is re-run at every corner of ±15pp on both and the spread of
    outcomes is returned. That spread is what the confidence reading measures.
    """
    loan_beta = float(scenario_inputs["loan_beta_pct"])
    deposit_beta = float(scenario_inputs["deposit_beta_pct"])
    outcomes = []
    for loan_shift in (-BETA_UNCERTAINTY_PP, BETA_UNCERTAINTY_PP):
        for deposit_shift in (-BETA_UNCERTAINTY_PP, BETA_UNCERTAINTY_PP):
            corner = dict(scenario_inputs)
            corner["loan_beta_pct"] = max(0.0, min(100.0, loan_beta + loan_shift))
            corner["deposit_beta_pct"] = max(
                0.0, min(100.0, deposit_beta + deposit_shift)
            )
            outcomes.append(calculate_scenario(**corner))
    return {
        key: (
            min(outcome[key] for outcome in outcomes),
            max(outcome[key] for outcome in outcomes),
        )
        for key in outcomes[0]
    }
