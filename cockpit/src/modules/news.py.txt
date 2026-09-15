"""
News — overnight external developments and their potential bank impact.

Two layers sit here. The upper one is the curated news feed with its
per-country attention scoring. The lower one runs the OpenAI signal extractor
over the fixture articles and lets a signal be pushed straight into the What-If
engine as a starting assumption.
"""

import html

import pandas as pd
import streamlit as st

from src import charts
from src.hud import (
    clip_ui_text,
    investigate_url,
    metric_card,
    module_url,
    navigate_to_module,
    render_html,
    safe_float,
)
from src.rag import confidence_badge, confidence_probability
from src.modules.scenario import DEFAULT_INPUTS
from src.news_partner import extract_signals, load_articles, signal_to_scenario_kwargs

IMPACT_BADGE = {"HIGH": "alert-red", "MEDIUM": "alert-amber"}


def article_confidence(article):
    """How sure the classifier is about an article's potential bank impact."""
    return confidence_probability(
        safe_float(article.get("confidence_score"), 0.0),
        "Classifier confidence in the potential bank impact",
    )


@st.cache_data(show_spinner="Extracting overnight news signals…")
def load_extracted_signals():
    """
    Run the OpenAI signal extractor over the fixture articles.

    Cached so the model is called once per session rather than on every rerun.
    An article that fails extraction is skipped rather than failing the module.
    """
    signals = []
    for article in load_articles():
        try:
            extracted = extract_signals(article)
        except Exception:
            continue
        for signal in extracted:
            signal["_article"] = article
        signals.extend(extracted)
    return signals


def _signal_to_scenario_inputs(signal):
    """
    Translate an extracted signal into What-If engine inputs.

    The engine models rates and deposit volume. A credit-migration signal has no
    lever here, so it maps to no change and the caller reports that.
    """
    kwargs = signal_to_scenario_kwargs(signal)
    inputs = dict(st.session_state.get("scenario_inputs", DEFAULT_INPUTS))
    applied = []

    if "rate_shock_bps" in kwargs:
        inputs["ecb"] = int(max(-100, min(100, kwargs["rate_shock_bps"])))
        applied.append(f"ECB {inputs['ecb']:+d} bps")

    if "deposit_outflow_pct" in kwargs:
        # The extractor reports an outflow as a positive percentage; the engine
        # takes a signed balance shock.
        outflow = float(kwargs["deposit_outflow_pct"])
        inputs["deposit"] = float(max(-10.0, min(5.0, -abs(outflow))))
        applied.append(f"deposits {inputs['deposit']:+.1f}%")

    return inputs, applied


def _news_card(article):
    escape = html.escape
    level = str(article.get("potential_impact_level", "")).upper()
    badge_class = IMPACT_BADGE.get(level, "alert-green")

    return f"""
    <div class="news-card">
        <div class="news-topline">
            <span class="news-badge">{escape(str(article.get('category', 'News')))}</span>
            <span class="news-meta">{escape(str(article['source']))} · {pd.to_datetime(article['published_date']).strftime('%d %b')} · {escape(str(article.get('country', '')))}</span>
        </div>
        <div class="news-headline">{escape(str(article['headline']))}</div>
        <div class="news-context-grid">
            <div class="news-context-line">
                <span class="news-context-label">Why it matters</span>
                <span class="news-context-copy">{escape(clip_ui_text(article.get('bank_impact_summary', ''), 160))}</span>
            </div>
            <div class="news-context-line">
                <span class="news-context-label">Potential metric</span>
                <span class="news-context-copy">{escape(str(article['primary_affected_metric']))} · <span class="{badge_class}">{escape(level or 'UNRATED')}</span></span>
            </div>
            <div class="news-context-line">
                <span class="news-context-label">Confidence</span>
                <span class="news-context-copy">{confidence_badge(article_confidence(article))}</span>
            </div>
            <div class="news-context-line">
                <span class="news-context-label">Next</span>
                <span class="news-context-copy">{escape(clip_ui_text(article.get('suggested_action', ''), 140))}</span>
            </div>
        </div>
        <div class="news-footer">
            <a class="news-source-link" href="{escape(str(article['source_url']), quote=True)}" target="_blank" rel="noopener noreferrer">Open article ↗</a>
            <span class="news-public-note">Public source · bank impact is prototype analysis</span>
        </div>
    </div>
    """


