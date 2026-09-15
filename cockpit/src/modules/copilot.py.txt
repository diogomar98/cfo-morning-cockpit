"""
CFO Copilot — conversational investigation over the cockpit data.

The reference cockpit talks to Databricks Genie. This one uses the local
partners instead: OpenAI when an API key is configured, and the deterministic
rule-based partner otherwise, so the module still answers with no network.
"""

import streamlit as st

from src.ai_partner import answer_question, build_morning_briefing
from src.cockpit_views import metrics_history
from src.copilot_partner import answer_data_question
from src.openai_partner import build_cockpit_facts, generate_openai_response
from src.hud import clear_query_value, get_query_value, render_html

INVESTIGATION_PROMPTS = {
    "nim": (
        "Investigate the latest NIM movement. Quantify the change versus the "
        "prior month, show the available loan-yield and deposit-cost movements, "
        "identify country or business-line drivers the data supports, quantify "
        "the NII impact, and separate observed facts from interpretation."
    ),
    "deposits": (
        "Investigate the latest 30-day deposit movement. Quantify the bank-level "
        "change in EUR and percent, identify the countries and business lines "
        "driving it, and explain what the CFO should review before changing "
        "deposit pricing."
    ),
    "credit": (
        "Investigate the current credit-migration signal. Focus on the country "
        "and business line with the highest Stage 2 concentration, quantify the "
        "30-day change and Stage 3 position, and identify what can and cannot be "
        "concluded about the underlying cause."
    ),
    "efficiency": (
        "Investigate the year-to-date cost/income ratio. Separate the cost and "
        "income movements that drove it, quantify what one point of the ratio is "
        "worth in annualised operating income, compare it with the peer median, "
        "and identify what the CFO should test before approving new cost."
    ),
    "balance_sheet": (
        "Investigate the balance-sheet position: the loan book, the deposit base "
        "and the loan-to-deposit ratio. Quantify the 30-day movements, identify "
        "the business lines and countries driving them, and explain how much "
        "further lending the current funding base can carry."
    ),
    "capital": (
        "Investigate the capital position. Split the CET1 ratio movement into its "
        "capital-generation and risk-weighted-asset components, quantify the "
        "headroom over the regulatory requirement, and identify what the CFO "
        "should stress before committing capital to growth or distribution."
    ),
    "liquidity": (
        "Investigate the liquidity position. Explain the LCR movement in terms of "
        "high-quality liquid assets and net cash outflows, relate it to the "
        "30-day deposit movement and the loan-to-deposit ratio, and identify the "
        "funding risk the CFO should review next."
    ),
    "news": (
        "Review the latest public news developments. Lead with the actual "
        "headlines and sources, explain the potentially affected bank metrics, "
        "and suggest the next investigation. Do not present news as proven "
        "causality for internal financial movements."
    ),
    "horizon": (
        "Explain the Horizon run-rate baseline. Distinguish clearly between the "
        "mechanical momentum-decay baseline and an official forecast or budget. "
        "Identify which observed repricing, funding and balance-sheet "
        "assumptions matter most, and suggest what the CFO should stress next."
    ),
    "scenario": (
        "Interpret the latest What-If scenario shown in the cockpit. Explain the "
        "NIM and NII impact, the role of loan and deposit pass-through "
        "assumptions, any replacement-funding effect, and what the CFO should "
        "compare next. Do not recalculate the deterministic scenario output."
    ),
}

QUICK_COMMANDS = [
    (
        "Brief me on what changed",
        "copilot_suggestion_brief",
        "Give me the CFO morning decision brief. Rank the most material observed "
        "changes, explain why each may matter, quantify the impact where the data "
        "supports it, and tell me what to investigate or decide next.",
    ),
    ("Challenge the outlook", "copilot_suggestion_horizon", INVESTIGATION_PROMPTS["horizon"]),
    (
        "Where are we behind peers?",
        "copilot_suggestion_peers",
        "Compare our latest position with the European peer set. Identify the "
        "most decision-relevant gaps in return, capital and efficiency, "
        "distinguish unlike-for-like return metrics, and recommend the first "
        "management question to pursue.",
    ),
    (
        "What is our treasury trade-off?",
        "copilot_suggestion_treasury",
        "Summarize the treasury portfolio trade-off: current DV01 and duration, "
        "the +50bp economic-value and OCI impact, and which predefined hedge "
        "alternative changes the exposure most. Separate economic value, OCI and "
        "immediate P&L.",
    ),
]

