"""What-If Engine — governed balance-sheet shock simulation."""

import pandas as pd
import streamlit as st

from src import charts
from src.engines import BETA_UNCERTAINTY_PP, calculate_scenario, scenario_beta_range
from src.hud import investigate_url, metric_card, module_url, render_html
from src.news_partner import signal_to_scenario_kwargs
from src.rag import HIGH, confidence_badge, confidence_fixed, confidence_within, rag

DEFAULT_INPUTS = {
    "ecb": -50,
    "deposit": 0.0,
    "horizon": 365,
    "loan_beta": 35,
    "deposit_beta": 55,
    "replacement_rate": 3.25,
}

METHOD_CAPTION = (
    "Prototype deterministic scenario: the current NIM, balances and rates are "
    "the anchor. Loan and deposit pass-through, replacement funding and the "
    "deposit shock are explicit assumptions. Confidence re-runs the scenario "
    f"with both pass-through betas ±{BETA_UNCERTAINTY_PP:.0f}pp and reads the spread "
    "of outcomes as a 90% range. The next production step is to move this "
    "calculation upstream into a governed scenario layer."
)

# What still counts as "the same answer" for each output.
NIM_TOLERANCE_BPS = 5.0
NII_TOLERANCE_M = 50.0


def _range_confidence(value_range, tolerance, tolerance_text):
    """Confidence from the beta sweep: the range is read as a 90% interval."""
    low, high = value_range
    sigma = (high - low) / 2.0 / 1.645
    reading = confidence_within(sigma, tolerance, tolerance_text)
    reading["basis"] += f" (pass-through range {low:+,.1f} to {high:+,.1f})"
    return reading


def _signal_apply_panel():
    from src.modules.news import load_extracted_signals  # deferred — avoids brief→news→scenario→news cycle
    try:
        signals = load_extracted_signals()
    except Exception:
        return
    actionable = [s for s in signals if s.get("engine_param") in (
        "rate_shock_bps", "deposit_outflow_pct",
    )]
    if not actionable:
        return

    render_html("""<div class="module-code" style="margin-top:1rem;">Overnight news signals</div>""")
    applied = st.session_state.get("applied_signal")
    for i, sig in enumerate(actionable):
        article = sig.get("_article", {})
        entity = sig.get("entity") or "Signal"
        quote = sig.get("quote") or ""
        source = article.get("source", "")
        is_active = applied is not None and applied is sig
        label = f"{entity} — *\"{quote}\"*" + (f" ({source})" if source else "")
        col_text, col_btn = st.columns([4, 1])
        with col_text:
            st.markdown(label)
        with col_btn:
            btn_label = "Applied" if is_active else "Apply"
            if st.button(btn_label, key=f"scenario_apply_{i}", disabled=is_active):
                kwargs = signal_to_scenario_kwargs(sig)
                new_inputs = dict(st.session_state.get("scenario_inputs", DEFAULT_INPUTS))
                if "rate_shock_bps" in kwargs:
                    new_inputs["ecb"] = max(-100, min(100, int(kwargs["rate_shock_bps"])))
                if "deposit_outflow_pct" in kwargs:
                    outflow = float(kwargs["deposit_outflow_pct"])
                    new_inputs["deposit"] = max(-10.0, min(5.0, -abs(outflow)))
                st.session_state["scenario_inputs"] = new_inputs
                st.session_state["applied_signal"] = sig
                st.rerun()


