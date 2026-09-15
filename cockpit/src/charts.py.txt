"""
Altair chart builders, themed to the HUD.

Every chart shares one visual contract: a transparent view (the CSS paints the
panel behind it), Cascadia Mono axis labels in muted slate, faint green grid
lines, and the cockpit's four accent colours for series. The helpers at the top
express that contract once so each builder stays about its data.
"""

import altair as alt
import pandas as pd

# HUD palette. Green is the primary series, violet the counterfactual or
# comparison series, amber and pale mint the remaining accents. Mint sits last
# so it only appears on four-series charts, where its lightness separates it
# from the primary green.
ACCENT = "#13AC33"
VIOLET = "#B88CFF"
MINT = "#CCEAD6"
AMBER = "#FFCB66"
RED = "#FF5D7A"
INK = "#E6F5E9"

AXIS_LABEL = "#759D7F"
AXIS_VALUE = "#C2D2C6"
GRID = "#19201B"
DOMAIN = "#1F2721"
MONO = "Cascadia Mono"


def _quant_axis(title, **overrides):
    """A quantitative axis in the HUD idiom."""
    options = dict(
        labelColor=AXIS_LABEL,
        titleColor=AXIS_LABEL,
        gridColor=GRID,
        gridOpacity=0.55,
        domain=False,
    )
    options.update(overrides)
    return alt.Axis(**options), title


def _quant(field, title, **overrides):
    axis, title = _quant_axis(title, **overrides)
    return alt.X(field, title=title, axis=axis)


def _category_axis():
    """A nominal axis for horizontal bar charts."""
    return alt.Axis(labelColor=AXIS_VALUE, domain=False, ticks=False)


def _month_axis():
    """The shared ordinal month axis used by the NIM and Horizon charts."""
    return alt.Axis(
        labelAngle=0,
        grid=False,
        labelColor=AXIS_LABEL,
        labelFont=MONO,
        labelFontSize=11,
        labelPadding=10,
        domainColor=DOMAIN,
        tickColor=DOMAIN,
    )


def _percent_axis(fmt=".2f"):
    return alt.Axis(
        format=fmt,
        tickCount=5,
        labelColor=AXIS_LABEL,
        labelFont=MONO,
        labelFontSize=11,
        titleColor=AXIS_LABEL,
        titleFont=MONO,
        titleFontSize=10,
        grid=True,
        gridColor=GRID,
        gridOpacity=0.72,
        domain=False,
        ticks=False,
    )


def _padded_domain(series, minimum_spread=0.04, padding_ratio=0.22):
    """
    A y-domain that expands a narrow series to fill the panel.

    A percentage series that only moves within a few basis points would render
    as a flat line against a zero-anchored scale, so the domain is fitted to the
    data and padded rather than zeroed.
    """
    low, high = float(series.min()), float(series.max())
    spread = max(high - low, minimum_spread)
    padding = spread * padding_ratio
    return alt.Scale(domain=[low - padding, high + padding], zero=False, nice=False)


def _finish(chart, height):
    return chart.properties(height=height).configure_view(
        stroke=None, fill="transparent"
    )


def _empty(columns, mark="line"):
    """A placeholder with the same shape, so a missing dataset renders blank."""
    base = alt.Chart(pd.DataFrame({c: [] for c in columns}))
    return getattr(base, f"mark_{mark}")()


# ------------------------------------------------------------------
# Morning brief
# ------------------------------------------------------------------

