import streamlit as st

from src.news_partner import signal_to_scenario_kwargs

_TYPE_LABELS = {
    "rate_change": "Rate change",
    "deposit_shift": "Deposit shift",
    "credit_migration": "Credit migration",
    "macro": "Macro / informational",
}

_PARAM_TO_SLIDER = {
    "rate_shock_bps": ("scenario_rate_shock_bps", -200, 200, int),
    "deposit_outflow_pct": ("scenario_deposit_outflow_pct", 0.0, 25.0, float),
    "stage_2_increase_pct_points": ("scenario_stage_2_increase", 0.0, 10.0, float),
    "stage_3_increase_pct_points": ("scenario_stage_3_increase", 0.0, 5.0, float),
}


def _plain_english(signal: dict) -> str:
    stype = signal.get("signal_type") or ""
    entity = signal.get("entity") or "Unknown entity"
    value = signal.get("value")
    param = signal.get("engine_param") or ""

    if stype == "rate_change" and value is not None:
        direction = "raised" if value > 0 else "cut"
        return f"{entity} {direction} rates by {abs(value):.0f} bps"
    if stype == "deposit_shift" and value is not None:
        return f"Deposit outflow of {value:.1f}% of deposits"
    if stype == "credit_migration" and value is not None:
        stage = "3 (defaults/NPLs)" if "stage_3" in param else "2 (watchlist)"
        return f"Stage {stage} migration: +{value:.1f} pp"
    if stype == "macro":
        return signal.get("quote") or "Macro / informational signal"
    if value is not None and param:
        return f"{param.replace('_', ' ')}: {value}"
    return signal.get("quote") or "Signal detected"


def _confidence_bar(confidence: float) -> str:
    filled = round(confidence * 5)
    return "\u2588" * filled + "\u2591" * (5 - filled)


def render_overnight_signals_panel(signals: list[dict]) -> None:
    with st.expander("\U0001F4F0 Overnight signals", expanded=True):
        if not signals:
            st.caption("No market signals detected overnight.")
            return
        actionable = [s for s in signals if s.get("engine_param")]
        macro = [s for s in signals if not s.get("engine_param")]
        if actionable:
            st.markdown("**Actionable**")
            for sig in actionable:
                _signal_card(sig)
        if macro:
            st.markdown("**Informational / macro**")
            for sig in macro:
                _signal_card(sig)


def _signal_card(sig: dict) -> None:
    article = sig.get("_article", {})
    entity = sig.get("entity") or "-"
    confidence = float(sig.get("confidence") or 0)
    quote = sig.get("quote") or ""
    source = article.get("source", "")
    published = article.get("published", "")
    headline = article.get("headline", "")
    label = _TYPE_LABELS.get(sig.get("signal_type") or "", "Signal")
    summary = _plain_english(sig)
    source_suffix = f" - {source}, {published}" if source else ""
    st.markdown(
        f"**{entity}** - _{label}_ \n"
        f"{summary} \n"
        f'*\"{quote}\"* \n'
        f"Confidence: `{_confidence_bar(confidence)}` {confidence:.0%}{source_suffix}",
        help=headline or None,
    )
    st.divider()


def apply_pending_signals() -> None:
    if "_pending_signal_kwargs" in st.session_state:
        kwargs = st.session_state.pop("_pending_signal_kwargs")
        sig = st.session_state.pop("_pending_applied_signal", None)
        for param, value in kwargs.items():
            if param in _PARAM_TO_SLIDER:
                key, lo, hi, cast = _PARAM_TO_SLIDER[param]
                st.session_state[key] = cast(max(lo, min(hi, value)))
        if sig is not None:
            st.session_state["applied_signal"] = sig

    if st.session_state.pop("_pending_reset", False):
        st.session_state["scenario_rate_shock_bps"] = 0
        st.session_state["scenario_deposit_outflow_pct"] = 0.0
        st.session_state["scenario_stage_2_increase"] = 0.0
        st.session_state["scenario_stage_3_increase"] = 0.0
        st.session_state.pop("applied_signal", None)


def render_signal_apply_panel(actionable_signals: list[dict]) -> None:
    if not actionable_signals:
        st.caption("No actionable signals available.")
    else:
        st.markdown("**Apply a news signal**")
        for i, sig in enumerate(actionable_signals):
            article = sig.get("_article", {})
            summary = _plain_english(sig)
            source = article.get("source", "-")
            quote = sig.get("quote") or ""
            col_text, col_btn = st.columns([4, 1])
            with col_text:
                st.markdown(f"**{summary}** \n*\"{quote}\"* - {source}")
            with col_btn:
                if st.button("Apply", key=f"apply_signal_{i}", width="stretch"):
                    st.session_state["_pending_signal_kwargs"] = signal_to_scenario_kwargs(sig)
                    st.session_state["_pending_applied_signal"] = sig
                    st.rerun()

    if st.button("Reset scenario", width="stretch"):
        st.session_state["_pending_reset"] = True
        st.rerun()


def render_provenance_banner(signal: dict) -> None:
    article = signal.get("_article", {})
    entity = signal.get("entity") or "Unknown"
    quote = signal.get("quote") or ""
    source = article.get("source", "")
    summary = _plain_english(signal)
    st.info(
        f"**Scenario driven by:** {entity} - *\"{quote}\"*"
        + (f" ({source})" if source else "")
        + f" \n{summary}"
    )


def add_horizon_signal_annotation(fig, metric: str) -> None:
    applied = st.session_state.get("applied_signal")
    if not applied or applied.get("engine_param") != "rate_shock_bps":
        return
    if metric not in ("nim_pct", "cet1_ratio_pct"):
        return
    val = applied.get("value") or 0
    entity = applied.get("entity") or "Signal"
    direction = "hike" if val > 0 else "cut"
    fig.add_annotation(
        xref="paper", yref="paper", x=0.01, y=0.97,
        text=f"if applied: {entity} {abs(int(val))} bps {direction}",
        showarrow=False, font=dict(size=11, color="#d62728"),
        bgcolor="rgba(255,255,255,0.85)", bordercolor="#d62728",
        borderwidth=1, align="left",
    )