def _controls(s):
    """Assumption form. Returns the submitted inputs, or None if not submitted."""
    render_html("""<div class="module-code">Scenario assumptions</div>""")

    current = st.session_state.get("scenario_inputs", DEFAULT_INPUTS)

    with st.form("scenario_form"):
        ecb_shock = st.slider(
            "ECB rate shock",
            min_value=-100,
            max_value=100,
            value=current["ecb"],
            step=5,
            format="%d bps",
        )
        deposit_shock = st.slider(
            "Deposit balance shock",
            min_value=-10.0,
            max_value=5.0,
            value=current["deposit"],
            step=0.5,
            format="%.1f%%",
        )
        horizon_days = st.slider(
            "Scenario horizon",
            min_value=30,
            max_value=365,
            value=current["horizon"],
            step=5,
            format="%d days",
        )

        with st.expander("Advanced repricing assumptions", expanded=False):
            loan_beta = st.slider(
                "Loan pass-through to ECB shock",
                min_value=0,
                max_value=100,
                value=current["loan_beta"],
                step=5,
                format="%d%%",
            )
            deposit_beta = st.slider(
                "Deposit pass-through to ECB shock",
                min_value=0,
                max_value=100,
                value=current["deposit_beta"],
                step=5,
                format="%d%%",
            )
            replacement_rate = st.number_input(
                "Replacement funding rate (%)",
                min_value=0.0,
                max_value=10.0,
                value=current["replacement_rate"],
                step=0.05,
                format="%.2f",
            )

        submitted = st.form_submit_button("Run scenario")

    if st.button("Reset to defaults", key="reset_scenario"):
        st.session_state["scenario_inputs"] = dict(DEFAULT_INPUTS)
        st.session_state.pop("applied_signal", None)
        st.rerun()

    _signal_apply_panel()

    render_html(
        f"""
        <div class="forward-lens-panel" style="margin-top:.85rem;">
            <div class="forward-lens-kicker">Current anchor</div>
            <div class="forward-lens-row"><span class="forward-lens-label">NIM</span><span class="forward-lens-value"><strong>{s.cert_current_nim:.2f}%</strong></span></div>
            <div class="forward-lens-row"><span class="forward-lens-label">Loan rate</span><span class="forward-lens-value"><strong>{s.current_loan_rate_pct:.2f}%</strong></span></div>
            <div class="forward-lens-row"><span class="forward-lens-label">Deposit rate</span><span class="forward-lens-value"><strong>{s.current_deposit_rate_pct:.2f}%</strong></span></div>
            <div class="forward-lens-row"><span class="forward-lens-label">Deposits</span><span class="forward-lens-value"><strong>€{s.current_deposits_m / 1000:.1f}bn</strong></span></div>
        </div>
        """
    )

    if not submitted:
        return None

    return {
        "ecb": ecb_shock,
        "deposit": deposit_shock,
        "horizon": horizon_days,
        "loan_beta": loan_beta,
        "deposit_beta": deposit_beta,
        "replacement_rate": replacement_rate,
    }


def _decision_copy(scenario, inputs):
    """The meaning and next-step lines, keyed off the direction of the result."""
    if scenario["nim_impact_bps"] < 0:
        meaning = (
            "The selected assumptions compress margin. Review funding "
            "pass-through and deposit-volume sensitivity before accepting the "
            "outcome."
        )
    elif scenario["nim_impact_bps"] > 0:
        meaning = (
            "The selected assumptions expand margin. Check whether the assumed "
            "loan/deposit pass-through is realistic before treating the upside "
            "as actionable."
        )
    else:
        meaning = (
            "The selected assumptions leave margin broadly unchanged. The result "
            "is most sensitive to the repricing betas and any deposit outflow."
        )

    if inputs["ecb"] > 0:
        next_step = (
            "Compare the bank-margin benefit with the Treasury +50bp "
            "economic-value loss before making a rate-risk decision."
        )
    elif inputs["ecb"] < 0:
        next_step = (
            "Review how quickly asset yields reprice relative to deposit costs "
            "and whether funding growth offsets the margin pressure."
        )
    else:
        next_step = (
            "Focus on the deposit-volume shock and the replacement-funding "
            "assumption."
        )

    return meaning, next_step


