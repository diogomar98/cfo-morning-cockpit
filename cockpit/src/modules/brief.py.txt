"""
Morning Brief — the news on the left, what moved in our own numbers on the right.

The news column carries two feeds in two frames: internal developments the
bank's own data records, and external public news. The right column is the
domain grid — every indicator with its movement and its RAG status; hovering
a tile opens its why / impact / next reading.
"""

import html

import pandas as pd
import streamlit as st

from src import charts
from src.hud import (
    EXPLAIN_HINT,
    clip_ui_text,
    explain_panel,
    investigate_url,
    navigate_to_module,
    render_html,
)
from src.modules.news import article_confidence
from src.rag import confidence_badge, rag_badge

BRIEF_COPILOT_PROMPT = (
    "Based on the latest CFO morning brief, explain what changed in NIM, "
    "deposits and credit, why the observed data may matter, quantify the "
    "financial impact available in the certified views, and recommend the next "
    "investigation. Separate facts from interpretation and do not invent "
    "causality."
)

EXTERNAL_NEWS_SHOWN = 4


# ------------------------------------------------------------------
# Left column — news
# ------------------------------------------------------------------

def _internal_item(item):
    return f"""
    <div class="feed-item">
        <div class="feed-item-top">
            <span class="feed-tag">{item['tag']}</span>
            <span class="feed-date">{item['date']}</span>
            <span class="feed-status status-{item['status'].lower()}">{item['status']}</span>
        </div>
        <div class="feed-headline">{item['headline']}</div>
        <div class="feed-detail">{item['detail']}</div>
        <div class="feed-source">{item['source']}</div>
    </div>
    """


def _external_item(article):
    escape = html.escape
    level = str(article.get("potential_impact_level", "")).upper() or "UNRATED"
    return f"""
    <div class="feed-item">
        <div class="feed-item-top">
            <span class="feed-tag">{escape(str(article.get('category', 'News')))}</span>
            <span class="feed-date">{pd.to_datetime(article['published_date']).strftime('%d %b')}</span>
            <span class="feed-status status-impact-{level.lower()}">{escape(level.title())} impact</span>
        </div>
        <div class="feed-headline">{escape(str(article['headline']))}</div>
        <div class="feed-detail">{escape(clip_ui_text(article.get('bank_impact_summary', ''), 150))}</div>
        <div class="feed-detail"><strong>Potential metric</strong> {escape(str(article['primary_affected_metric']))}</div>
        <div class="feed-foot">
            {confidence_badge(article_confidence(article))}
            <a class="news-source-link" href="{escape(str(article['source_url']), quote=True)}" target="_blank" rel="noopener noreferrer">{escape(str(article['source']))} ↗</a>
        </div>
    </div>
    """


def _news_column(s):
    internal = "".join(_internal_item(item) for item in s.internal_news)
    if not internal:
        internal = '<div class="feed-empty">No internal developments recorded.</div>'

    if s.news_recent is not None and not s.news_recent.empty:
        external = "".join(
            _external_item(article)
            for _, article in s.news_recent.head(EXTERNAL_NEWS_SHOWN).iterrows()
        )
    else:
        external = '<div class="feed-empty">No recent public-news records available.</div>'

    return f"""
    <div class="brief-column-head">
        <span class="section-title">News</span>
        <span class="feed-legend">
            <span class="feed-key is-internal">Internal</span>
            <span class="feed-key is-external">External</span>
        </span>
    </div>
    <section class="feed-frame is-internal">
        <div class="feed-frame-head">
            <span class="feed-frame-title">Internal news</span>
            <span class="feed-frame-note">Recorded in the bank's own data</span>
        </div>
        {internal}
    </section>
    <section class="feed-frame is-external">
        <div class="feed-frame-head">
            <span class="feed-frame-title">External news</span>
            <span class="feed-frame-note">Public sources · bank impact is prototype analysis</span>
        </div>
        {external}
    </section>
    """


# ------------------------------------------------------------------
# Right column — changes in our data and indicators
# ------------------------------------------------------------------

def _domain_tile(tile):
    """
    One KPI: the number, its movement, its RAG and the first line of the
    reading. Hovering opens the full why / impact / next / RAG over the page.
    """
    copilot_link = (
        f'<a class="kpi-explain-link" href="{investigate_url(tile["topic"])}" '
        f'target="_self">Ask Copilot &rarr;</a>'
    )
    return f"""
        <div class="kpi-slot domain-slot" tabindex="0">
            <div class="domain-tile tone-{tile['tone']}">
                <div class="domain-tile-top">
                    <span class="domain-tile-label">{tile['label']}</span>
                </div>
                <div class="domain-tile-value">{tile['value']}</div>
                <div class="domain-tile-delta"><span class="domain-tile-dot"></span>{tile['delta']}</div>
                <div class="domain-tile-rag">{rag_badge(tile['rag'])}</div>
                <div class="domain-tile-why"><span>Why</span>{tile['why_short']}</div>
                <span class="domain-tile-more">{EXPLAIN_HINT}</span>
            </div>
            {explain_panel(
                tile['label'], tile['why'], tile['impact'], tile['next'], tile['rag'],
                footer=copilot_link,
            )}
        </div>
    """


def _domain_panel(domain):
    """One supervisory domain: its KPIs side by side."""
    tiles = "".join(_domain_tile(tile) for tile in domain["tiles"])

    return f"""
    <section class="domain-panel">
        <div class="domain-panel-head">
            <span class="domain-panel-title">{domain['name']}</span>
            <span class="domain-panel-metrics">{domain['metrics']}</span>
        </div>
        <div class="domain-panel-body" style="--tiles: {len(domain['tiles'])}">
            {tiles}
        </div>
    </section>
    """


def render_brief(s):
    news_col, data_col = st.columns([0.9, 1.55], gap="medium")

    with news_col:
        render_html(_news_column(s))

    with data_col:
        render_html(
            f"""
            <div class="brief-column-head">
                <span class="section-title">Changes in our data &amp; indicators</span>
                <span class="brief-column-note">Live {s.live_date} · close {s.close_date}</span>
            </div>
            <div class="domain-grid brief-domain-grid">
                {"".join(_domain_panel(domain) for domain in s.domain_grid)}
            </div>
            """
        )

        nim_col, deposit_col = st.columns(2)
        with nim_col:
            render_html(
                """<div class="module-code">Performance trend</div>
                <div class="section-title">NIM trajectory</div>"""
            )
            st.altair_chart(
                charts.build_nim_chart(s.monthly_nim, height=230),
                use_container_width=True,
            )
        with deposit_col:
            render_html(
                """<div class="module-code">Funding trend</div>
                <div class="section-title">30-day deposits by country</div>"""
            )
            st.altair_chart(
                charts.build_deposit_country_chart(s.deposit_country, height=230),
                use_container_width=True,
            )

        if st.button(
            "Investigate the morning brief with CFO Copilot →",
            key="brief_to_copilot",
        ):
            st.session_state["brief_copilot_prompt"] = BRIEF_COPILOT_PROMPT
            navigate_to_module("copilot")
