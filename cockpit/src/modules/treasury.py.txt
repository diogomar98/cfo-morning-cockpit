"""Treasury — portfolio sensitivity, scenarios and hedge alternatives."""

import html

import streamlit as st

from src import charts
from src.cockpit_views import load_treasury_portfolio
from src.hud import explained_metric_card, metric_row, render_html, safe_float
from src.rag import confidence_badge, confidence_label


def render_treasury(s):
    render_html(
        """
        <div class="section-title">Treasury Pulse</div>
        <div class="section-subtitle">
            Portfolio sensitivity, predefined market-risk scenarios and
            deterministic hedge alternatives. Economic value, OCI and immediate
            P&amp;L remain explicitly separated.
        </div>
        """
    )

    hedge = s.strongest_hedge
    hedge_name = (
        html.escape(str(hedge["hedge_name"]))
        if hedge is not None
        else "No predefined hedge available"
    )
    hedge_reduction = safe_float(hedge["dv01_reduction_pct"]) if hedge is not None else 0.0
    hedge_carry = (
        safe_float(hedge["estimated_annual_carry_m"]) if hedge is not None else 0.0
    )

    if s.treasury_market_change_m is not None:
        change_copy = (
            f"Market value {s.treasury_market_trend_text} "
            f"({s.treasury_market_trend_label})."
        )
        change_next = "Compare the move with the market-risk scenarios below."
    else:
        change_copy = (
            "No prior treasury snapshot is available, so day-over-day "
            "market-value change cannot yet be measured."
        )
        change_next = "Trend appears automatically once a prior snapshot exists."

    hedge_option = (
        f"Largest predefined DV01 reduction: {hedge_name} — {hedge_reduction:.0f}% · "
        f"carry €{hedge_carry:+,.0f}m/year. Prototype option, not a trading "
        "recommendation."
    )

    ratings = s.ratings
    render_html(
        metric_row(
            [
                explained_metric_card(
                    "MARKET VALUE",
                    f"€{s.treasury_market_value_m / 1000:.1f}bn",
                    f"unrealised P&amp;L €{s.treasury_unrealised_pnl_m:+,.0f}m",
                    ratings["treasury_value"],
                    why=change_copy,
                    impact=(
                        f"Unrealised P&amp;L of €{s.treasury_unrealised_pnl_m:+,.0f}m "
                        "on the current portfolio marks."
                    ),
                    next_step=change_next,
                ),
                explained_metric_card(
                    "PORTFOLIO DV01",
                    f"€{s.treasury_dv01:.1f}m",
                    "per 1 bp parallel rate move",
                    ratings["treasury_dv01"],
                    why=(
                        f"Each 1bp parallel rate move changes economic value by "
                        f"about €{s.treasury_dv01:.1f}m."
                    ),
                    impact=(
                        "The sensitivity that explains why parallel rate moves "
                        "affect economic value."
                    ),
                    next_step=hedge_option,
                ),
                explained_metric_card(
                    "MODIFIED DURATION",
                    f"{s.treasury_duration:.2f}y",
                    "market-value weighted",
                    ratings["treasury_duration"],
                    why=f"Market-value-weighted modified duration of {s.treasury_duration:.2f}y.",
                    impact=(
                        "The longer the duration, the larger the economic-value swing "
                        "for the same rate move."
                    ),
                    next_step="See where it sits in the DV01-by-maturity chart below.",
                ),
                explained_metric_card(
                    "RATES +50BP",
                    s.treasury_rate50_text,
                    "economic-value impact",
                    ratings["treasury_rate50"],
                    why=(
                        f"A +50bp parallel shock moves economic value by "
                        f"{s.treasury_rate50_text}, driven by DV01 €{s.treasury_dv01:.1f}m/bp."
                    ),
                    impact=(
                        "Economic-value impact; OCI and immediate P&amp;L are reported "
                        "separately in the scenarios below."
                    ),
                    next_step=hedge_option,
                    confidence=s.conf_treasury_rate50,
                ),
            ]
        )
    )

    left, right = st.columns([1.25, 1])

    with left:
        render_html(
            """<div class="module-code">Portfolio outputs</div>
            <div class="section-title">Market-risk scenarios</div>"""
        )
        st.altair_chart(
            charts.build_treasury_scenario_chart(s.treasury_scenarios, height=300),
            use_container_width=True,
        )
        st.caption(
            "Scenario outputs come straight from the treasury scenario dataset; "
            "the UI does not reprice the portfolio."
        )

        portfolio = load_treasury_portfolio()
        composition_left, composition_right = st.columns(2)
        with composition_left:
            render_html("""<div class="module-code">Market value by asset class</div>""")
            st.altair_chart(
                charts.build_treasury_asset_class_chart(portfolio, height=230),
                use_container_width=True,
            )
        with composition_right:
            render_html("""<div class="module-code">DV01 by maturity bucket</div>""")
            st.altair_chart(
                charts.build_treasury_dv01_chart(portfolio, height=230),
                use_container_width=True,
            )

    with right:
        render_html(
            """<div class="module-code">Predefined alternatives</div>
            <div class="section-title">Hedge options</div>"""
        )

        hedges = s.hedge_options
        if hedges is not None and not hedges.empty:
            best = hedges.sort_values("dv01_reduction_pct", ascending=False).iloc[0]
            render_html(
                f"""
                <div class="feature-callout">
                    <div class="feature-callout-title">Largest DV01 reduction / {html.escape(str(best['hedge_name']))}</div>
                    <div class="feature-callout-copy">
                        Indicative notional €{safe_float(best['hedge_notional_m']) / 1000:.1f}bn ·
                        DV01 reduction {safe_float(best['dv01_reduction_pct']):.0f}% ·
                        annual carry €{safe_float(best['estimated_annual_carry_m']):+,.0f}m.
                        Prototype estimate, not an executable trading recommendation.
                    </div>
                    {confidence_badge(s.conf_hedges, with_basis=True)}
                </div>
                """
            )

            display = hedges[
                [
                    "hedge_name",
                    "hedge_notional_m",
                    "dv01_reduction_pct",
                    "rates_plus_50bp_pnl_after_m",
                    "estimated_annual_carry_m",
                ]
            ].copy()
            display.columns = [
                "Hedge",
                "Notional (€m)",
                "DV01 reduction (%)",
                "+50bp impact after hedge (€m)",
                "Annual carry (€m)",
            ]
            # Every row is an estimate from the same simplified method.
            display["Confidence"] = confidence_label(s.conf_hedges)
            st.dataframe(display, hide_index=True)
        else:
            st.caption("No hedge alternatives available.")

    if s.treasury_market_change_m is None:
        st.info(
            "The treasury dataset contains a single snapshot, so a genuine "
            "day-over-day move cannot be shown yet. The cockpit is wired to "
            "display the change automatically once a previous snapshot exists."
        )
