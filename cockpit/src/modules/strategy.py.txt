"""Opportunity — opportunity radar and capability-gap intelligence."""

import html

import streamlit as st

from src import charts
from src.hud import (
    clip_ui_text,
    explained_metric_card,
    metric_row,
    render_html,
    safe_float,
)
from src.rag import confidence_badge


def _ranking_table(radar):
    """The top of the ranking with every scoring dimension, highest first."""
    display = radar[
        [
            "opportunity_rank",
            "company_name",
            "capability_domain",
            "strategic_fit_score",
            "financial_attractiveness_score",
            "integration_feasibility_score",
            "affordability_score",
            "time_to_value_score",
            "overall_opportunity_score",
        ]
    ].head(7).copy()
    display.columns = [
        "Rank",
        "Company",
        "Capability",
        "Strategic fit",
        "Financial attractiveness",
        "Integration",
        "Affordability",
        "Time to value",
        "Overall score",
    ]
    st.dataframe(display, hide_index=True)


def render_strategy(s):
    escape = html.escape

    render_html(
        """
        <div class="section-title">Opportunity Radar</div>
        <div class="section-subtitle">
            Public company facts are separated from synthetic management
            assessments. Strategic fit, attractiveness and capability scores are
            prototype decision-support inputs — not claims that a company is for
            sale, nor transaction recommendations.
        </div>
        """
    )

    top = s.top_strategy
    second = s.second_strategy

    if top is None:
        st.caption("No strategic radar data available.")
        return

    _ranking_table(s.strategic_radar)

    top_name = escape(str(top["company_name"]))
    top_score = safe_float(top["overall_opportunity_score"])
    runner_up = (
        f" against #2 {escape(str(second['company_name']))} at "
        f"{safe_float(second['overall_opportunity_score']):.1f}"
        if second is not None
        else ""
    )

    gap = s.top_capability_gap
    gap_name = escape(str(gap["capability"])) if gap is not None else "—"
    gap_value = safe_float(gap["capability_gap"]) if gap is not None else 0.0
    if gap is not None:
        gap_why = (
            f"{gap_name} is assessed at {safe_float(gap['current_score']):.0f} against a "
            f"target of {safe_float(gap['target_score']):.0f} — the widest "
            "current-to-target gap in the capability map."
        )
        gap_impact = escape(clip_ui_text(gap["strategic_objective"], 160))
        gap_next = (
            f"Screen the linked companies — {escape(str(gap['linked_companies']))} — "
            "against the ranking above."
        )
    else:
        gap_why = "No capability gap is recorded in the capability map."
        gap_impact = "Nothing to close on the current assessment."
        gap_next = "Re-run the assessment when the capability map is refreshed."

    render_html(
        metric_row(
            [
                explained_metric_card(
                    "TOP OPPORTUNITY",
                    top_name,
                    f"rank #{int(top['opportunity_rank'])} · {top_score:.1f}/100",
                    s.ratings["strategy_top"],
                    why=(
                        f"Scores {top_score:.1f}/100 on the full seven-factor "
                        f"composite{runner_up}, not just the two map axes."
                    ),
                    impact=escape(clip_ui_text(top["strategic_gap_addressed"], 160)),
                    next_step=(
                        f"Route: {escape(str(top['preferred_route']))}. Key risk: "
                        f"{escape(clip_ui_text(top['key_risk'], 120))}"
                    ),
                    confidence=s.conf_strategy_rank,
                    value_class="kpi-value-name",
                ),
                explained_metric_card(
                    "STRATEGIC FIT",
                    f"{safe_float(top['strategic_fit_score']):.0f}",
                    "synthetic management score",
                    s.ratings["strategy_fit"],
                    why=(
                        f"Synthetic management score for how closely {top_name} "
                        "matches the bank's strategic priorities."
                    ),
                    impact=(
                        "Fit carries 30% of the composite score and, with financial "
                        "attractiveness, forms the two axes of the opportunity map."
                    ),
                    next_step=(
                        "Weigh it against integration, affordability and time to "
                        "value in the ranking table above."
                    ),
                ),
                explained_metric_card(
                    "LARGEST CAPABILITY GAP",
                    gap_name,
                    f"gap {gap_value:.0f} points",
                    s.ratings["strategy_gap"],
                    why=gap_why,
                    impact=gap_impact,
                    next_step=gap_next,
                    value_class="kpi-value-name",
                ),
            ]
        )
    )

    if second is not None:
        pills = "".join(
            f'<span class="strategy-delta-pill">{escape(item)}</span>'
            for item in s.strategy_advantage_pills
        )
        render_html(
            f"""
            <div class="strategy-explainer">
                <div class="strategy-explainer-grid">
                    <div>
                        <div class="module-code">Why rank #1?</div>
                        <div class="strategy-score-bridge">
                            {top_name} <span>{top_score:.1f}</span>
                            vs {escape(str(second['company_name']))} {safe_float(second['overall_opportunity_score']):.1f}
                        </div>
                        {confidence_badge(s.conf_strategy_rank, with_basis=True)}
                    </div>
                    <div class="strategy-explainer-copy">
                        The opportunity map below shows only <strong>strategic fit</strong> and
                        <strong>financial attractiveness</strong>, which together represent 45% of the
                        composite score. The rank uses seven weighted dimensions, so the leader can
                        give up points on the two map axes and still rank first through integration
                        feasibility, affordability and time to value.
                        <div class="strategy-delta-strip">{pills}</div>
                    </div>
                </div>
            </div>
            """
        )

    render_html(
        f"""
        <div class="decision-strip">
            <div class="decision-strip-item">
                <span class="flow-label">Why #1</span>
                <strong>{top_name} / {top_score:.1f}</strong>
                <span>Full seven-factor composite, not just the two map axes.</span>
            </div>
            <div class="decision-strip-item">
                <span class="flow-label">Impact</span>
                <strong>{escape(clip_ui_text(top['strategic_gap_addressed'], 72))}</strong>
                <span>{escape(clip_ui_text(top['strategic_rationale'], 110))}</span>
            </div>
            <div class="decision-strip-item">
                <span class="flow-label">Route</span>
                <strong>{escape(str(top['preferred_route']))}</strong>
                <span>Prototype management route, not a statement that the company is for sale.</span>
            </div>
            <div class="decision-strip-item">
                <span class="flow-label">Key risk</span>
                <strong>{escape(clip_ui_text(top['key_risk'], 78))}</strong>
                <span>Read alongside affordability, integration and regulatory complexity.</span>
            </div>
        </div>
        """
    )

    left, right = st.columns([1.35, 1])

    with left:
        render_html(
            """<div class="module-code">Opportunity matrix / 2 of 7 scoring dimensions</div>
            <div class="section-title">Strategic opportunity map</div>
            <div class="section-subtitle">
                X/Y show fit and financial attractiveness. Bubble size represents
                the full seven-factor composite score used for ranking.
            </div>"""
        )
        st.altair_chart(
            charts.build_strategy_radar_chart(s.strategic_radar, height=410),
            use_container_width=True,
        )

    with right:
        render_html(
            """<div class="module-code">Composite bridge / #1 vs #2</div>
            <div class="section-title">What drives the ranking?</div>"""
        )
        if second is not None and not s.strategy_delta.empty:
            st.altair_chart(
                charts.build_strategy_delta_chart(
                    s.strategy_delta,
                    str(top["company_name"]),
                    str(second["company_name"]),
                    height=250,
                ),
                use_container_width=True,
            )

        render_html(
            """<div class="module-code" style="margin-top:0.8rem;">Current-to-target gap</div>
            <div class="section-title">Capability gaps</div>"""
        )
        st.altair_chart(
            charts.build_capability_gap_chart(s.capability_gaps, height=245),
            use_container_width=True,
        )
