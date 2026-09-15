"""Horizon — the deterministic run-rate outlook."""

import streamlit as st

from src import charts
from src.cockpit_state import HORIZON_MONTHS_AHEAD
from src.engines import build_horizon_baseline
from src.hud import arrow_delta, investigate_url, metric_card, module_url, render_html
from src.rag import confidence_badge

BASELINE_CAPTION = (
    "Baseline assumptions: earning assets follow the median of the latest 3 "
    "monthly moves; deposits use the latest 30-day growth rate; 50% of the "
    "latest 30-day repricing is carried into the first projected month and that "
    "momentum halves each month thereafter. Confidence is the probability of "
    "landing within the stated tolerance, with the error growing like a random "
    "walk from the observed month-to-month moves."
)


def _legend():
    render_html(
        """
        <div class="nim-legend">
            <div class="legend-item"><span class="legend-dot legend-actual"></span>Actual</div>
            <div class="legend-item"><span class="legend-line legend-forecast"></span>Deterministic baseline</div>
            <div class="legend-item"><span class="legend-band"></span>90% band · confidence per month in the tooltip</div>
        </div>
        """
    )


def render_horizon(s):
    direction = (
        "higher"
        if s.horizon_change_bps > 0
        else "lower"
        if s.horizon_change_bps < 0
        else "flat"
    )
    repricing_direction = (
        "supports margin"
        if s.spread_30d_bps > 0
        else "pressures margin"
        if s.spread_30d_bps < 0
        else "is neutral for margin"
    )

    last_actual = s.previous_month_label
    first_projected = "Sep"
    if not s.horizon_baseline.empty:
        actual = s.horizon_baseline[s.horizon_baseline["series"] == "Actual"]
        forecast = s.horizon_baseline[s.horizon_baseline["series"] == "Baseline"]
        if not actual.empty:
            last_actual = actual.iloc[-1]["month_label"]
        if not forecast.empty:
            first_projected = forecast.iloc[0]["month_label"]
            year_end_label = forecast.iloc[-1]["month_label"]
        else:
            year_end_label = last_actual
    else:
        year_end_label = last_actual

    render_html(
        f"""
        <div class="section-title">Where are we heading?</div>
        <div class="section-subtitle">
            A transparent momentum-decay baseline projects the current operating
            run-rate through {year_end_label}. It is a mechanical reference point
            for decisions — not the bank's official plan or forecast.
        </div>
        """
    )

    ratings = s.ratings
    cards = [
        metric_card(
            f"{year_end_label.upper()} NIM BASELINE",
            f"{s.horizon_year_end_nim:.2f}%",
            f"{arrow_delta(s.horizon_change_bps, ' bps')} vs {last_actual}",
            ratings["horizon_ye_nim"],
            s.conf_horizon_ye_nim,
            detail_class="executive-delta",
        ),
        metric_card(
            "FY NII BASELINE",
            f"€{s.horizon_full_year_nii_m / 1000:.2f}bn",
            f"€{s.horizon_remaining_nii_m / 1000:.2f}bn {first_projected}-{year_end_label}",
            ratings["horizon_fy_nii"],
            s.conf_horizon_fy_nii,
            detail_class="executive-delta",
        ),
        metric_card(
            f"{first_projected.upper()} NIM STEP",
            f"{s.horizon_first_month_bps:+.1f}",
            f"bps vs {last_actual}",
            ratings["horizon_first_step"],
            s.conf_horizon_first_step,
            detail_class="executive-delta",
        ),
        metric_card(
            "BALANCE-SHEET RUN-RATE",
            f"{s.horizon_asset_growth_pct:+.2f}%",
            f"earning assets / month · deposits {s.horizon_deposit_growth_pct:+.2f}%",
            ratings["horizon_balance_sheet"],
            s.conf_horizon_balance_sheet,
            detail_class="executive-delta",
        ),
    ]

    for column, card in zip(st.columns(4), cards):
        with column:
            render_html(card)

    st.write("")
    chart_col, lens_col = st.columns([1.72, 0.9])

    with chart_col:
        render_html(
            """<div class="module-code">Forward trajectory / actual → baseline</div>
            <div class="section-title">NIM outlook</div>"""
        )
        _legend()

        shock_baseline = None
        try:
            from src.modules.news import load_extracted_signals
            rate_signals = [
                sig for sig in load_extracted_signals()
                if sig.get("engine_param") == "rate_shock_bps"
            ]
        except Exception:
            rate_signals = []

        if rate_signals:
            options = {
                f"{sig.get('entity', 'Signal')} {'+' if (sig.get('value') or 0) > 0 else ''}{int(sig.get('value') or 0)} bps"
                f" ({(sig.get('_article') or {}).get('source', '')})"
                : sig
                for sig in rate_signals
            }
            selected_label = st.selectbox(
                "Apply news signal to forecast",
                list(options.keys()),
                index=None,
                placeholder="Select a rate signal to overlay…",
                key="horizon_signal_select",
            )
            if selected_label:
                sig = options[selected_label]
                shock_bps = int(sig.get("value") or 0)
                loan_beta, deposit_beta = 0.35, 0.55
                shock_baseline, _ = build_horizon_baseline(
                    s.monthly_nim,
                    months_ahead=HORIZON_MONTHS_AHEAD,
                    current_loans_m=s.current_loans_m,
                    current_deposits_m=s.current_deposits_m,
                    current_loan_rate_pct=s.current_loan_rate_pct + shock_bps / 100.0 * loan_beta,
                    current_deposit_rate_pct=s.current_deposit_rate_pct + shock_bps / 100.0 * deposit_beta,
                    loan_rate_30d_bps=s.loan_rate_30d_bps + shock_bps,
                    deposit_rate_30d_bps=s.deposit_rate_30d_bps + shock_bps * deposit_beta,
                    deposit_growth_30d_pct=s.total_deposit_30d_change_pct,
                )

        st.altair_chart(
            charts.build_horizon_outlook_chart(s.horizon_baseline, height=355, shock_baseline=shock_baseline),
            use_container_width=True,
        )
        st.caption(BASELINE_CAPTION)

    with lens_col:
        render_html(
            f"""
            <div class="forward-lens-panel">
                <div class="forward-lens-kicker">Forward lens</div>
                <div class="forward-lens-title">What is the baseline telling us?</div>

                <div class="forward-lens-row">
                    <span class="forward-lens-label">Repricing</span>
                    <span class="forward-lens-value">
                        Loan yield moved <strong>{s.loan_rate_30d_bps:+.1f} bps</strong> and
                        deposit cost <strong>{s.deposit_rate_30d_bps:+.1f} bps</strong> over 30D.
                        The net pricing spread move of <strong>{s.spread_30d_bps:+.1f} bps</strong>
                        currently {repricing_direction}.
                    </span>
                </div>

                <div class="forward-lens-row">
                    <span class="forward-lens-label">Funding</span>
                    <span class="forward-lens-value">
                        Deposits are running at <strong>{s.horizon_deposit_growth_pct:+.2f}%</strong>
                        per month in the baseline, anchored to the latest 30D move.
                    </span>
                </div>

                <div class="forward-lens-row">
                    <span class="forward-lens-label">Outcome</span>
                    <span class="forward-lens-value">
                        If those observed trends continue but repricing momentum fades,
                        {year_end_label} NIM lands at <strong>{s.horizon_year_end_nim:.2f}%</strong> —
                        <strong>{abs(s.horizon_change_bps):.1f} bps {direction}</strong>
                        than {last_actual}.
                    </span>
                </div>

                <div class="forward-lens-row">
                    <span class="forward-lens-label">Confidence</span>
                    <span class="forward-lens-value">
                        {confidence_badge(s.conf_horizon_ye_nim)}
                        NIM has moved about <strong>{s.nim_sigma_bps:.0f} bps</strong> month to
                        month this year, so a {year_end_label} landing within
                        ±10 bps of the baseline is far from certain; the FY NII figure is
                        firmer because most of the year is already booked.
                    </span>
                </div>

                <div class="forward-lens-row">
                    <span class="forward-lens-label">Plan gap</span>
                    <span class="forward-lens-value">
                        The official budget/planning comparator is not part of this
                        dataset, so this view should not be read as "ahead/behind plan".
                    </span>
                </div>

                <div class="forward-lens-meaning">
                    <strong>How to use it</strong>
                    Treat this as the no-new-action reference case. The useful question is not
                    whether {s.horizon_year_end_nim:.2f}% is "the forecast", but which assumption
                    would move it most — rates, deposit pricing, funding volume or asset growth.
                </div>
            </div>
            """
        )

    render_html(
        f"""
        <div class="module-action-row">
            <a class="module-action-link" href="{module_url('scenario')}" target="_self">
                Stress key assumptions →
            </a>
            <a class="module-action-link" href="{investigate_url('horizon')}" target="_self">
                Ask Copilot about the outlook →
            </a>
        </div>
        """
    )