DEFAULT_FOLLOWUPS = [
    "What evidence would change this conclusion?",
    "What is the main downside or trade-off?",
    "What should I monitor next?",
]


def consume_investigation_topic(selected_module):
    """
    Turn ``?investigate=<topic>`` into a queued prompt, exactly once.

    The parameter is cleared after it is read, so the Copilot's own rerun does
    not resubmit the same question.
    """
    if selected_module != "copilot":
        st.session_state.pop("_last_investigation_topic", None)
        return

    topic = get_query_value("investigate", "").lower().strip()
    if topic not in INVESTIGATION_PROMPTS:
        return

    if st.session_state.get("_last_investigation_topic") != topic:
        st.session_state["brief_copilot_prompt"] = INVESTIGATION_PROMPTS[topic]
        st.session_state["_last_investigation_topic"] = topic

    clear_query_value("investigate")


def _answer(question, history):
    """
    Answer through OpenAI, falling back to the deterministic partner.

    The fallback matters: without an API key the module must still respond
    rather than surface a stack trace.
    """
    try:
        facts = build_cockpit_facts(history)
        return generate_openai_response(question, facts), "OpenAI"
    except Exception:
        lowered = question.lower()
        if "brief" in lowered or "what changed" in lowered:
            return build_morning_briefing(history), "Deterministic partner"
        return answer_question(question, history), "Deterministic partner"


def _render_data_copilot():
    """
    A Genie-backed data Q&A thread, separate from the decision-partner thread
    above. Its own session-state key and chat_input container keep it from
    colliding with the decision thread's chat_input.
    """
    render_html(
        """
        <div class="module-code" style="margin-top:1.4rem;">Data copilot</div>
        <div class="section-title" style="font-size:1.05rem;">Ask the data</div>
        <div class="section-subtitle">
            Ask a plain-language data question. Genie retrieves the figures and the
            answer below is grounded only in what it returns.
        </div>
        """
    )

    st.session_state.setdefault("copilot_messages", [])
    data_messages = st.session_state["copilot_messages"]

    with st.container():
        for message in data_messages:
            role = message.get("role", "assistant")
            avatar = ":material/person:" if role == "user" else ":material/database:"

            with st.chat_message(role, avatar=avatar):
                st.markdown(message.get("content", ""))

                provenance = message.get("provenance")
                if role == "assistant" and provenance:
                    with st.expander("How this was derived"):
                        st.markdown(
                            "**Question sent to Genie:** "
                            f"{provenance.get('refined_question') or '_none_'}"
                        )

                        sql = provenance.get("sql")
                        if sql:
                            st.code(sql, language="sql")
                        else:
                            st.caption("No SQL was returned.")

                        data = provenance.get("data")
                        if data is not None and not (
                            hasattr(data, "empty") and data.empty
                        ):
                            st.dataframe(data)
                        else:
                            st.caption("No data rows were returned.")

        data_question = st.chat_input(
            "Ask a data question — e.g. how did NIM trend last quarter?",
            key="copilot_data_chat_input",
        )

    if data_question and data_question.strip():
        question = data_question.strip()
        data_messages.append({"role": "user", "content": question})

        try:
            with st.spinner("Asking Genie…"):
                result = answer_data_question(question)
            data_messages.append(
                {
                    "role": "assistant",
                    "content": result["final_answer"],
                    "provenance": {
                        "refined_question": result["refined_question"],
                        "sql": result["sql"],
                        "data": result["data"],
                    },
                }
            )
        except Exception as error:
            data_messages.append(
                {
                    "role": "assistant",
                    "content": (
                        "The data question could not be answered right now. "
                        f"Technical detail: `{error}`"
                    ),
                    "provenance": None,
                }
            )

        st.rerun()


