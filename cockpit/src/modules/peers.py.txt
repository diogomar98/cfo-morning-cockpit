"""Peers — directional European peer positioning."""

import streamlit as st

from src import charts
from src.hud import explained_metric_card, metric_row, render_html


def render_peers(s):
    ratings = s.ratings
    gap_word = "below" if s.roe_peer_gap_pp < 0 else "above"
    cet1_word = "below" if s.cet1_peer_gap_pp < 0 else "above"
    efficiency_word = (
        "better"
        if s.efficiency_peer_advantage_pp > 0
        else "worse"
        if s.efficiency_peer_advantage_pp < 0
        else "in line"
    )

    render_html(
        metric_row(
            [
                explained_metric_card(
                    "OUR ROE PROXY",
                    f"{s.ytd_roe_proxy:.1f}%",
                    f"peer median {s.peer_profitability_median:.1f}% · {s.roe_peer_gap_pp:+.1f}pp",
                    ratings["peer_roe"],
                    why=(
                        f"Our annualised YTD ROE proxy sits {abs(s.roe_peer_gap_pp):.1f}pp "
                        f"{gap_word} the peer median of {s.peer_profitability_median:.1f}%."
                    ),
                    impact=(
                        "Directional only: peers report a mix of ROE, RoTE and Net "
                        "RoTE, so the gap is not fully like-for-like."
                    ),
                    next_step=(
                        "Investigate return levers — separate revenue/NII, fee income, "
                        "cost and capital-deployment drivers before drawing conclusions."
                    ),
                ),
                explained_metric_card(
                    "OUR CET1",
                    f"{s.cet1_ratio:.1f}%",
                    f"peer median {s.peer_cet1_median:.1f}% · {s.cet1_peer_gap_pp:+.1f}pp",
                    ratings["peer_cet1"],
                    why=(
                        f"CET1 sits {abs(s.cet1_peer_gap_pp):.1f}pp {cet1_word} the "
                        f"peer median of {s.peer_cet1_median:.1f}%."
                    ),
                    impact=(
                        "Capital position and reported return should be read together, "
                        "not as a one-dimensional ranking."
                    ),
                    next_step=(
                        "Read it against the ROE proxy on the position matrix below to "
                        "see whether the return gap reflects how much capital we hold."
                    ),
                ),
                explained_metric_card(
                    "OUR COST / INCOME",
                    f"{s.ytd_cost_income:.1f}%",
                    f"peer median {s.peer_cost_income_median:.1f}% · "
                    f"{s.efficiency_peer_advantage_pp:+.1f}pp advantage",
                    ratings["peer_ci"],
                    why=(
                        f"Cost/income is {abs(s.efficiency_peer_advantage_pp):.1f}pp "
                        f"{efficiency_word} than the peer median of "
                        f"{s.peer_cost_income_median:.1f}%."
                    ),
                    impact="Shows whether the return gap is accompanied by an efficiency gap.",
                    next_step=(
                        "Use the comparison set below to see which peers pair lower "
                        "cost/income with higher returns."
                    ),
                ),
            ]
        )
    )

    render_html(
        """
        <div class="section-title">Peer Benchmarking</div>
        <div class="section-subtitle">
            Directional comparison with public FY2025 peer disclosures. Peer
            profitability mixes ROE, RoTE and Net RoTE; our bank is shown using
            its annualised YTD ROE proxy, so return comparisons are not fully
            like-for-like.
        </div>
        """
    )

    left, right = st.columns([1.45, 1])

    with left:
        render_html(
            """<div class="module-code">Position matrix / Return × capital</div>
            <div class="section-title">Where do we sit?</div>"""
        )
        st.altair_chart(
            charts.build_peer_positioning_chart(s.peer_plot, height=400),
            use_container_width=True,
        )

    with right:
        render_html(
            """<div class="module-code">Peer ledger / Public disclosures</div>
            <div class="section-title">Comparison set</div>"""
        )
        peers = s.peer_benchmark
        if peers is not None and not peers.empty:
            display = peers[
                [
                    "bank_name",
                    "reported_return_pct",
                    "return_metric_type",
                    "cet1_ratio_pct",
                    "cost_income_ratio_pct",
                ]
            ].copy()
            display.columns = [
                "Bank",
                "Return (%)",
                "Metric",
                "CET1 (%)",
                "Cost / income (%)",
            ]
            st.dataframe(
                display, hide_index=True, height=410
            )
        else:
            st.caption("No peer disclosures available.")
