from __future__ import annotations

import re

import pandas as pd

from src.scenarios import run_scenario


def format_eur_millions(value: float) -> str:
    return f"€{value:,.0f}m"


def get_status(value, amber, red, higher_is_worse=False):
    """Return a simple risk status label."""
    if higher_is_worse:
        if value >= red:
            return "Red"
        if value >= amber:
            return "Amber"
        return "Green"

    if value <= red:
        return "Red"
    if value <= amber:
        return "Amber"
    return "Green"


def build_morning_briefing(df: pd.DataFrame) -> str:
    """Create a deterministic 30-second CFO briefing from cockpit data."""
    latest = df.iloc[-1]
    previous = df.iloc[-2]

    cet1_change = latest["cet1_ratio_pct"] - previous["cet1_ratio_pct"]
    lcr_change = latest["lcr_pct"] - previous["lcr_pct"]
    nim_change = latest["nim_pct"] - previous["nim_pct"]
    deposit_change = latest["deposit_movement"]

    cet1_status = get_status(
        latest["cet1_ratio_pct"],
        amber=14.5,
        red=13.75,
    )

    lcr_status = get_status(
        latest["lcr_pct"],
        amber=130,
        red=110,
    )

    cost_income_status = get_status(
        latest["cost_to_income_pct"],
        amber=60,
        red=70,
        higher_is_worse=True,
    )

    stage_3_status = get_status(
        latest["stage_3_ratio_pct"],
        amber=2.5,
        red=3.5,
        higher_is_worse=True,
    )

    positives = []
    risks = []

    if cet1_status == "Green":
        positives.append(
            f"capital remains sound at {latest['cet1_ratio_pct']:.2f}% CET1"
        )
    else:
        risks.append(
            f"CET1 is {cet1_status.lower()} at {latest['cet1_ratio_pct']:.2f}%"
        )

    if lcr_status == "Green":
        positives.append(
            f"liquidity remains strong, with LCR at {latest['lcr_pct']:.0f}%"
        )
    else:
        risks.append(
            f"LCR is {lcr_status.lower()} at {latest['lcr_pct']:.0f}%"
        )

    if nim_change < -0.03:
        risks.append(
            f"NIM declined {abs(nim_change):.2f} percentage points to "
            f"{latest['nim_pct']:.2f}%"
        )

    if deposit_change < 0:
        risks.append(
            f"deposits declined by {format_eur_millions(abs(deposit_change))} "
            f"during the month"
        )

    if stage_3_status != "Green":
        risks.append(
            f"Stage 3 exposure is {stage_3_status.lower()} at "
            f"{latest['stage_3_ratio_pct']:.2f}%"
        )

    if cost_income_status != "Green":
        risks.append(
            f"cost-to-income is {cost_income_status.lower()} at "
            f"{latest['cost_to_income_pct']:.1f}%"
        )

    positive_text = "; ".join(positives) if positives else "no material positive signal"
    risk_text = "; ".join(risks) if risks else "no immediate risk threshold breach"

    return (
        f"**Morning briefing — {df.index[-1]:%d %B %Y}**\n\n"
        f"Overall, {positive_text}. "
        f"Key watchpoints: {risk_text}. "
        f"Monthly NII is {format_eur_millions(latest['nii'])}, while "
        f"loan growth is {latest['loan_growth_yoy_pct']:.2f}% year-on-year."
    )


def explain_nim(df: pd.DataFrame) -> str:
    """Explain the latest NIM movement using the model's actual drivers."""
    latest = df.iloc[-1]
    previous = df.iloc[-2]

    nim_change = latest["nim_pct"] - previous["nim_pct"]
    loan_yield_change = (
        latest["avg_loan_yield_pct"] - previous["avg_loan_yield_pct"]
    )
    deposit_cost_change = (
        latest["avg_deposit_cost_pct"] - previous["avg_deposit_cost_pct"]
    )
    nii_change = latest["nii"] - previous["nii"]

    direction = "declined" if nim_change < 0 else "increased"

    return (
        f"**NIM analysis**\n\n"
        f"NIM {direction} by {abs(nim_change):.2f} percentage points to "
        f"{latest['nim_pct']:.2f}% versus the prior month. "
        f"Average loan yield moved by {loan_yield_change:+.2f} pp, while "
        f"average deposit cost moved by {deposit_cost_change:+.2f} pp. "
        f"Monthly NII changed by {format_eur_millions(nii_change)} to "
        f"{format_eur_millions(latest['nii'])}.\n\n"
        f"Interpretation: NIM changes when the repricing of interest-earning "
        f"assets differs from the repricing of deposits. In this synthetic "
        f"model, loan yields and deposit costs react to the ECB-rate path "
        f"at different speeds."
    )