def build_nim_chart(monthly_nim, height=300):
    """
    The certified monthly NIM path.

    Drawn as a line rather than an area: an area mark introduces a zero
    baseline, which visually flattens a series that lives around 1.6%.
    """
    if monthly_nim is None or monthly_nim.empty:
        return _empty(["month_label", "nim_pct"])

    chart_df = monthly_nim.dropna(subset=["nim_pct"]).copy()
    if chart_df.empty:
        return _empty(["month_label", "nim_pct"])

    chart_df = chart_df.sort_values("month").reset_index(drop=True)
    chart_df["month_label"] = pd.to_datetime(chart_df["month"]).dt.strftime("%b")

    base = alt.Chart(chart_df).encode(
        x=alt.X(
            "month_label:O",
            sort=chart_df["month_label"].tolist(),
            title=None,
            axis=_month_axis(),
        ),
        y=alt.Y(
            "nim_pct:Q",
            title="Certified NIM (%)",
            scale=_padded_domain(chart_df["nim_pct"]),
            axis=_percent_axis(),
        ),
        tooltip=[
            alt.Tooltip("month:T", title="Month", format="%B %Y"),
            alt.Tooltip("nim_pct:Q", title="NIM", format=".3f"),
        ],
    )

    line = base.mark_line(strokeWidth=3, color=ACCENT, interpolate="linear")
    points = base.mark_circle(size=58, color=ACCENT, stroke=INK, strokeWidth=1.2)

    return _finish(line + points, height)


def build_deposit_country_chart(deposit_country, height=245):
    """30-day deposit change by country."""
    if deposit_country is None or deposit_country.empty:
        return _empty(["country", "deposit_change_30d_pct"], mark="bar")

    chart_df = deposit_country.dropna(subset=["deposit_change_30d_pct"])
    if chart_df.empty:
        return _empty(["country", "deposit_change_30d_pct"], mark="bar")

    chart = (
        alt.Chart(chart_df)
        .mark_bar(cornerRadiusEnd=3, color=ACCENT, opacity=0.78)
        .encode(
            x=_quant(
                "deposit_change_30d_pct:Q", "30-day deposit change (%)"
            ),
            y=alt.Y("country:N", title=None, sort="-x", axis=_category_axis()),
            tooltip=[
                alt.Tooltip("country:N", title="Country"),
                alt.Tooltip(
                    "deposit_change_30d_pct:Q", title="30-day change", format="+.2f"
                ),
                alt.Tooltip(
                    "deposit_balance_m:Q", title="Deposits (€m)", format=",.0f"
                ),
            ],
        )
    )

    return _finish(chart, height)


def build_credit_stage2_chart(credit_detail, height=245):
    """Stage 2 concentration by country and business line."""
    if credit_detail is None or credit_detail.empty:
        return _empty(["segment", "weighted_stage_2_share_pct"], mark="bar")

    chart_df = credit_detail.copy()
    chart_df["segment"] = (
        chart_df["country"].astype(str) + " / " + chart_df["business_line"].astype(str)
    )
    chart_df = chart_df.nlargest(8, "weighted_stage_2_share_pct")

    chart = (
        alt.Chart(chart_df)
        .mark_bar(cornerRadiusEnd=3, color=AMBER, opacity=0.78)
        .encode(
            x=_quant("weighted_stage_2_share_pct:Q", "Stage 2 share (%)"),
            y=alt.Y("segment:N", title=None, sort="-x", axis=_category_axis()),
            tooltip=[
                alt.Tooltip("country:N", title="Country"),
                alt.Tooltip("business_line:N", title="Business line"),
                alt.Tooltip(
                    "weighted_stage_2_share_pct:Q", title="Stage 2", format=".2f"
                ),
                alt.Tooltip(
                    "weighted_stage_3_share_pct:Q", title="Stage 3", format=".2f"
                ),
                alt.Tooltip("loan_balance_m:Q", title="Loans (€m)", format=",.0f"),
            ],
        )
    )

    return _finish(chart, height)


# ------------------------------------------------------------------
# Capital, liquidity and earnings trends
# ------------------------------------------------------------------