def _render_signal_workbench():
    """The OpenAI extraction layer, below the curated feed."""
    render_html(
        """
        <div class="module-code" style="margin-top:1rem;">Signal extraction / model-assisted</div>
        <div class="section-title">Overnight signals</div>
        <div class="section-subtitle">
            Quantified signals extracted from the article text. An actionable
            signal can be pushed into the What-If engine as a starting
            assumption; the engine still calculates the result deterministically.
        </div>
        """
    )

    try:
        signals = load_extracted_signals()
    except Exception as error:
        st.warning(f"News signal extraction unavailable: {error}")
        return

    if not signals:
        st.caption("No market signals detected overnight.")
        return

    actionable = [s for s in signals if s.get("engine_param")]
    informational = [s for s in signals if not s.get("engine_param")]

    if actionable:
        for index, signal in enumerate(actionable):
            article = signal.get("_article", {})
            quote = str(signal.get("quote") or "")
            confidence = safe_float(signal.get("confidence"), 0.0)

            copy_col, action_col = st.columns([4, 1])

            with copy_col:
                render_html(
                    f"""
                    <div class="feature-callout">
                        <div class="feature-callout-title">{html.escape(str(signal.get('entity') or 'Signal'))} {confidence_badge(confidence_probability(confidence, "Model confidence in the extracted signal"))}</div>
                        <div class="feature-callout-copy">
                            “{html.escape(clip_ui_text(quote, 180))}”<br>
                            <span class="news-public-note">{html.escape(str(article.get('source', '—')))} · {html.escape(str(article.get('headline', '')))}</span>
                        </div>
                    </div>
                    """
                )

            with action_col:
                if st.button(
                    "Send to What-If",
                    key=f"news_signal_{index}"
                ):
                    inputs, applied = _signal_to_scenario_inputs(signal)
                    if applied:
                        st.session_state["scenario_inputs"] = inputs
                        st.session_state["scenario_from_signal"] = ", ".join(applied)
                        st.session_state["applied_signal"] = signal
                        navigate_to_module("scenario")
                    else:
                        st.warning(
                            "This signal has no rate or deposit lever in the "
                            "What-If engine."
                        )

    if informational:
        with st.expander(
            f"Informational / macro signals ({len(informational)})", expanded=False
        ):
            for signal in informational:
                article = signal.get("_article", {})
                st.markdown(
                    f"**{signal.get('entity') or '—'}** — "
                    f"*\"{clip_ui_text(str(signal.get('quote') or ''), 160)}\"* "
                    f"· {article.get('source', '—')}"
                )


def render_news(s):
    render_html(
        """
        <div class="section-title">News Intelligence</div>
        <div class="section-subtitle">
            Public news mapped to the bank's country exposures, with a prepared
            view of the metric each development could touch. News is context for
            an investigation, never proven causality for an internal movement.
        </div>
        """
    )

    articles = 0 if s.news_recent is None else len(s.news_recent)
    focus = s.geo_focus

    focus_name = html.escape(str(focus["country"])) if focus is not None else "—"
    focus_score = safe_float(focus["geo_attention_score"]) if focus is not None else 0.0
    exposure = safe_float(focus["bank_exposure_share_pct"]) if focus is not None else 0.0

    ratings = s.ratings
    cards = [
        metric_card(
            "ARTICLES IN WINDOW",
            f"{articles}",
            "deduplicated public sources",
            ratings["news_articles"],
        ),
        metric_card(
            "HIGH POTENTIAL IMPACT",
            f"{s.high_impact_news_count}",
            "flagged for review",
            ratings["news_high"],
        ),
        metric_card(
            "HIGHEST ATTENTION",
            focus_name,
            f"attention score {focus_score:.1f}",
            ratings["news_attention"],
            value_class="kpi-value-name",
        ),
        metric_card(
            "EXPOSURE THERE",
            f"{exposure:.1f}%",
            "share of bank exposure",
            ratings["news_exposure"],
        ),
    ]

    for column, card in zip(st.columns(4), cards):
        with column:
            render_html(card)

    render_html(
        f"""
        <div class="decision-strip">
            <div class="decision-strip-item">
                <span class="flow-label">Change</span>
                <strong>{s.news_signal_primary}</strong>
                <span>{s.news_signal_secondary}</span>
            </div>
            <div class="decision-strip-item">
                <span class="flow-label">Why</span>
                <strong>{s.news_why}</strong>
                <span>Prepared analysis of why the development could matter.</span>
            </div>
            <div class="decision-strip-item">
                <span class="flow-label">Impact</span>
                <strong>Potential metric: {s.news_impact}</strong>
                <span>Potential, not measured — the internal data does not attribute causality.</span>
                {confidence_badge(article_confidence(s.top_news)) if s.top_news is not None else ""}
            </div>
            <div class="decision-strip-item">
                <span class="flow-label">Next</span>
                <strong>{s.news_next}</strong>
                <span>Investigate before treating any development as actionable.</span>
            </div>
        </div>
        """
    )

    feed_col, geo_col = st.columns([1.5, 1])

    with feed_col:
        render_html(
            """<div class="module-code">Feed / public sources</div>
            <div class="section-title">Recent developments</div>"""
        )
        if s.news_recent is not None and not s.news_recent.empty:
            for _, article in s.news_recent.head(8).iterrows():
                render_html(_news_card(article))
        else:
            st.caption("No recent public-news records available.")

    with geo_col:
        render_html(
            """<div class="module-code">Geographic lens / trailing 30 days</div>
            <div class="section-title">Where is the attention?</div>"""
        )
        st.altair_chart(
            charts.build_geo_attention_chart(s.geo_news, height=250),
            use_container_width=True,
        )

        if s.geo_news is not None and not s.geo_news.empty:
            display = s.geo_news[
                [
                    "country",
                    "relevant_news_count",
                    "high_impact_news_count",
                    "bank_exposure_share_pct",
                    "geo_attention_score",
                ]
            ].copy()
            display.columns = [
                "Country",
                "Articles",
                "High impact",
                "Exposure (%)",
                "Attention",
            ]
            st.dataframe(display, hide_index=True)

        _render_signal_workbench()

    render_html(
        f"""
        <div class="module-action-row">
            <a class="module-action-link" href="{investigate_url('news')}" target="_self">
                Ask Copilot about these developments →
            </a>
            <a class="module-action-link" href="{module_url('scenario')}" target="_self">
                Stress a development in What-If →
            </a>
        </div>
        """
    )