def explain_capital(df: pd.DataFrame) -> str:
    """Explain latest CET1 and RWA development."""
    latest = df.iloc[-1]
    previous = df.iloc[-2]

    cet1_change = latest["cet1_ratio_pct"] - previous["cet1_ratio_pct"]
    capital_change = latest["cet1_capital"] - previous["cet1_capital"]
    rwa_change = latest["rwa"] - previous["rwa"]

    return (
        f"**Capital analysis**\n\n"
        f"CET1 is {latest['cet1_ratio_pct']:.2f}%, "
        f"{cet1_change:+.2f} pp month-on-month. CET1 capital changed by "
        f"{format_eur_millions(capital_change)}, while RWA changed by "
        f"{format_eur_millions(rwa_change)}.\n\n"
        f"Because CET1 ratio equals CET1 capital divided by RWA, the ratio "
        f"improves when retained earnings increase capital faster than RWA "
        f"grows; it declines when impairments reduce capital or credit-risk "
        f"deterioration increases RWA."
    )


def explain_liquidity(df: pd.DataFrame) -> str:
    """Explain LCR and deposit movement."""
    latest = df.iloc[-1]
    previous = df.iloc[-2]

    lcr_change = latest["lcr_pct"] - previous["lcr_pct"]
    hqla_change = latest["hqla"] - previous["hqla"]
    outflow_change = (
        latest["net_cash_outflows"] - previous["net_cash_outflows"]
    )

    return (
        f"**Liquidity analysis**\n\n"
        f"LCR is {latest['lcr_pct']:.0f}%, a change of {lcr_change:+.0f} pp. "
        f"HQLA changed by {format_eur_millions(hqla_change)}, while estimated "
        f"net stressed cash outflows changed by {format_eur_millions(outflow_change)}. "
        f"Deposits moved by {format_eur_millions(latest['deposit_movement'])} "
        f"in the latest month.\n\n"
        f"In this prototype, LCR is calculated as HQLA divided by net stressed "
        f"cash outflows. A deposit outflow can reduce available liquidity and "
        f"increase projected stressed outflows."
    )


def recommend_actions(df: pd.DataFrame) -> str:
    """Return three controlled, non-executing CFO recommendations."""
    latest = df.iloc[-1]
    recommendations = []

    if latest["cet1_ratio_pct"] < 14.5:
        recommendations.append(
            "1. **Protect capital:** review dividend, buyback and RWA-intensive "
            "growth plans; assess capital-light origination or risk-transfer options."
        )

    if latest["lcr_pct"] < 130 or latest["deposit_movement"] < 0:
        recommendations.append(
            "2. **Protect liquidity:** investigate the deposit outflow by segment, "
            "increase monitoring of concentrated balances, and evaluate HQLA or "
            "term-funding contingency options."
        )

    if latest["nim_pct"] < 2.0:
        recommendations.append(
            "3. **Stabilise earnings:** assess deposit-pricing discipline, asset "
            "repricing opportunities, and ALM hedging sensitivity to further rate cuts."
        )

    if latest["stage_3_ratio_pct"] > 2.5:
        recommendations.append(
            "4. **Contain credit deterioration:** review high-risk portfolios, "
            "Stage 2 migration, collateral coverage and early-warning watchlists."
        )

    if latest["cost_to_income_pct"] > 60:
        recommendations.append(
            "5. **Improve efficiency:** prioritise discretionary-cost controls and "
            "automation initiatives with measurable cost-to-income benefits."
        )

    if not recommendations:
        recommendations = [
            "1. **Maintain capital discipline:** monitor RWA density and ensure "
            "loan growth remains aligned with the capital plan.",
            "2. **Preserve liquidity resilience:** monitor deposit concentration, "
            "outflows and HQLA composition.",
            "3. **Protect NIM:** monitor deposit beta, loan repricing and "
            "interest-rate sensitivity under further ECB cuts.",
        ]

    return (
        "**Recommended management actions**\n\n"
        + "\n\n".join(recommendations[:3])
        + "\n\n*These are decision-support recommendations only. "
        "They do not execute any banking action.*"
    )