def _trend_chart(history, series_spec, y_title, height, months, threshold=None):
    """
    Shared multi-series month-end trend.

    ``series_spec`` maps a history column to its display label; colours are
    assigned from the HUD accents in order.
    """
    if history is None or history.empty:
        return _empty(["date", "value"])

    frame = history.tail(months)
    palette = [ACCENT, VIOLET, AMBER, MINT]

    long = frame.melt(
        id_vars="date",
        value_vars=list(series_spec),
        var_name="metric",
        value_name="value",
    )
    long["metric"] = long["metric"].map(series_spec)

    lines = (
        alt.Chart(long)
        .mark_line(strokeWidth=2.4)
        .encode(
            x=alt.X(
                "date:T",
                title=None,
                axis=alt.Axis(
                    labelColor=AXIS_LABEL,
                    labelFont=MONO,
                    labelFontSize=10,
                    gridColor=GRID,
                    gridOpacity=0.35,
                    domainColor=DOMAIN,
                    tickColor=DOMAIN,
                    format="%b %y",
                ),
            ),
            y=alt.Y(
                "value:Q",
                title=y_title,
                scale=_padded_domain(long["value"].dropna(), minimum_spread=0.5, padding_ratio=0.12),
                axis=_percent_axis(fmt=".1f"),
            ),
            color=alt.Color(
                "metric:N",
                scale=alt.Scale(
                    domain=list(series_spec.values()),
                    range=palette[: len(series_spec)],
                ),
                legend=alt.Legend(title=None, labelColor="#95BB9E", orient="top"),
            ),
            tooltip=[
                alt.Tooltip("date:T", title="Month", format="%B %Y"),
                alt.Tooltip("metric:N", title="Metric"),
                alt.Tooltip("value:Q", title="Value", format=".2f"),
            ],
        )
    )

    if threshold is None:
        return _finish(lines, height)

    value, label = threshold
    rule = (
        alt.Chart(pd.DataFrame({"y": [value], "label": [label]}))
        .mark_rule(color=RED, strokeDash=[4, 4], opacity=0.7)
        .encode(y="y:Q", tooltip=[alt.Tooltip("label:N", title="Threshold")])
    )

    return _finish(lines + rule, height)


def build_capital_liquidity_chart(history, months=24, height=330):
    return _trend_chart(
        history,
        {
            "cet1_ratio_pct": "CET1 ratio",
            "total_capital_ratio_pct": "Total capital ratio",
            "loan_to_deposit_pct": "Loan / deposit",
        },
        "Percent",
        height,
        months,
        threshold=(13.75, "Illustrative CET1 threshold"),
    )


def build_earnings_efficiency_chart(history, months=24, height=330):
    return _trend_chart(
        history,
        {
            "cost_income_ratio_pct": "Cost / income",
            "stage_3_share_pct": "Stage 3 share",
        },
        "Percent",
        height,
        months,
    )


def build_lcr_chart(history, months=24, height=330):
    return _trend_chart(
        history,
        {"lcr_pct": "Liquidity coverage ratio"},
        "Percent",
        height,
        months,
        threshold=(100.0, "Regulatory minimum"),
    )


# ------------------------------------------------------------------
# Horizon
# ------------------------------------------------------------------