def render_copilot(s):
    render_html(
        """
        <div class="section-title">CFO AI Decision Partner</div>
        <div class="section-subtitle">
            Challenge the numbers, connect signals across the cockpit and turn
            evidence into a decision path.
        </div>
        """
    )

    render_html(
        f"""
        <div class="panel">
            <div class="copilot-intro">
                <div class="copilot-glyph">AI</div>
                <div>
                    <div class="copilot-name">Executive decision intelligence</div>
                    <div class="copilot-copy">
                        Ask what changed, why it matters, what the trade-offs are and what
                        should happen next. Deterministic scenario outputs stay in What-If.
                    </div>
                </div>
            </div>
            <div class="copilot-context-strip">
                <div class="copilot-context-item"><span>Live data</span><strong>{s.live_date}</strong></div>
                <div class="copilot-context-item"><span>NIM</span><strong>{s.cert_current_nim:.2f}%</strong></div>
                <div class="copilot-context-item"><span>CET1</span><strong>{s.cet1_ratio:.1f}%</strong></div>
                <div class="copilot-context-item"><span>LCR</span><strong>{s.lcr_ratio:.1f}%</strong></div>
            </div>
        </div>
        """
    )

    st.session_state.setdefault("cfo_copilot_messages", [])

    command_col, reset_col = st.columns([5, 1])

    with command_col:
        render_html(
            """
            <div class="copilot-command-bar">
                <span>Decision thread</span>
                <span>Ask · challenge · compare · decide</span>
            </div>
            """
        )

    with reset_col:
        if st.button("Clear context", key="reset_cfo_copilot"):
            st.session_state["cfo_copilot_messages"] = []
            st.rerun()

    suggested_prompt = st.session_state.pop("brief_copilot_prompt", None)

    command_cols = st.columns(len(QUICK_COMMANDS))
    for column, (label, key, prompt) in zip(command_cols, QUICK_COMMANDS):
        with column:
            if st.button(label, key=key):
                suggested_prompt = prompt

    messages = st.session_state["cfo_copilot_messages"]

    if not messages:
        render_html(
            """
            <div class="panel" style="margin-top:0.85rem;">
                <div class="readout-label">Start with a decision, not a search</div>
                <div style="margin-top:0.45rem; color:#78ac86; font-size:0.82rem; line-height:1.5;">
                    Ask the assistant to challenge an assumption, compare alternatives,
                    connect a market development to the bank's exposures, or tell you what
                    evidence would change a decision.
                </div>
            </div>
            """
        )
    else:
        render_html(
            '<div class="copilot-thread-label" style="margin-top:1rem;">Decision thread</div>'
        )

        for message in messages:
            role = message.get("role", "assistant")
            avatar = ":material/person:" if role == "user" else ":material/monitoring:"

            with st.chat_message(role, avatar=avatar):
                if role == "user":
                    render_html('<div class="copilot-user-label">CFO / question</div>')
                else:
                    render_html(
                        '<div class="copilot-answer-label">CFO AI / decision brief</div>'
                    )

                st.markdown(message.get("content", ""))

                source = message.get("source")
                if role == "assistant" and source:
                    st.caption(f"Answered by: {source}")

    followups = DEFAULT_FOLLOWUPS if messages else []
    if followups:
        render_html(
            '<div class="module-code" style="margin-top:0.8rem;">Next investigations</div>'
        )
        followup_cols = st.columns(len(followups))
        for index, suggestion in enumerate(followups):
            with followup_cols[index]:
                if st.button(
                    suggestion, key=f"copilot_followup_{index}"
                ):
                    suggested_prompt = suggestion

    typed = st.chat_input(
        "Ask a CFO question — challenge the evidence, compare options or decide what to do next…"
    )

    question = suggested_prompt or (typed.strip() if typed and typed.strip() else None)

    if question:
        messages.append({"role": "user", "content": question})

        try:
            with st.spinner("Analyzing evidence and decision implications…"):
                answer, source = _answer(question, metrics_history())
            messages.append(
                {"role": "assistant", "content": answer, "source": source}
            )
        except Exception as error:
            messages.append(
                {
                    "role": "assistant",
                    "content": (
                        "**Decision view**\n\nThe investigation could not complete, so "
                        "no financial conclusion has been generated from incomplete "
                        f"evidence.\n\nTechnical detail: `{error}`"
                    ),
                    "source": None,
                }
            )

        st.rerun()

    _render_data_copilot()

    render_html(
        """
        <div class="copilot-evidence-note">
            Financial conclusions are grounded in the cockpit's certified views.
            Scenario calculations remain deterministic in What-If.
        </div>
        """
    )