def extract_rate_shock_bps(question: str) -> int | None:
    """
    Extract phrases such as '50 bps rate cut' or '100bp hike'.
    A cut becomes negative; a hike/increase becomes positive.
    """
    match = re.search(
        r"(\d+)\s*(?:bp|bps|basis\s*points?)",
        question.lower(),
    )

    if not match:
        return None

    shock = int(match.group(1))
    lower_question = question.lower()

    if any(word in lower_question for word in ["cut", "decrease", "drop", "lower"]):
        return -shock

    return shock


def answer_question(question: str, df: pd.DataFrame) -> str:
    """
    Route natural-language questions to controlled analytical functions.

    This is intentionally deterministic: every reported number is derived
    from the current synthetic dashboard data or scenario output.
    """
    lower_question = question.lower()
    rate_shock_bps = extract_rate_shock_bps(question)

    if rate_shock_bps is not None:
        scenario = run_scenario(
            history=df,
            rate_shock_bps=rate_shock_bps,
            deposit_outflow_pct=0.0,
            stage_2_increase_pct_points=0.0,
            stage_3_increase_pct_points=0.0,
        )

        baseline = scenario.loc["Baseline"]
        stressed = scenario.loc["Scenario"]

        direction = "cut" if rate_shock_bps < 0 else "increase"

        return (
            f"**Rate-shock simulation: {abs(rate_shock_bps)} bps {direction}**\n\n"
            f"| Metric | Baseline | Scenario | Change |\n"
            f"|---|---:|---:|---:|\n"
            f"| NIM | {baseline['nim_pct']:.2f}% | {stressed['nim_pct']:.2f}% | "
            f"{stressed['nim_pct'] - baseline['nim_pct']:+.2f} pp |\n"
            f"| CET1 ratio | {baseline['cet1_ratio_pct']:.2f}% | "
            f"{stressed['cet1_ratio_pct']:.2f}% | "
            f"{stressed['cet1_ratio_pct'] - baseline['cet1_ratio_pct']:+.2f} pp |\n"
            f"| LCR | {baseline['lcr_pct']:.0f}% | {stressed['lcr_pct']:.0f}% | "
            f"{stressed['lcr_pct'] - baseline['lcr_pct']:+.0f} pp |\n\n"
            f"Interpretation: the model applies differentiated asset and deposit "
            f"repricing and recalculates NII/NIM. It is an illustrative ALM "
            f"sensitivity, not a production IRRBB calculation."
        )

    if any(term in lower_question for term in ["briefing", "summary", "morning"]):
        return build_morning_briefing(df)

    if any(term in lower_question for term in ["nim", "net interest", "interest margin"]):
        return explain_nim(df)

    if any(term in lower_question for term in ["cet1", "capital", "rwa"]):
        return explain_capital(df)

    if any(term in lower_question for term in ["lcr", "liquidity", "deposit"]):
        return explain_liquidity(df)

    if any(
        term in lower_question
        for term in ["recommend", "action", "do", "next step", "red flag"]
    ):
        return recommend_actions(df)

    return (
        "I can help with the current synthetic bank data. Try one of these:\n\n"
        "- `Give me the morning briefing`\n"
        "- `Why did NIM change?`\n"
        "- `Explain the CET1 ratio and RWA movement`\n"
        "- `Assess liquidity and deposit movements`\n"
        "- `Simulate a further 50 bps rate cut`\n"
        "- `What actions do you recommend?`"
    )