def build_horizon_outlook_chart(baseline, height=360, shock_baseline=None):
    """
    Actual NIM path handed over to the deterministic run-rate baseline.

    The last actual point is repeated as the baseline's first point so the
    handover reads as one continuous line rather than two disjoint segments.
    """
    if baseline is None or baseline.empty:
        return _empty(["month_label", "nim_pct"])

    chart_df = baseline.dropna(subset=["nim_pct"]).sort_values("month")
    chart_df = chart_df.reset_index(drop=True)
    # The baseline can run into the next year, so the month name alone would
    # put two Januaries on one ordinal slot.
    chart_df["month_label"] = pd.to_datetime(chart_df["month"]).dt.strftime("%b %y")
    month_sort = chart_df["month_label"].tolist()

    has_band = "nim_low_pct" in chart_df.columns
    band_values = (
        pd.concat([chart_df["nim_pct"], chart_df["nim_low_pct"], chart_df["nim_high_pct"]])
        .dropna()
        if has_band
        else chart_df["nim_pct"]
    )
    scale = _padded_domain(band_values, minimum_spread=0.05, padding_ratio=0.08)

    actual = chart_df[chart_df["series"] == "Actual"].copy()
    forecast = chart_df[chart_df["series"] == "Baseline"].copy()

    if not actual.empty and not forecast.empty:
        bridge = actual.tail(1).copy()
        bridge["series"] = "Baseline"
        if has_band:
            # The band opens from the last actual, where there is no error yet.
            bridge["nim_low_pct"] = bridge["nim_pct"]
            bridge["nim_high_pct"] = bridge["nim_pct"]
        forecast = pd.concat([bridge, forecast], ignore_index=True)

    x_axis = alt.X(
        "month_label:O", sort=month_sort, title=None, axis=_month_axis()
    )
    y_axis = alt.Y("nim_pct:Q", title="NIM (%)", scale=scale, axis=_percent_axis())

    actual_line = (
        alt.Chart(actual)
        .mark_line(strokeWidth=3, color=ACCENT)
        .encode(
            x=x_axis,
            y=y_axis,
            tooltip=[
                alt.Tooltip("month:T", title="Month", format="%B %Y"),
                alt.Tooltip("nim_pct:Q", title="Actual NIM", format=".3f"),
            ],
        )
    )
    actual_points = (
        alt.Chart(actual)
        .mark_circle(size=58, color=ACCENT, stroke=INK, strokeWidth=1.2)
        .encode(x=x_axis, y=y_axis)
    )

    forecast_line = (
        alt.Chart(forecast)
        .mark_line(strokeWidth=3, strokeDash=[7, 5], color=VIOLET)
        .encode(
            x=x_axis,
            y=y_axis,
            tooltip=[
                alt.Tooltip("month:T", title="Month", format="%B %Y"),
                alt.Tooltip("nim_pct:Q", title="Baseline NIM", format=".3f"),
            ],
        )
    )

    forecast_tooltip = [
        alt.Tooltip("month:T", title="Month", format="%B %Y"),
        alt.Tooltip("nim_pct:Q", title="Baseline NIM", format=".3f"),
    ]
    if has_band:
        forecast_tooltip += [
            alt.Tooltip("nim_low_pct:Q", title="90% band low", format=".3f"),
            alt.Tooltip("nim_high_pct:Q", title="90% band high", format=".3f"),
            alt.Tooltip("confidence_pct:Q", title="Confidence within ±10 bps (%)", format=".0f"),
        ]

    forecast_points = (
        alt.Chart(forecast.iloc[1:] if len(forecast) > 1 else forecast)
        .mark_circle(size=56, fill="#080c09", stroke="#C7A8FF", strokeWidth=2)
        .encode(x=x_axis, y=y_axis, tooltip=forecast_tooltip)
    )

    layers = actual_line + actual_points + forecast_line + forecast_points

    if has_band:
        band = (
            alt.Chart(forecast)
            .mark_area(color=VIOLET, opacity=0.13)
            .encode(
                x=x_axis,
                y=alt.Y("nim_low_pct:Q", title="NIM (%)", scale=scale, axis=_percent_axis()),
                y2="nim_high_pct:Q",
            )
        )
        layers = band + layers

    if shock_baseline is not None and not shock_baseline.empty:
        shock_df = shock_baseline[shock_baseline["series"] == "Baseline"].copy()
        shock_df["month_label"] = pd.to_datetime(shock_df["month"]).dt.strftime("%b %y")
        if not actual.empty and not shock_df.empty:
            shock_bridge = actual.tail(1).copy()
            shock_bridge["series"] = "Baseline"
            shock_df = pd.concat([shock_bridge, shock_df], ignore_index=True)
        shock_line = (
            alt.Chart(shock_df)
            .mark_line(strokeWidth=2.5, strokeDash=[4, 3], color=AMBER)
            .encode(
                x=x_axis,
                y=y_axis,
                tooltip=[
                    alt.Tooltip("month:T", title="Month", format="%B %Y"),
                    alt.Tooltip("nim_pct:Q", title="Signal-shocked NIM", format=".3f"),
                ],
            )
        )
        layers = layers + shock_line

    return _finish(layers, height)


# ------------------------------------------------------------------
# What-if engine
# ------------------------------------------------------------------