def render_scenario(s):
    render_html(
        """
        <div class="section-title">What-If Engine</div>
        <div class="section-subtitle">
            Change the assumptions and quantify the effect on the NII/NIM
            baseline. The financial output is deterministic; Copilot can explain
            the result, but does not calculate it.
        </div>
        """
    )

    controls, results = st.columns([0.86, 1.55])

    with controls:
        submitted = _controls(s)

    # The last run persists across reruns, so navigating away and back does not
    # silently reset the scenario the CFO is looking at.
    if "scenario_inputs" not in st.session_state:
        st.session_state["scenario_inputs"] = dict(DEFAULT_INPUTS)

    if submitted:
        st.session_state["scenario_inputs"] = submitted

    inputs = st.session_state["scenario_inputs"]

    scenario = calculate_scenario(
        current_nim_pct=s.cert_current_nim,
        current_loans_m=s.current_loans_m,
        current_deposits_m=s.current_deposits_m,
        current_loan_rate_pct=s.current_loan_rate_pct,
        current_deposit_rate_pct=s.current_deposit_rate_pct,
        ecb_shock_bps=inputs["ecb"],
        deposit_balance_shock_pct=inputs["deposit"],
        horizon_days=inputs["horizon"],
        loan_beta_pct=inputs["loan_beta"],
        deposit_beta_pct=inputs["deposit_beta"],
        replacement_funding_rate_pct=inputs["replacement_rate"],
    )

    spread = scenario_beta_range(
        current_nim_pct=s.cert_current_nim,
        current_loans_m=s.current_loans_m,
        current_deposits_m=s.current_deposits_m,
        current_loan_rate_pct=s.current_loan_rate_pct,
        current_deposit_rate_pct=s.current_deposit_rate_pct,
        ecb_shock_bps=inputs["ecb"],
        deposit_balance_shock_pct=inputs["deposit"],
        horizon_days=inputs["horizon"],
        loan_beta_pct=inputs["loan_beta"],
        deposit_beta_pct=inputs["deposit_beta"],
        replacement_funding_rate_pct=inputs["replacement_rate"],
    )
    nii_text = f"±€{NII_TOLERANCE_M:.0f}m"
    confidence = {
        "nim": _range_confidence(
            spread["nim_impact_bps"], NIM_TOLERANCE_BPS, f"±{NIM_TOLERANCE_BPS:.0f} bps"
        ),
        "nii": _range_confidence(spread["horizon_nii_impact_m"], NII_TOLERANCE_M, nii_text),
        "loan": _range_confidence(spread["loan_repricing_impact_m"], NII_TOLERANCE_M, nii_text),
        "funding": _range_confidence(spread["funding_cost_change_m"], NII_TOLERANCE_M, nii_text),
        "annual": _range_confidence(spread["scenario_annual_nii_m"], NII_TOLERANCE_M, nii_text),
        "replacement": confidence_fixed(
            HIGH, "Mechanical: the assumed deposit shock applied to today's balance."
        ),
    }

    anchor_nii_m = scenario["current_annual_nii_m"] or 1.0
    lost = scenario["lost_deposits_m"]
    ratings = {
        "nim": rag(scenario["nim_impact_bps"], 0.0, -10.0, unit=" bps"),
        "nii": rag(
            scenario["annual_nii_impact_m"] / anchor_nii_m * 100.0, 0.0, -2.0,
            unit="% of annual NII",
        ),
        "replacement": rag(
            lost / max(s.current_deposits_m, 1.0) * 100.0, 0.5, 3.0,
            higher_is_better=False, unit="% of deposits",
        ),
    }

    with results:
        render_html(
            """<div class="module-code">Scenario result</div>
            <div class="section-title">What changes?</div>"""
        )

        cards = [
            metric_card(
                "NIM IMPACT",
                f"{scenario['nim_impact_bps']:+.1f} bps",
                f"{scenario['current_nim_pct']:.2f}% → {scenario['scenario_nim_pct']:.2f}%",
                ratings["nim"],
                confidence["nim"],
                detail_class="executive-delta",
            ),
            metric_card(
                "NII IMPACT / HORIZON",
                f"€{scenario['horizon_nii_impact_m']:+,.0f}m",
                f"{inputs['horizon']} day impact",
                ratings["nii"],
                confidence["nii"],
                detail_class="executive-delta",
            ),
            metric_card(
                "REPLACEMENT FUNDING",
                f"€{lost / 1000:.2f}bn",
                f"{inputs['deposit']:+.1f}% deposit shock",
                ratings["replacement"],
                confidence["replacement"],
                detail_class="executive-delta",
            ),
        ]

        for column, card in zip(st.columns(3), cards):
            with column:
                render_html(card)

        render_html(
            f"""
            <div class="scenario-impact-grid">
                <div class="scenario-impact-cell">
                    <div class="scenario-impact-label">Loan repricing</div>
                    <div class="scenario-impact-value">€{scenario['loan_repricing_impact_m']:+,.0f}m / yr</div>
                    <div class="scenario-impact-copy">{scenario['current_loan_rate_pct']:.2f}% → {scenario['scenario_loan_rate_pct']:.2f}%</div>
                    {confidence_badge(confidence["loan"])}
                </div>
                <div class="scenario-impact-cell">
                    <div class="scenario-impact-label">Funding-cost change</div>
                    <div class="scenario-impact-value">€{scenario['funding_cost_change_m']:+,.0f}m / yr</div>
                    <div class="scenario-impact-copy">Deposit rate {scenario['current_deposit_rate_pct']:.2f}% → {scenario['scenario_deposit_rate_pct']:.2f}%</div>
                    {confidence_badge(confidence["funding"])}
                </div>
                <div class="scenario-impact-cell">
                    <div class="scenario-impact-label">Annualised NII</div>
                    <div class="scenario-impact-value">€{scenario['scenario_annual_nii_m'] / 1000:.2f}bn</div>
                    <div class="scenario-impact-copy">vs €{scenario['current_annual_nii_m'] / 1000:.2f}bn anchor run-rate</div>
                    {confidence_badge(confidence["annual"])}
                </div>
            </div>
            """
        )

        comparison = pd.DataFrame(
            [
                {"metric": "NIM (%)", "series": "Current", "value": scenario["current_nim_pct"]},
                {"metric": "NIM (%)", "series": "Scenario", "value": scenario["scenario_nim_pct"]},
                {"metric": "Loan rate (%)", "series": "Current", "value": scenario["current_loan_rate_pct"]},
                {"metric": "Loan rate (%)", "series": "Scenario", "value": scenario["scenario_loan_rate_pct"]},
                {"metric": "Deposit rate (%)", "series": "Current", "value": scenario["current_deposit_rate_pct"]},
                {"metric": "Deposit rate (%)", "series": "Scenario", "value": scenario["scenario_deposit_rate_pct"]},
            ]
        )
        st.altair_chart(
            charts.build_scenario_comparison_chart(comparison, height=230),
            use_container_width=True,
        )

        meaning, next_step = _decision_copy(scenario, inputs)

        render_html(
            f"""
            <div class="scenario-decision-card">
                <div class="scenario-decision-line"><span>Change</span><span>ECB {inputs['ecb']:+.0f} bps · deposits {inputs['deposit']:+.1f}% · {inputs['horizon']} days.</span></div>
                <div class="scenario-decision-line"><span>Impact</span><span>NIM {scenario['nim_impact_bps']:+.1f} bps and NII €{scenario['horizon_nii_impact_m']:+,.0f}m over the selected horizon.</span></div>
                <div class="scenario-decision-line"><span>Confidence</span><span>{confidence_badge(confidence["nim"])} {confidence["nim"]["basis"]}.</span></div>
                <div class="scenario-decision-line"><span>Meaning</span><span>{meaning}</span></div>
                <div class="scenario-decision-line"><span>Next</span><span>{next_step}</span></div>
            </div>
            """
        )

        render_html(
            f"""
            <div class="module-action-row">
                <a class="module-action-link" href="{investigate_url('scenario')}" target="_self">
                    Ask Copilot to interpret →
                </a>
                <a class="module-action-link" href="{module_url('treasury')}" target="_self">
                    Compare with Treasury →
                </a>
            </div>
            """
        )

        st.caption(METHOD_CAPTION)