def build_scenario_comparison_chart(comparison, height=300):
    """Base against shocked outcome for each headline metric."""
    if comparison is None or comparison.empty:
        return _empty(["metric", "value"], mark="bar")

    chart = (
        alt.Chart(comparison)
        .mark_bar(cornerRadiusEnd=3, opacity=0.86)
        .encode(
            x=alt.X("value:Q", title="Percent", axis=_quant_axis("Percent")[0]),
            y=alt.Y("metric:N", title=None, sort=None, axis=_category_axis()),
            yOffset=alt.YOffset("series:N"),
            color=alt.Color(
                "series:N",
                scale=alt.Scale(
                    domain=["Current", "Scenario"], range=[ACCENT, VIOLET]
                ),
                legend=alt.Legend(title=None, labelColor="#95BB9E", orient="top"),
            ),
            tooltip=[
                alt.Tooltip("metric:N", title="Metric"),
                alt.Tooltip("series:N", title="Series"),
                alt.Tooltip("value:Q", title="Value", format=".2f"),
            ],
        )
    )

    return _finish(chart, height)


# ------------------------------------------------------------------
# Treasury
# ------------------------------------------------------------------

def build_treasury_scenario_chart(scenarios, height=300):
    if scenarios is None or scenarios.empty:
        return _empty(["scenario_name", "economic_value_impact_m"], mark="bar")

    chart_df = scenarios.copy()
    chart_df["economic_value_impact_m"] = pd.to_numeric(
        chart_df["economic_value_impact_m"], errors="coerce"
    )

    chart = (
        alt.Chart(chart_df)
        .mark_bar(cornerRadiusEnd=3, color=VIOLET, opacity=0.82)
        .encode(
            x=_quant("economic_value_impact_m:Q", "Economic value impact (€m)"),
            y=alt.Y(
                "scenario_name:N", title=None, sort="x", axis=_category_axis()
            ),
            tooltip=[
                alt.Tooltip("scenario_name:N", title="Scenario"),
                alt.Tooltip(
                    "economic_value_impact_m:Q",
                    title="Economic value (€m)",
                    format=",.0f",
                ),
                alt.Tooltip(
                    "estimated_oci_impact_m:Q", title="OCI (€m)", format=",.0f"
                ),
                alt.Tooltip(
                    "estimated_immediate_pnl_impact_m:Q",
                    title="Immediate P&L (€m)",
                    format=",.0f",
                ),
            ],
        )
    )

    return _finish(chart, height)


def build_treasury_asset_class_chart(portfolio, height=280):
    """Market value by asset class."""
    if portfolio is None or portfolio.empty:
        return _empty(["asset_class", "market_value_m"], mark="bar")

    by_class = (
        portfolio.groupby("asset_class", as_index=False)["market_value_m"]
        .sum()
        .sort_values("market_value_m", ascending=False)
    )

    chart = (
        alt.Chart(by_class)
        .mark_bar(cornerRadiusEnd=3, color=ACCENT, opacity=0.78)
        .encode(
            x=_quant("market_value_m:Q", "Market value (€m)"),
            y=alt.Y("asset_class:N", title=None, sort="-x", axis=_category_axis()),
            tooltip=[
                alt.Tooltip("asset_class:N", title="Asset class"),
                alt.Tooltip(
                    "market_value_m:Q", title="Market value (€m)", format=",.0f"
                ),
            ],
        )
    )

    return _finish(chart, height)


def build_treasury_dv01_chart(portfolio, height=280):
    """DV01 by maturity bucket, in maturity order rather than by size."""
    if portfolio is None or portfolio.empty:
        return _empty(["maturity_bucket", "dv01_m_per_bp"], mark="bar")

    bucket_order = ["0-2Y", "2-5Y", "5-10Y", "10Y+"]
    by_bucket = portfolio.groupby("maturity_bucket", as_index=False)[
        "dv01_m_per_bp"
    ].sum()

    chart = (
        alt.Chart(by_bucket)
        .mark_bar(cornerRadiusEnd=3, color=AMBER, opacity=0.8)
        .encode(
            x=alt.X(
                "maturity_bucket:N",
                title=None,
                sort=bucket_order,
                axis=alt.Axis(labelColor=AXIS_VALUE, domain=False, ticks=False),
            ),
            y=alt.Y(
                "dv01_m_per_bp:Q",
                title="DV01 (€m per bp)",
                axis=_quant_axis("DV01")[0],
            ),
            tooltip=[
                alt.Tooltip("maturity_bucket:N", title="Bucket"),
                alt.Tooltip("dv01_m_per_bp:Q", title="DV01 (€m/bp)", format=",.2f"),
            ],
        )
    )

    return _finish(chart, height)


# ------------------------------------------------------------------
# Peers
# ------------------------------------------------------------------

def build_peer_positioning_chart(peer_plot, height=390):
    """Return against capital, sized by balance sheet."""
    if peer_plot is None or peer_plot.empty:
        return _empty(["reported_return_pct", "cet1_ratio_pct"], mark="circle")

    base = alt.Chart(peer_plot).encode(
        x=_quant(
            "reported_return_pct:Q", "Reported return / own ROE proxy (%)"
        ),
        y=alt.Y(
            "cet1_ratio_pct:Q",
            title="CET1 ratio (%)",
            axis=_quant_axis("CET1 ratio (%)")[0],
        ),
        size=alt.Size(
            "total_assets_m:Q", legend=None, scale=alt.Scale(range=[120, 900])
        ),
        color=alt.Color(
            "is_our_bank:N",
            scale=alt.Scale(domain=["Peer", "Our Bank"], range=[ACCENT, VIOLET]),
            legend=alt.Legend(title=None, labelColor="#95BB9E", orient="top"),
        ),
        tooltip=[
            alt.Tooltip("bank_name:N", title="Bank"),
            alt.Tooltip("reported_return_pct:Q", title="Return", format=".1f"),
            alt.Tooltip("return_metric_type:N", title="Return metric"),
            alt.Tooltip("cet1_ratio_pct:Q", title="CET1", format=".1f"),
            alt.Tooltip(
                "cost_income_ratio_pct:Q", title="Cost / income", format=".1f"
            ),
        ],
    )

    points = base.mark_circle(opacity=0.84, stroke=INK, strokeWidth=0.5)
    labels = (
        alt.Chart(peer_plot[peer_plot["is_our_bank"] == "Our Bank"])
        .mark_text(dy=-18, font=MONO, fontSize=11, color="#E6F5E9")
        .encode(
            x="reported_return_pct:Q",
            y="cet1_ratio_pct:Q",
            text="bank_name:N",
        )
    )

    return _finish(points + labels, height)


# ------------------------------------------------------------------
# Strategy
# ------------------------------------------------------------------

def build_strategy_radar_chart(radar, height=390):
    """Opportunity map: strategic fit against financial attractiveness."""
    if radar is None or radar.empty:
        return _empty(
            ["strategic_fit_score", "financial_attractiveness_score"], mark="circle"
        )

    base = alt.Chart(radar).encode(
        x=alt.X(
            "strategic_fit_score:Q",
            title="Strategic fit",
            scale=alt.Scale(domain=[50, 100]),
            axis=_quant_axis("Strategic fit")[0],
        ),
        y=alt.Y(
            "financial_attractiveness_score:Q",
            title="Financial attractiveness",
            scale=alt.Scale(domain=[50, 100]),
            axis=_quant_axis("Financial attractiveness")[0],
        ),
        size=alt.Size(
            "overall_opportunity_score:Q",
            legend=None,
            scale=alt.Scale(range=[160, 1050]),
        ),
        color=alt.Color(
            "preferred_route:N",
            legend=alt.Legend(
                title="Route",
                labelColor="#95BB9E",
                titleColor="#95BB9E",
                orient="top",
            ),
        ),
        tooltip=[
            alt.Tooltip("opportunity_rank:Q", title="Rank"),
            alt.Tooltip("company_name:N", title="Company"),
            alt.Tooltip("capability_domain:N", title="Capability"),
            alt.Tooltip("preferred_route:N", title="Preferred route"),
            alt.Tooltip("strategic_fit_score:Q", title="Strategic fit", format=".1f"),
            alt.Tooltip(
                "financial_attractiveness_score:Q",
                title="Financial attractiveness",
                format=".1f",
            ),
            alt.Tooltip(
                "overall_opportunity_score:Q", title="Overall score", format=".1f"
            ),
        ],
    )

    points = base.mark_circle(opacity=0.82, stroke=INK, strokeWidth=0.6)
    labels = (
        alt.Chart(radar.head(5))
        .mark_text(dy=-17, font=MONO, fontSize=10, color="#D9E9DC")
        .encode(
            x="strategic_fit_score:Q",
            y="financial_attractiveness_score:Q",
            text="company_name:N",
        )
    )

    return _finish(points + labels, height)


def build_strategy_delta_chart(strategy_delta, top_name, second_name, height=245):
    """Where the top-ranked opportunity's score advantage actually comes from."""
    if strategy_delta is None or strategy_delta.empty:
        return _empty(["Component", "Weighted delta"], mark="bar")

    chart_df = strategy_delta.copy()
    chart_df["Leader"] = chart_df["Weighted delta"].apply(
        lambda value: top_name if value >= 0 else second_name
    )

    bars = (
        alt.Chart(chart_df)
        .mark_bar(cornerRadius=3, opacity=0.86)
        .encode(
            x=_quant(
                "Weighted delta:Q",
                f"Weighted score contribution: {top_name} minus {second_name}",
            ),
            y=alt.Y("Component:N", title=None, sort="-x", axis=_category_axis()),
            color=alt.condition(
                alt.datum["Weighted delta"] >= 0,
                alt.value(ACCENT),
                alt.value(VIOLET),
            ),
            tooltip=[
                alt.Tooltip("Component:N", title="Component"),
                alt.Tooltip(
                    "Weighted delta:Q", title="Weighted score delta", format="+.2f"
                ),
                alt.Tooltip("Leader:N", title="Advantage"),
            ],
        )
    )

    zero = (
        alt.Chart(pd.DataFrame({"x": [0]}))
        .mark_rule(color="#345D3F", strokeDash=[3, 3])
        .encode(x="x:Q")
    )

    return _finish(bars + zero, height)


def build_capability_gap_chart(gaps, height=280):
    if gaps is None or gaps.empty:
        return _empty(["capability", "capability_gap"], mark="bar")

    chart = (
        alt.Chart(gaps)
        .mark_bar(cornerRadiusEnd=3, color=ACCENT, opacity=0.78)
        .encode(
            x=_quant("capability_gap:Q", "Capability gap"),
            y=alt.Y("capability:N", title=None, sort="-x", axis=_category_axis()),
            tooltip=[
                alt.Tooltip("capability:N", title="Capability"),
                alt.Tooltip("current_score:Q", title="Current", format=".0f"),
                alt.Tooltip("target_score:Q", title="Target", format=".0f"),
                alt.Tooltip("capability_gap:Q", title="Gap", format=".0f"),
                alt.Tooltip("priority:N", title="Priority"),
            ],
        )
    )

    return _finish(chart, height)


# ------------------------------------------------------------------
# News
# ------------------------------------------------------------------

def build_geo_attention_chart(geo_news, height=260):
    """Per-country news attention over the trailing window."""
    if geo_news is None or geo_news.empty:
        return _empty(["country", "geo_attention_score"], mark="bar")

    chart = (
        alt.Chart(geo_news)
        .mark_bar(cornerRadiusEnd=3, color=VIOLET, opacity=0.8)
        .encode(
            x=_quant("geo_attention_score:Q", "Attention score"),
            y=alt.Y("country:N", title=None, sort="-x", axis=_category_axis()),
            tooltip=[
                alt.Tooltip("country:N", title="Country"),
                alt.Tooltip("geo_attention_score:Q", title="Attention", format=".1f"),
                alt.Tooltip("relevant_news_count:Q", title="Articles"),
                alt.Tooltip("high_impact_news_count:Q", title="High impact"),
                alt.Tooltip(
                    "bank_exposure_share_pct:Q", title="Exposure (%)", format=".1f"
                ),
            ],
        )
    )

    return _finish(chart, height)
