import os
import html

import streamlit as st
import pandas as pd
import altair as alt

from databricks import sql
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config
from textwrap import dedent


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="A.R.C. | CFO Command",
    page_icon="◉",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# HELPERS
# ============================================================

def render_html(content):
    st.html(dedent(content).strip())


def safe_float(value, default=0.0):
    if pd.isna(value):
        return default
    return float(value)


VALID_MODULES = {
    "home",
    "brief",
    "horizon",
    "scenario",
    "treasury",
    "peers",
    "strategy",
    "news",
    "copilot",
}


def get_selected_module():
    """Return the module selected through the radial HUD."""

    try:
        selected = st.query_params.get(
            "module",
            "home",
        )

    except AttributeError:
        selected = st.experimental_get_query_params().get(
            "module",
            ["home"],
        )

    if isinstance(selected, list):
        selected = selected[-1] if selected else "home"

    selected = str(selected).lower()

    if selected not in VALID_MODULES:
        return "home"

    return selected


def navigate_to_module(module):
    """Update radial navigation state across Streamlit versions."""

    if module not in VALID_MODULES:
        return

    try:
        st.query_params["module"] = module

    except AttributeError:
        st.experimental_set_query_params(
            module=module,
        )

    st.rerun()


def get_query_value(key, default=""):
    """Read one query-parameter value across Streamlit versions."""

    try:
        value = st.query_params.get(key, default)
    except AttributeError:
        value = st.experimental_get_query_params().get(key, [default])

    if isinstance(value, list):
        value = value[-1] if value else default

    return str(value) if value is not None else str(default)


# ============================================================
# DATABRICKS CONNECTION
# ============================================================

cfg = Config()

# Environment-specific resources are configured outside source control.
# Supported options:
#   DATABRICKS_WAREHOUSE_HTTP_PATH=/sql/1.0/warehouses/<id>
#   or DATABRICKS_WAREHOUSE_ID=<id>
WAREHOUSE_HTTP_PATH = os.getenv("DATABRICKS_WAREHOUSE_HTTP_PATH")
if not WAREHOUSE_HTTP_PATH:
    warehouse_id = os.getenv("DATABRICKS_WAREHOUSE_ID") or os.getenv("CFO_WAREHOUSE_ID")
    if warehouse_id:
        WAREHOUSE_HTTP_PATH = f"/sql/1.0/warehouses/{warehouse_id}"

# Data namespace is configurable so the same source can run in personal and ABN environments.
DATA_CATALOG = os.getenv("CFO_DATA_CATALOG", "frbg3as_studio_a")
DATA_SCHEMA = os.getenv("CFO_DATA_SCHEMA", "cfo_cockpit")
DATA_NAMESPACE = f"{DATA_CATALOG}.{DATA_SCHEMA}"


def get_connection():

    if not WAREHOUSE_HTTP_PATH:
        raise RuntimeError(
            "No SQL warehouse configured. Set DATABRICKS_WAREHOUSE_HTTP_PATH "
            "or DATABRICKS_WAREHOUSE_ID/CFO_WAREHOUSE_ID in the App environment."
        )

    server_hostname = cfg.host

    if server_hostname.startswith("https://"):
        server_hostname = server_hostname.replace("https://", "")

    elif server_hostname.startswith("http://"):
        server_hostname = server_hostname.replace("http://", "")

    # Prefer Databricks Apps user authorization when a forwarded user token
    # is available. This makes Unity Catalog enforce the permissions of the
    # signed-in app user (useful in governed environments such as ABN).
    #
    # If user authorization is not configured, fall back to the app service
    # principal so the same source still works in environments where the app
    # service principal has explicit Unity Catalog privileges.
    user_access_token = None
    try:
        user_access_token = st.context.headers.get("x-forwarded-access-token")
    except Exception:
        user_access_token = None

    if user_access_token:
        return sql.connect(
            server_hostname=server_hostname,
            http_path=WAREHOUSE_HTTP_PATH,
            access_token=user_access_token,
            _use_arrow_native_complex_types=False,
        )

    return sql.connect(
        server_hostname=server_hostname,
        http_path=WAREHOUSE_HTTP_PATH,
        credentials_provider=lambda: cfg.authenticate,
        _use_arrow_native_complex_types=False,
    )


def run_query(query: str) -> pd.DataFrame:

    # Keep the SQL definitions readable while allowing the app to switch
    # between schemas via CFO_DATA_SCHEMA / CFO_DATA_CATALOG.
    query = query.replace("workspace.cfo_cockpit", DATA_NAMESPACE)

    with get_connection() as connection:

        with connection.cursor() as cursor:

            cursor.execute(query)

            return cursor.fetchall_arrow().to_pandas()


# ============================================================
# GENIE CFO COPILOT
# ============================================================

# Configure the Genie Agent/Space ID through the App environment.
# Keep environment-specific resource IDs out of GitHub source code.
# Example app.yaml pattern:
# env:
#   - name: GENIE_SPACE_ID
#     valueFrom: genie-space

GENIE_SPACE_ID = os.getenv("GENIE_SPACE_ID")

workspace_client = WorkspaceClient(config=cfg)


def _enum_text(value):
    """Return a stable string for SDK enum-like objects."""
    if value is None:
        return ""
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def extract_genie_payload(response):
    """
    Extract the user-facing answer, generated SQL, and suggested
    follow-up questions from a completed Genie message.

    Genie can return multiple attachment types. We prefer text
    attachments marked as the final ANSWER and fall back to any
    available text attachment when needed.
    """

    attachments = getattr(response, "attachments", None) or []

    answer_texts = []
    fallback_texts = []
    generated_queries = []
    suggested_questions = []

    for attachment in attachments:

        # ----------------------------------------------------
        # TEXT RESPONSE
        # ----------------------------------------------------
        text_attachment = getattr(attachment, "text", None)

        if text_attachment is not None:

            content = getattr(text_attachment, "content", None)
            purpose = _enum_text(
                getattr(text_attachment, "purpose", None)
            ).upper()

            if content:

                fallback_texts.append(str(content))

                if "ANSWER" in purpose:
                    answer_texts.append(str(content))

        # ----------------------------------------------------
        # GENERATED SQL
        # ----------------------------------------------------
        query_attachment = getattr(attachment, "query", None)

        if query_attachment is not None:

            sql_text = getattr(query_attachment, "query", None)

            if sql_text:

                generated_queries.append(
                    {
                        "title": (
                            getattr(
                                query_attachment,
                                "title",
                                None,
                            )
                            or "Genie SQL"
                        ),
                        "description": (
                            getattr(
                                query_attachment,
                                "description",
                                None,
                            )
                            or ""
                        ),
                        "sql": str(sql_text),
                    }
                )

        # ----------------------------------------------------
        # SUGGESTED FOLLOW-UPS
        # ----------------------------------------------------
        suggestions = getattr(
            attachment,
            "suggested_questions",
            None,
        )

        if suggestions is not None:

            questions = getattr(
                suggestions,
                "questions",
                None,
            ) or []

            suggested_questions.extend(
                [
                    str(question)
                    for question in questions
                    if question
                ]
            )

    answer = "\n\n".join(
        answer_texts or fallback_texts
    ).strip()

    if not answer:

        error = getattr(response, "error", None)

        if error is not None:
            error_text = getattr(error, "error", None)
            if error_text:
                answer = (
                    "Genie could not complete the request: "
                    f"{error_text}"
                )

    if not answer:
        answer = (
            "Genie completed the request but did not return "
            "a text answer."
        )

    # Keep ordering but remove duplicates.
    unique_suggestions = list(
        dict.fromkeys(suggested_questions)
    )

    return (
        answer,
        generated_queries,
        unique_suggestions,
    )


def ask_cfo_genie(question: str):
    """
    Start a new Genie conversation or continue the current
    Streamlit-session conversation.
    """

    if not GENIE_SPACE_ID:
        raise RuntimeError(
            "GENIE_SPACE_ID is not configured. Add the Genie Agent as an App resource "
            "and expose its ID through the GENIE_SPACE_ID environment variable."
        )

    conversation_id = st.session_state.get(
        "cfo_genie_conversation_id"
    )

    if conversation_id:

        response = (
            workspace_client.genie.create_message_and_wait(
                space_id=GENIE_SPACE_ID,
                conversation_id=conversation_id,
                content=question,
            )
        )

    else:

        response = (
            workspace_client.genie.start_conversation_and_wait(
                space_id=GENIE_SPACE_ID,
                content=question,
            )
        )

        st.session_state[
            "cfo_genie_conversation_id"
        ] = response.conversation_id

    return extract_genie_payload(response)


COPILOT_RESPONSE_MODE = """
Respond as an executive CFO decision partner, not as a customer-service chatbot.
Use prior conversation context and do not ask the CFO to restate facts that were just discussed.
Lead with a short **Decision view**. Then use concise sections for **Evidence**, **Implication**,
and **Next moves**. When the user asks what the bank should do, take a position when the
certified evidence supports one; otherwise state the key uncertainty and propose the smallest
next investigation needed. Distinguish observed facts from interpretation and do not invent
causality. Keep the answer senior-executive concise. Do not use emojis.
""".strip()


def build_copilot_request(question: str) -> str:
    """Add lightweight recent context and CFO response discipline for Genie."""

    history = st.session_state.get("cfo_copilot_messages", [])
    context_lines = []

    for message in history[-4:]:
        content = str(message.get("content", "")).strip()
        if not content:
            continue

        # Preserve just enough prior context to make follow-up questions reliable
        # without bloating the Genie request.
        content = content[:1200]
        speaker = "CFO" if message.get("role") == "user" else "CFO AI"
        context_lines.append(f"{speaker}: {content}")

    context_block = "\n".join(context_lines)

    if context_block:
        return (
            f"Current CFO question:\n{question}\n\n"
            f"Recent conversation context:\n{context_block}\n\n"
            f"{COPILOT_RESPONSE_MODE}"
        )

    return f"Current CFO question:\n{question}\n\n{COPILOT_RESPONSE_MODE}"


# ============================================================
# LOAD LIVE DATA
# ============================================================

connection_ok = False
connection_error = None

# Certified source-of-truth datasets used by the radial shell and Morning Brief.
current_position_df = None
financial_history_df = None
monthly_nim_cert_df = None
deposit_country_df = None
credit_detail_df = None
credit_trend_df = None
news_recent_df = None
geo_news_df = None
daily_latest_df = None
daily_recent_df = None
daily_country_df = None
daily_business_country_df = None
treasury_summary_df = None
treasury_rate50_df = None
treasury_snapshot_history_df = None
treasury_scenarios_df = None
hedge_options_df = None
peer_benchmark_df = None
peer_benchmarks_df = None
strategic_radar_df = None
capability_gaps_df = None

# Horizon is now derived from the certified actuals through a deterministic
# run-rate baseline in this app. It no longer depends on the legacy Horizon view.

try:

    # --------------------------------------------------------
    # CERTIFIED CURRENT POSITION
    # --------------------------------------------------------

    current_position_df = run_query(
        """
        SELECT
            as_of_date,
            loans_m,
            deposits_m,
            total_assets_m,
            rwa_m,
            cet1_capital_m,
            cet1_ratio_pct,
            total_capital_ratio_pct,
            hqla_m,
            lcr_pct,
            loan_to_deposit_pct,
            ytd_nii_m,
            ytd_net_profit_m,
            ytd_cost_income_ratio_pct,
            annualised_ytd_roe_proxy_pct,
            months_observed
        FROM workspace.cfo_cockpit.cfo_current_position
        """
    )

    if current_position_df.empty:
        raise ValueError("cfo_current_position returned no rows.")

    current_position = current_position_df.iloc[0]

    # --------------------------------------------------------
    # CERTIFIED FINANCIAL HISTORY
    # Used for genuine month-over-month and YTD trend context.
    # --------------------------------------------------------

    financial_history_df = run_query(
        """
        SELECT
            date,
            deposits_m,
            stage_2_share_pct,
            stage_3_share_pct,
            cet1_capital_m,
            cet1_ratio_pct,
            lcr_pct,
            loan_to_deposit_pct,
            nii_m,
            operating_income_m,
            operating_costs_m,
            net_profit_m
        FROM workspace.cfo_cockpit.cfo_financial_history
        ORDER BY date
        """
    )

    if financial_history_df.empty:
        raise ValueError("cfo_financial_history returned no rows.")

    # --------------------------------------------------------
    # CERTIFIED MONTHLY NIM
    # --------------------------------------------------------

    monthly_nim_cert_df = run_query(
        """
        SELECT
            month,
            monthly_nii_m,
            avg_interest_earning_assets_m,
            nim_pct
        FROM workspace.cfo_cockpit.cfo_monthly_nim
        ORDER BY month
        """
    )

    if monthly_nim_cert_df.empty:
        raise ValueError("cfo_monthly_nim returned no rows.")

    # --------------------------------------------------------
    # CERTIFIED DEPOSIT MOVEMENTS BY COUNTRY
    # Correct stock aggregation: aggregate balances and absolute
    # changes first, then calculate the percentage change.
    # --------------------------------------------------------

    deposit_country_df = run_query(
        """
        WITH latest AS (
            SELECT MAX(date) AS latest_date
            FROM workspace.cfo_cockpit.cfo_deposit_signals
        )
        SELECT
            country,
            SUM(deposit_balance_m) AS deposit_balance_m,
            SUM(deposit_change_30d_m) AS deposit_change_30d_m,
            CASE
                WHEN SUM(deposit_balance_m) - SUM(deposit_change_30d_m) <> 0
                THEN 100.0 * SUM(deposit_change_30d_m)
                    / (SUM(deposit_balance_m) - SUM(deposit_change_30d_m))
            END AS deposit_change_30d_pct
        FROM workspace.cfo_cockpit.cfo_deposit_signals
        CROSS JOIN latest
        WHERE date = latest.latest_date
        GROUP BY country
        ORDER BY deposit_change_30d_pct DESC
        """
    )

    # --------------------------------------------------------
    # CERTIFIED CREDIT SIGNALS — latest country/business rows
    # --------------------------------------------------------

    credit_detail_df = run_query(
        """
        SELECT
            date,
            country,
            business_line,
            loan_balance_m,
            weighted_stage_1_share_pct,
            weighted_stage_2_share_pct,
            weighted_stage_3_share_pct,
            credit_watch_flag
        FROM workspace.cfo_cockpit.cfo_credit_signals
        WHERE date = (
            SELECT MAX(date)
            FROM workspace.cfo_cockpit.cfo_credit_signals
        )
        ORDER BY
            credit_watch_flag DESC,
            weighted_stage_2_share_pct DESC,
            weighted_stage_3_share_pct DESC
        """
    )


    credit_trend_df = run_query(
        """
        WITH max_date AS (
            SELECT MAX(date) AS latest_date
            FROM workspace.cfo_cockpit.cfo_credit_signals
        )
        SELECT
            c.date,
            c.country,
            c.business_line,
            c.loan_balance_m,
            c.weighted_stage_2_share_pct,
            c.weighted_stage_3_share_pct,
            c.credit_watch_flag
        FROM workspace.cfo_cockpit.cfo_credit_signals c
        CROSS JOIN max_date m
        WHERE c.date IN (m.latest_date, DATE_SUB(m.latest_date, 30))
        """
    )

    # --------------------------------------------------------
    # CERTIFIED EXTERNAL INTELLIGENCE — one row per article
    # --------------------------------------------------------

    news_recent_df = run_query(
        """
        WITH ranked AS (
            SELECT
                news_id,
                published_date,
                headline,
                source,
                source_url,
                category,
                primary_affected_metric,
                impact_direction,
                potential_impact_level,
                relevance_score,
                bank_impact_summary,
                suggested_action,
                country,
                geo_impact_score,
                ROW_NUMBER() OVER (
                    PARTITION BY news_id
                    ORDER BY geo_impact_score DESC, country
                ) AS rn
            FROM workspace.cfo_cockpit.cfo_news_intelligence
            WHERE published_date >= (
                SELECT DATE_SUB(MAX(published_date), 13)
                FROM workspace.cfo_cockpit.cfo_news_intelligence
            )
        )
        SELECT
            news_id,
            published_date,
            headline,
            source,
            source_url,
            category,
            primary_affected_metric,
            impact_direction,
            potential_impact_level,
            relevance_score,
            bank_impact_summary,
            suggested_action,
            country,
            geo_impact_score
        FROM ranked
        WHERE rn = 1
        ORDER BY relevance_score DESC, published_date DESC
        """
    )

    geo_news_df = run_query(
        """
        SELECT
            country,
            country_code,
            relevant_news_count,
            high_impact_news_count,
            medium_impact_news_count,
            geo_attention_score,
            latest_news_date
        FROM workspace.cfo_cockpit.cfo_geo_news_summary
        ORDER BY geo_attention_score DESC
        """
    )

    daily_latest_df = run_query(
        """
        SELECT
            date,
            daily_nii_m,
            annualised_daily_nim_pct,
            weighted_loan_rate_pct,
            weighted_deposit_rate_pct,
            ecb_rate_pct,
            has_anomaly
        FROM workspace.cfo_cockpit.cfo_daily_bank
        ORDER BY date DESC
        LIMIT 1
        """
    )


    daily_recent_df = run_query(
        """
        SELECT
            date,
            daily_nii_m,
            annualised_daily_nim_pct,
            weighted_loan_rate_pct,
            weighted_deposit_rate_pct,
            ecb_rate_pct
        FROM workspace.cfo_cockpit.cfo_daily_bank
        WHERE date >= DATE_SUB(
            (SELECT MAX(date) FROM workspace.cfo_cockpit.cfo_daily_bank),
            30
        )
        ORDER BY date
        """
    )

    # --------------------------------------------------------
    # CERTIFIED COUNTRY / BUSINESS-COUNTRY DRILLDOWNS
    # Retained as governed sources for geographic and business-line analysis.
    # --------------------------------------------------------

    daily_country_df = run_query(
        """
        SELECT
            date,
            country,
            interest_earning_assets_m,
            deposit_balance_m,
            daily_interest_income_m,
            daily_interest_expense_m,
            daily_nii_m,
            weighted_loan_rate_pct,
            weighted_deposit_rate_pct,
            annualised_daily_nim_pct,
            rwa_m,
            weighted_stage_2_share_pct,
            weighted_stage_3_share_pct,
            has_anomaly
        FROM workspace.cfo_cockpit.cfo_daily_country
        WHERE date = (
            SELECT MAX(date)
            FROM workspace.cfo_cockpit.cfo_daily_country
        )
        ORDER BY country
        """
    )

    daily_business_country_df = run_query(
        """
        SELECT
            date,
            country,
            business_line,
            interest_earning_assets_m,
            deposit_balance_m,
            daily_nii_m,
            rwa_m,
            weighted_stage_2_share_pct,
            weighted_stage_3_share_pct,
            has_anomaly
        FROM workspace.cfo_cockpit.cfo_daily_business_country
        WHERE date = (
            SELECT MAX(date)
            FROM workspace.cfo_cockpit.cfo_daily_business_country
        )
        ORDER BY country, business_line
        """
    )

    # --------------------------------------------------------
    # CERTIFIED TREASURY PULSE
    # Used as a secondary intelligence readout around the radial core.
    # --------------------------------------------------------

    treasury_summary_df = run_query(
        """
        SELECT
            as_of_date,
            market_value_m,
            unrealized_pnl_m,
            weighted_modified_duration,
            portfolio_dv01_m_per_bp,
            fvoci_market_value_m,
            amortised_cost_market_value_m
        FROM workspace.cfo_cockpit.cfo_treasury_summary
        """
    )

    treasury_rate50_df = run_query(
        """
        SELECT
            scenario_name,
            economic_value_impact_m,
            economic_value_impact_pct,
            estimated_oci_impact_m,
            estimated_immediate_pnl_impact_m
        FROM workspace.cfo_cockpit.cfo_treasury_scenarios
        WHERE rate_shock_bps = 50
          AND COALESCE(credit_spread_shock_bps, 0) = 0
        ORDER BY scenario_name
        LIMIT 1
        """
    )

    # --------------------------------------------------------
    # TREASURY SNAPSHOT TREND + SCENARIO / HEDGE DETAIL
    # --------------------------------------------------------

    # Snapshot history is used only when a prior observation exists.
    # If the prototype contains a single treasury snapshot, the UI
    # explicitly reports that a day-over-day comparison is unavailable.
    treasury_snapshot_history_df = run_query(
        """
        SELECT
            CAST(as_of_date AS DATE) AS as_of_date,
            SUM(CAST(market_value_m AS DOUBLE)) AS market_value_m
        FROM workspace.cfo_cockpit.raw_treasury_portfolio
        GROUP BY CAST(as_of_date AS DATE)
        ORDER BY as_of_date DESC
        LIMIT 2
        """
    )

    treasury_scenarios_df = run_query(
        """
        SELECT
            scenario_name,
            scenario_description,
            rate_shock_bps,
            credit_spread_shock_bps,
            economic_value_impact_m,
            economic_value_impact_pct,
            estimated_oci_impact_m,
            estimated_immediate_pnl_impact_m
        FROM workspace.cfo_cockpit.cfo_treasury_scenarios
        ORDER BY economic_value_impact_m
        """
    )

    hedge_options_df = run_query(
        """
        SELECT
            hedge_id,
            hedge_name,
            hedge_instrument,
            hedge_notional_m,
            portfolio_dv01_before_m_per_bp,
            portfolio_dv01_after_m_per_bp,
            dv01_reduction_pct,
            rates_plus_50bp_pnl_before_m,
            estimated_hedge_gain_plus_50bp_m,
            rates_plus_50bp_pnl_after_m,
            estimated_annual_carry_m
        FROM workspace.cfo_cockpit.cfo_hedge_options
        ORDER BY dv01_reduction_pct DESC
        """
    )

    # --------------------------------------------------------
    # PEER INTELLIGENCE
    # --------------------------------------------------------

    peer_benchmark_df = run_query(
        """
        SELECT
            bank_name,
            home_market,
            total_assets_m,
            reported_return_pct,
            return_metric_type,
            cet1_ratio_pct,
            cost_income_ratio_pct,
            profitability_peer_median_pct,
            cet1_peer_median_pct,
            cost_income_peer_median_pct,
            positioning_quadrant,
            comparison_caveat,
            source_url
        FROM workspace.cfo_cockpit.cfo_peer_benchmark
        ORDER BY reported_return_pct DESC
        """
    )

    peer_benchmarks_df = run_query(
        """
        SELECT
            metric,
            metric_label,
            peer_count,
            peer_min,
            peer_q1,
            peer_median,
            peer_q3,
            peer_max,
            benchmark_note
        FROM workspace.cfo_cockpit.cfo_peer_benchmarks
        ORDER BY metric
        """
    )

    # --------------------------------------------------------
    # STRATEGIC RADAR
    # --------------------------------------------------------

    strategic_radar_df = run_query(
        """
        SELECT
            opportunity_rank,
            company_name,
            headquarters_country,
            capability_domain,
            public_scale_metric,
            public_source_url,
            strategic_gap_addressed,
            preferred_route,
            strategic_fit_score,
            financial_attractiveness_score,
            integration_feasibility_score,
            affordability_score,
            regulatory_complexity_score,
            innovation_score,
            time_to_value_score,
            size_score,
            overall_opportunity_score,
            radar_status,
            strategic_rationale,
            key_risk,
            scores_are_synthetic
        FROM workspace.cfo_cockpit.cfo_strategic_radar
        ORDER BY opportunity_rank
        """
    )

    capability_gaps_df = run_query(
        """
        SELECT
            capability,
            current_score,
            target_score,
            capability_gap,
            priority,
            benchmark_direction,
            linked_companies,
            strategic_objective,
            scores_are_synthetic
        FROM workspace.cfo_cockpit.cfo_capability_gaps
        ORDER BY capability_gap DESC
        """
    )

    # --------------------------------------------------------
    # CORE LOAD COMPLETE
    # --------------------------------------------------------


    connection_ok = True

except Exception as e:

    connection_error = e


# ============================================================
# STYLING
# ============================================================

render_html(
    """
    <style>

        :root {
            --void: #02070c;
            --void-soft: #06111a;
            --panel: rgba(5, 22, 33, 0.82);
            --panel-strong: rgba(6, 29, 43, 0.94);
            --line: rgba(80, 222, 255, 0.18);
            --line-strong: rgba(80, 222, 255, 0.42);
            --cyan: #52e7ff;
            --cyan-soft: #9af2ff;
            --blue: #3b82f6;
            --violet: #b88cff;
            --green: #42f5a7;
            --amber: #ffcb66;
            --red: #ff5d7a;
            --text: #e9fbff;
            --muted: #7fa6b5;
        }

        html, body, [class*="css"] {
            font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
        }

        .stApp {
            color: var(--text);
            background:
                radial-gradient(circle at 82% 4%, rgba(16, 121, 164, 0.18), transparent 28rem),
                radial-gradient(circle at 12% 35%, rgba(34, 86, 147, 0.10), transparent 34rem),
                linear-gradient(135deg, #02070c 0%, #04101a 48%, #02070c 100%);
        }

        .stApp::before {
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            z-index: 0;
            opacity: 0.34;
            background-image:
                linear-gradient(rgba(82, 231, 255, 0.026) 1px, transparent 1px),
                linear-gradient(90deg, rgba(82, 231, 255, 0.026) 1px, transparent 1px);
            background-size: 44px 44px;
            mask-image: linear-gradient(to bottom, black, transparent 92%);
        }

        .stApp::after {
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            z-index: 0;
            opacity: 0.11;
            background: repeating-linear-gradient(
                0deg,
                rgba(255,255,255,0.04) 0px,
                rgba(255,255,255,0.04) 1px,
                transparent 1px,
                transparent 4px
            );
        }

        header[data-testid="stHeader"] {
            background: linear-gradient(180deg, rgba(2, 7, 12, 0.96), rgba(2, 7, 12, 0));
        }

        [data-testid="stToolbar"] {
            right: 1.25rem;
        }

        .block-container {
            position: relative;
            z-index: 1;
            padding-top: 3.7rem !important;
            padding-bottom: 3rem !important;
            max-width: 1580px;
        }

        div[data-testid="stMainBlockContainer"],
        div[data-testid="stAppViewBlockContainer"] {
            padding-top: 3.7rem !important;
        }

        #MainMenu, footer {
            visibility: hidden;
        }

        hr {
            border-color: rgba(82, 231, 255, 0.12) !important;
        }

        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] li {
            color: #b8d4dc;
        }

        [data-testid="stMarkdownContainer"] h1,
        [data-testid="stMarkdownContainer"] h2,
        [data-testid="stMarkdownContainer"] h3,
        [data-testid="stMarkdownContainer"] h4 {
            color: #e9fbff;
            letter-spacing: -0.02em;
        }

        /* -------------------------------------------------
           HERO / COMMAND HEADER
           ------------------------------------------------- */

        .hud-hero {
            position: relative;
            min-height: 248px;
            display: grid;
            grid-template-columns: minmax(0, 1.55fr) minmax(260px, 0.7fr);
            align-items: center;
            gap: 2rem;
            overflow: hidden;
            padding: 2.1rem 2.35rem;
            margin: 0 0 1.3rem 0;
            background:
                linear-gradient(105deg, rgba(5, 27, 41, 0.94), rgba(3, 14, 23, 0.72)),
                radial-gradient(circle at 79% 50%, rgba(82, 231, 255, 0.15), transparent 13rem);
            border: 1px solid var(--line-strong);
            clip-path: polygon(0 0, calc(100% - 30px) 0, 100% 30px, 100% 100%, 30px 100%, 0 calc(100% - 30px));
            box-shadow:
                inset 0 0 55px rgba(42, 186, 230, 0.055),
                0 22px 70px rgba(0, 0, 0, 0.34);
        }

        .hud-hero::before {
            content: "";
            position: absolute;
            top: 0;
            left: -45%;
            width: 42%;
            height: 2px;
            background: linear-gradient(90deg, transparent, var(--cyan), transparent);
            box-shadow: 0 0 18px var(--cyan);
            animation: scan-horizontal 7s linear infinite;
        }

        .hud-hero::after {
            content: "";
            position: absolute;
            inset: 12px;
            pointer-events: none;
            opacity: 0.65;
            background:
                linear-gradient(var(--cyan), var(--cyan)) left top / 45px 1px no-repeat,
                linear-gradient(var(--cyan), var(--cyan)) left top / 1px 45px no-repeat,
                linear-gradient(var(--cyan), var(--cyan)) right bottom / 45px 1px no-repeat,
                linear-gradient(var(--cyan), var(--cyan)) right bottom / 1px 45px no-repeat;
        }

        .hero-copy, .hero-core {
            position: relative;
            z-index: 2;
        }

        .system-kicker,
        .module-code,
        .kpi-label,
        .scenario-summary-label,
        .readout-label {
            font-family: "Cascadia Mono", "SFMono-Regular", Consolas, monospace;
            text-transform: uppercase;
            letter-spacing: 0.16em;
        }

        .system-kicker {
            display: flex;
            align-items: center;
            gap: 0.65rem;
            color: var(--cyan);
            font-size: 0.70rem;
            font-weight: 700;
            margin-bottom: 0.8rem;
        }

        .system-kicker::before {
            content: "";
            width: 28px;
            height: 1px;
            background: var(--cyan);
            box-shadow: 0 0 10px var(--cyan);
        }

        .hero-title {
            margin: 0;
            color: #f2fdff;
            font-size: clamp(2.35rem, 4.5vw, 4.85rem);
            line-height: 0.94;
            font-weight: 300;
            letter-spacing: -0.055em;
            text-shadow: 0 0 34px rgba(82, 231, 255, 0.13);
        }

        .hero-title strong {
            color: var(--cyan);
            font-weight: 780;
            letter-spacing: 0.035em;
        }

        .hero-subtitle {
            max-width: 690px;
            margin-top: 1rem;
            color: #9bbdca;
            font-size: 0.96rem;
            line-height: 1.65;
        }

        .hero-status-row {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 0.6rem;
            margin-top: 1.35rem;
        }

        .status-pill, .data-pill {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            padding: 0.38rem 0.72rem;
            border: 1px solid rgba(82, 231, 255, 0.24);
            background: rgba(82, 231, 255, 0.055);
            color: #aeeffc;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.66rem;
            font-weight: 700;
            letter-spacing: 0.095em;
            text-transform: uppercase;
            clip-path: polygon(8px 0, 100% 0, 100% calc(100% - 8px), calc(100% - 8px) 100%, 0 100%, 0 8px);
        }

        .status-dot {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: var(--green);
            box-shadow: 0 0 0 4px rgba(66, 245, 167, 0.10), 0 0 12px var(--green);
            animation: pulse-dot 1.9s ease-in-out infinite;
        }

        .hero-core {
            min-height: 190px;
            display: grid;
            place-items: center;
        }

        .arc-orb {
            position: relative;
            width: 176px;
            height: 176px;
            display: grid;
            place-items: center;
            border-radius: 50%;
            background:
                radial-gradient(circle, rgba(225, 252, 255, 0.98) 0 4%, var(--cyan) 5% 9%, rgba(82,231,255,0.17) 10% 24%, rgba(8,31,44,0.92) 25% 42%, transparent 43%),
                conic-gradient(from 25deg, transparent 0 8%, rgba(82,231,255,0.92) 9% 13%, transparent 14% 29%, rgba(82,231,255,0.42) 30% 33%, transparent 34% 61%, rgba(82,231,255,0.85) 62% 68%, transparent 69% 86%, rgba(82,231,255,0.42) 87% 90%, transparent 91%);
            border: 1px solid rgba(82, 231, 255, 0.55);
            box-shadow:
                0 0 24px rgba(82,231,255,0.40),
                0 0 80px rgba(44,171,215,0.20),
                inset 0 0 28px rgba(82,231,255,0.24);
            animation: orb-breathe 3.5s ease-in-out infinite;
        }

        .arc-orb::before,
        .arc-orb::after {
            content: "";
            position: absolute;
            border-radius: 50%;
        }

        .arc-orb::before {
            inset: -13px;
            border: 1px dashed rgba(82, 231, 255, 0.42);
            animation: rotate-cw 18s linear infinite;
        }

        .arc-orb::after {
            inset: 20px;
            border: 1px solid rgba(185, 244, 255, 0.34);
            border-left-color: transparent;
            border-right-color: transparent;
            animation: rotate-ccw 7s linear infinite;
        }

        .orb-readout {
            position: relative;
            z-index: 2;
            text-align: center;
            color: #eaffff;
            text-shadow: 0 0 12px var(--cyan);
        }

        .orb-number {
            display: block;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 1.75rem;
            font-weight: 750;
            line-height: 1;
        }

        .orb-label {
            display: block;
            margin-top: 0.35rem;
            color: var(--cyan-soft);
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.51rem;
            letter-spacing: 0.14em;
            text-transform: uppercase;
        }

        /* -------------------------------------------------
           SECTION AND MODULE LANGUAGE
           ------------------------------------------------- */

        .section-heading {
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 1rem;
            margin: 1.1rem 0 1rem 0;
        }

        .section-title {
            display: flex;
            align-items: center;
            gap: 0.7rem;
            margin: 0 0 0.8rem 0;
            color: #e8fbff;
            font-size: 1.12rem;
            font-weight: 650;
            letter-spacing: 0.01em;
        }

        .section-title::before {
            content: "";
            width: 10px;
            height: 10px;
            background: var(--cyan);
            clip-path: polygon(50% 0, 100% 50%, 50% 100%, 0 50%);
            box-shadow: 0 0 14px var(--cyan);
        }

        .section-subtitle {
            max-width: 760px;
            color: var(--muted);
            font-size: 0.88rem;
            line-height: 1.55;
            margin: -0.25rem 0 1.2rem 0;
        }

        .module-code {
            color: var(--cyan);
            font-size: 0.61rem;
            font-weight: 750;
        }

        .attention-line {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 1rem;
            padding: 0.2rem 0 0.45rem 0;
        }

        .attention-copy {
            color: #cce8ef;
            font-size: 1.05rem;
        }

        .attention-copy strong {
            color: var(--cyan);
            font-size: 1.35rem;
            text-shadow: 0 0 15px rgba(82, 231, 255, 0.35);
        }

        .sync-copy {
            color: #547b8b;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.63rem;
            letter-spacing: 0.09em;
            text-transform: uppercase;
        }

        /* -------------------------------------------------
           KPI MODULES
           ------------------------------------------------- */

        .kpi-card {
            position: relative;
            min-height: 166px;
            overflow: hidden;
            padding: 1.25rem 1.35rem 1.15rem;
            background:
                linear-gradient(145deg, rgba(8, 34, 49, 0.94), rgba(3, 17, 27, 0.90)),
                radial-gradient(circle at 100% 0%, rgba(82,231,255,0.12), transparent 45%);
            border: 1px solid rgba(82, 231, 255, 0.20);
            clip-path: polygon(0 0, calc(100% - 20px) 0, 100% 20px, 100% 100%, 13px 100%, 0 calc(100% - 13px));
            box-shadow: inset 0 0 32px rgba(47, 201, 244, 0.025);
            transition: transform 180ms ease, border-color 180ms ease, background 180ms ease;
        }

        .kpi-card:hover {
            transform: translateY(-3px);
            border-color: rgba(82, 231, 255, 0.48);
            background:
                linear-gradient(145deg, rgba(9, 39, 56, 0.98), rgba(3, 18, 29, 0.94)),
                radial-gradient(circle at 100% 0%, rgba(82,231,255,0.17), transparent 48%);
        }

        .kpi-card::before {
            content: "";
            position: absolute;
            left: 0;
            top: 0;
            width: 34%;
            height: 2px;
            background: linear-gradient(90deg, var(--cyan), transparent);
            box-shadow: 0 0 12px rgba(82,231,255,0.55);
        }

        .kpi-card::after {
            content: attr(data-module);
            position: absolute;
            top: 0.86rem;
            right: 1rem;
            color: rgba(134, 205, 222, 0.30);
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.54rem;
            letter-spacing: 0.14em;
        }

        .kpi-card:has(.kpi-alert)::before {
            background: linear-gradient(90deg, var(--red), transparent);
            box-shadow: 0 0 12px rgba(255,93,122,0.55);
        }

        .kpi-card:has(.kpi-watch)::before {
            background: linear-gradient(90deg, var(--amber), transparent);
            box-shadow: 0 0 12px rgba(255,203,102,0.50);
        }

        .kpi-card:has(.kpi-track)::before {
            background: linear-gradient(90deg, var(--green), transparent);
            box-shadow: 0 0 12px rgba(66,245,167,0.46);
        }

        .kpi-label {
            color: #78a4b4;
            font-size: 0.65rem;
            font-weight: 750;
            margin-bottom: 0.65rem;
        }

        .kpi-value {
            color: #f0fdff;
            font-family: "Cascadia Mono", "Segoe UI", monospace;
            font-size: clamp(1.85rem, 3vw, 2.65rem);
            font-weight: 560;
            line-height: 1.08;
            letter-spacing: -0.055em;
            text-shadow: 0 0 24px rgba(82,231,255,0.16);
        }

        .kpi-alert, .kpi-watch, .kpi-track {
            display: flex;
            align-items: center;
            gap: 0.45rem;
            margin-top: 0.78rem;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.015em;
        }

        .kpi-alert { color: var(--red); }
        .kpi-watch { color: var(--amber); }
        .kpi-track { color: var(--green); }

        .micro-line {
            position: absolute;
            right: 1.2rem;
            bottom: 1.15rem;
            width: 54px;
            height: 18px;
            opacity: 0.52;
            background: linear-gradient(155deg, transparent 0 15%, var(--cyan) 16% 19%, transparent 20% 34%, var(--cyan) 35% 39%, transparent 40% 51%, var(--cyan) 52% 56%, transparent 57% 70%, var(--cyan) 71% 75%, transparent 76%);
            clip-path: polygon(0 83%, 18% 58%, 33% 70%, 52% 20%, 68% 43%, 83% 8%, 100% 28%, 100% 100%, 0 100%);
            filter: drop-shadow(0 0 5px var(--cyan));
        }

        /* -------------------------------------------------
           PANELS / BRIEFINGS
           ------------------------------------------------- */

        .panel, .scenario-panel {
            position: relative;
            overflow: hidden;
            padding: 1.2rem 1.3rem;
            color: #c9e1e8;
            background: linear-gradient(145deg, rgba(7, 29, 42, 0.88), rgba(3, 17, 26, 0.82));
            border: 1px solid rgba(82, 231, 255, 0.17);
            clip-path: polygon(0 0, calc(100% - 15px) 0, 100% 15px, 100% 100%, 0 100%);
        }

        .panel::after, .scenario-panel::after {
            content: "";
            position: absolute;
            right: 0;
            top: 0;
            width: 38px;
            height: 1px;
            background: var(--cyan);
            box-shadow: 0 0 10px var(--cyan);
        }

        .scenario-panel {
            margin-top: 1rem;
            background:
                linear-gradient(145deg, rgba(8, 37, 53, 0.90), rgba(4, 19, 30, 0.88)),
                radial-gradient(circle at 92% 15%, rgba(82,231,255,0.11), transparent 45%);
        }

        .scenario-title {
            color: #e7fbff;
            font-size: 0.96rem;
            font-weight: 680;
            letter-spacing: 0.015em;
            margin-bottom: 0.45rem;
        }

        .scenario-description {
            color: #83a9b7;
            font-size: 0.84rem;
            line-height: 1.55;
        }

        .scenario-badge {
            display: inline-flex;
            align-items: center;
            margin-top: 0.85rem;
            padding: 0.28rem 0.58rem;
            color: var(--cyan-soft);
            background: rgba(82, 231, 255, 0.06);
            border: 1px solid rgba(82, 231, 255, 0.25);
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.58rem;
            font-weight: 750;
            letter-spacing: 0.12em;
            clip-path: polygon(6px 0, 100% 0, 100% calc(100% - 6px), calc(100% - 6px) 100%, 0 100%, 0 6px);
        }

        .alert-card {
            position: relative;
            min-height: 94px;
            padding: 1rem 1rem 0.95rem 3.65rem;
            margin-bottom: 0.72rem;
            background: linear-gradient(100deg, rgba(8, 31, 44, 0.92), rgba(4, 17, 27, 0.78));
            border: 1px solid rgba(120, 204, 223, 0.13);
            border-left: 2px solid;
            clip-path: polygon(0 0, calc(100% - 12px) 0, 100% 12px, 100% 100%, 0 100%);
        }

        .alert-card::before {
            content: attr(data-index);
            position: absolute;
            left: 1rem;
            top: 1rem;
            width: 1.8rem;
            height: 1.8rem;
            display: grid;
            place-items: center;
            border: 1px solid currentColor;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.66rem;
            clip-path: polygon(50% 0, 100% 28%, 100% 72%, 50% 100%, 0 72%, 0 28%);
        }

        .alert-red { border-left-color: var(--red); color: var(--red); }
        .alert-amber { border-left-color: var(--amber); color: var(--amber); }
        .alert-green { border-left-color: var(--green); color: var(--green); }

        .alert-title {
            color: #e7f8fb;
            font-size: 0.87rem;
            font-weight: 680;
            margin-bottom: 0.3rem;
        }

        .alert-text {
            color: #83a8b5;
            font-size: 0.81rem;
            line-height: 1.45;
        }

        .scenario-summary {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 0.65rem;
            margin-top: 1rem;
        }

        .scenario-summary-item {
            position: relative;
            padding: 0.78rem 0.82rem;
            background: rgba(82, 231, 255, 0.035);
            border: 1px solid rgba(82, 231, 255, 0.13);
        }

        .scenario-summary-item::before {
            content: "";
            position: absolute;
            left: 0;
            top: 0;
            width: 14px;
            height: 1px;
            background: var(--cyan);
        }

        .scenario-summary-label {
            color: #648d9c;
            font-size: 0.56rem;
            font-weight: 700;
        }

        .scenario-summary-value {
            margin-top: 0.32rem;
            color: #e6faff;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.95rem;
            font-weight: 650;
        }

        .horizon-grid {
            display: grid;
            gap: 0.82rem;
        }

        .horizon-readout {
            display: flex;
            align-items: flex-end;
            justify-content: space-between;
            gap: 0.5rem;
            padding-bottom: 0.78rem;
            border-bottom: 1px solid rgba(82,231,255,0.10);
        }

        .horizon-readout:last-child {
            padding-bottom: 0;
            border-bottom: 0;
        }

        .nim-legend {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 1.45rem;
            margin: 0.15rem 0 0.8rem 0;
            color: #779eac;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.64rem;
            font-weight: 650;
            letter-spacing: 0.075em;
            text-transform: uppercase;
        }

        .legend-item {
            display: flex;
            align-items: center;
            gap: 0.48rem;
        }

        .legend-dot {
            width: 8px;
            height: 8px;
            display: inline-block;
            border-radius: 50%;
        }

        .legend-line {
            width: 25px;
            display: inline-block;
            border-top: 2px dashed;
        }

        .legend-actual {
            background: #52e7ff;
            box-shadow: 0 0 8px rgba(82,231,255,0.75);
        }

        .legend-budget { border-color: #577c8a; }
        .legend-forecast { border-color: #b88cff; }

        .diagnostic-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.7rem;
            padding: 0.25rem 0.2rem;
        }

        .diagnostic-item {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            min-width: 0;
            padding: 0.75rem;
            background: rgba(82,231,255,0.025);
            border: 1px solid rgba(82,231,255,0.09);
        }

        .diagnostic-value {
            overflow: hidden;
            margin-top: 0.18rem;
            color: #c8e5eb;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.67rem;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .readout-label {
            color: #608997;
            font-size: 0.57rem;
            font-weight: 700;
        }

        .readout-value {
            color: #eaffff;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 1.18rem;
            font-weight: 600;
        }

        /* -------------------------------------------------
           STREAMLIT-SAFE INTEGRATED COMMAND SYSTEM
           ------------------------------------------------- */

        .integrated-system {
            position: relative;
            max-width: 1450px;
            overflow: hidden;
            margin: 1.25rem auto 1.5rem;
            padding: 1rem 1.1rem 0.8rem;
            background:
                radial-gradient(circle at 50% 49%, rgba(0, 157, 220, 0.12), transparent 31rem),
                linear-gradient(135deg, rgba(2, 13, 21, 0.94), rgba(3, 20, 30, 0.78));
            border: 1px solid rgba(41, 191, 236, 0.18);
            clip-path: polygon(0 0, calc(100% - 22px) 0, 100% 22px, 100% 100%, 22px 100%, 0 calc(100% - 22px));
            box-shadow: inset 0 0 70px rgba(0, 139, 190, 0.035), 0 24px 70px rgba(0,0,0,0.30);
        }

        .integrated-system::before {
            content: "";
            position: absolute;
            inset: 0;
            z-index: 0;
            pointer-events: none;
            opacity: 0.28;
            background-image:
                linear-gradient(rgba(35, 182, 225, 0.035) 1px, transparent 1px),
                linear-gradient(90deg, rgba(35, 182, 225, 0.035) 1px, transparent 1px);
            background-size: 24px 24px;
            mask-image: radial-gradient(circle at 50% 50%, black 0 43%, transparent 78%);
        }

        .integrated-system::after {
            content: "";
            position: absolute;
            top: 0;
            left: -35%;
            z-index: 1;
            width: 30%;
            height: 1px;
            pointer-events: none;
            background: linear-gradient(90deg, transparent, #52e7ff, transparent);
            box-shadow: 0 0 15px rgba(82,231,255,0.8);
            animation: system-scan 8s linear infinite;
        }

        .system-topline {
            position: relative;
            z-index: 4;
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            align-items: center;
            gap: 1rem;
            padding: 0.15rem 0.25rem 0.65rem;
            color: #4a7483;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.54rem;
            font-weight: 700;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }

        .system-topline::before,
        .system-topline::after {
            content: "";
            height: 1px;
            background: linear-gradient(90deg, transparent, rgba(82,231,255,0.26));
        }

        .system-topline::after {
            background: linear-gradient(90deg, rgba(82,231,255,0.26), transparent);
        }

        .system-topline strong {
            color: #71dff3;
            font-weight: 750;
        }

        .system-grid {
            position: relative;
            z-index: 3;
            display: grid;
            grid-template-columns: minmax(255px, 0.78fr) minmax(590px, 1.72fr) minmax(275px, 0.84fr);
            align-items: center;
            gap: 1rem;
            min-height: 650px;
        }

        .dial-viewport {
            position: relative;
            z-index: 3;
            min-width: 0;
        }

        .dial-viewport::before {
            content: "";
            position: absolute;
            left: 50%;
            top: 50%;
            width: 74%;
            aspect-ratio: 1;
            transform: translate(-50%, -50%);
            border-radius: 50%;
            background: radial-gradient(circle, rgba(44,200,239,0.08), transparent 68%);
            filter: blur(12px);
            pointer-events: none;
        }

        .command-dial-html {
            position: relative;
            isolation: isolate;
            z-index: 2;
            width: min(100%, 680px);
            aspect-ratio: 1;
            margin: 0 auto;
            filter: drop-shadow(0 0 26px rgba(20, 158, 203, 0.11));
        }

        .command-dial-html::before {
            content: "";
            position: absolute;
            inset: 1.5%;
            z-index: 0;
            border: 1px solid rgba(82,231,255,0.18);
            border-radius: 50%;
            background:
                radial-gradient(circle, transparent 0 67%, rgba(20,152,196,0.035) 67.4% 68%, transparent 68.4%),
                radial-gradient(circle, rgba(23,168,211,0.08), transparent 69%);
            box-shadow:
                0 0 0 9px rgba(82,231,255,0.014),
                inset 0 0 48px rgba(20,171,217,0.055),
                0 0 48px rgba(20,171,217,0.05);
            pointer-events: none;
        }

        .command-dial-html::after {
            content: "";
            position: absolute;
            inset: 4.3%;
            z-index: 1;
            border: 1px dashed rgba(82,231,255,0.16);
            border-radius: 50%;
            pointer-events: none;
        }

        .dial-grid-disc-html {
            position: absolute;
            inset: 6.5%;
            z-index: 0;
            overflow: hidden;
            border: 1px solid rgba(82,231,255,0.08);
            border-radius: 50%;
            background:
                linear-gradient(rgba(82,231,255,0.035) 1px, transparent 1px),
                linear-gradient(90deg, rgba(82,231,255,0.035) 1px, transparent 1px),
                radial-gradient(circle, rgba(6,45,61,0.42), rgba(2,15,24,0.12) 61%, transparent 72%);
            background-size: 18px 18px, 18px 18px, auto;
            box-shadow: inset 0 0 72px rgba(0,0,0,0.62);
            pointer-events: none;
        }

        .dial-grid-disc-html::before,
        .dial-grid-disc-html::after {
            content: "";
            position: absolute;
            border-radius: 50%;
            pointer-events: none;
        }

        .dial-grid-disc-html::before {
            inset: 11%;
            border: 1px solid rgba(82,231,255,0.09);
            box-shadow:
                0 0 0 18px rgba(82,231,255,0.012),
                0 0 0 19px rgba(82,231,255,0.045),
                0 0 0 58px rgba(82,231,255,0.009),
                0 0 0 59px rgba(82,231,255,0.035);
        }

        .dial-grid-disc-html::after {
            inset: 26%;
            border: 1px dashed rgba(82,231,255,0.12);
        }

        .dial-crosshair-html {
            position: absolute;
            inset: 6%;
            z-index: 1;
            border-radius: 50%;
            pointer-events: none;
        }

        .dial-crosshair-html::before,
        .dial-crosshair-html::after {
            content: "";
            position: absolute;
            left: 50%;
            top: 50%;
            opacity: 0.42;
            background: repeating-linear-gradient(
                90deg,
                rgba(82,231,255,0.16) 0 3px,
                transparent 3px 10px
            );
            transform: translate(-50%, -50%);
        }

        .dial-crosshair-html::before {
            width: 100%;
            height: 1px;
        }

        .dial-crosshair-html::after {
            width: 100%;
            height: 1px;
            transform: translate(-50%, -50%) rotate(90deg);
        }

        .dial-tick-shell-html,
        .dial-rotor-html,
        .dial-annulus-bed-html {
            position: absolute;
            border-radius: 50%;
            pointer-events: none;
        }

        .dial-tick-shell-html {
            inset: 2.4%;
            z-index: 3;
            opacity: 0.70;
            background: repeating-conic-gradient(
                from -0.5deg,
                rgba(91,231,255,0.72) 0deg 0.45deg,
                transparent 0.45deg 3deg
            );
            -webkit-mask: radial-gradient(circle, transparent 0 95.1%, #000 95.3% 97.6%, transparent 97.8%);
            mask: radial-gradient(circle, transparent 0 95.1%, #000 95.3% 97.6%, transparent 97.8%);
            animation: rotate-cw 95s linear infinite;
        }

        .dial-rotor-html {
            z-index: 4;
            background: conic-gradient(
                from 6deg,
                transparent 0 8deg,
                rgba(82,231,255,0.90) 8deg 39deg,
                transparent 39deg 119deg,
                rgba(88,201,255,0.72) 119deg 157deg,
                transparent 157deg 238deg,
                rgba(184,140,255,0.72) 238deg 268deg,
                transparent 268deg 360deg
            );
            -webkit-mask: radial-gradient(circle, transparent 0 96.1%, #000 96.3% 98.4%, transparent 98.6%);
            mask: radial-gradient(circle, transparent 0 96.1%, #000 96.3% 98.4%, transparent 98.6%);
        }

        .dial-rotor-html.rotor-outer {
            inset: 0.8%;
            animation: rotate-cw 42s linear infinite;
        }

        .dial-rotor-html.rotor-inner {
            inset: 8.7%;
            opacity: 0.48;
            animation: rotate-ccw 31s linear infinite;
        }

        .dial-annulus-bed-html {
            inset: 7.2%;
            z-index: 5;
            background:
                repeating-conic-gradient(
                    from -1deg,
                    rgba(88,219,248,0.055) 0deg 1deg,
                    transparent 1deg 6deg
                ),
                conic-gradient(
                    from -30deg,
                    rgba(4,43,58,0.96),
                    rgba(6,63,82,0.76) 33.1%,
                    rgba(4,38,58,0.94) 33.4%,
                    rgba(18,48,76,0.86) 66.3%,
                    rgba(5,37,54,0.94) 66.6%,
                    rgba(7,60,75,0.88)
                );
            -webkit-mask: radial-gradient(circle, transparent 0 57.7%, #000 58.1% 98.2%, transparent 98.6%);
            mask: radial-gradient(circle, transparent 0 57.7%, #000 58.1% 98.2%, transparent 98.6%);
            box-shadow: 0 0 34px rgba(31,189,229,0.05);
        }

        .css-sector {
            position: absolute;
            inset: 7.2%;
            z-index: 8;
            border-radius: 50%;
            outline: none;
            opacity: 0.92;
            background:
                repeating-radial-gradient(
                    circle,
                    transparent 0 16px,
                    rgba(113,225,248,0.065) 17px,
                    transparent 18px 27px
                ),
                linear-gradient(145deg, rgba(14,126,157,0.94), rgba(4,30,44,0.98));
            -webkit-mask: radial-gradient(circle, transparent 0 57.7%, #000 58.1% 98.2%, transparent 98.6%);
            mask: radial-gradient(circle, transparent 0 57.7%, #000 58.1% 98.2%, transparent 98.6%);
            transform-origin: center;
            transition:
                transform 220ms cubic-bezier(.2,.8,.2,1),
                opacity 190ms ease,
                filter 190ms ease;
        }

        .dial-hit-copy {
            position: absolute;
            width: 1px;
            height: 1px;
            overflow: hidden;
            clip: rect(0 0 0 0);
            clip-path: inset(50%);
            white-space: nowrap;
        }

        .css-sector::before {
            content: "";
            position: absolute;
            inset: 0;
            border-radius: 50%;
            opacity: 0.54;
            background: repeating-conic-gradient(
                from -1deg,
                rgba(140,239,255,0.30) 0deg 0.35deg,
                transparent 0.35deg 4.5deg
            );
            -webkit-mask: radial-gradient(circle, transparent 0 90.5%, #000 90.8% 93%, transparent 93.3%);
            mask: radial-gradient(circle, transparent 0 90.5%, #000 90.8% 93%, transparent 93.3%);
        }

        .css-sector::after {
            content: "";
            position: absolute;
            inset: 2.2%;
            border: 1px solid rgba(160,242,255,0.32);
            border-radius: 50%;
            box-shadow: inset 0 0 30px rgba(74,220,255,0.08);
        }

        .css-sector-brief {
            clip-path: polygon(
                50% 50%,
                7.6% 23.5%,
                14.6% 14.6%,
                25% 6.7%,
                37.1% 1.7%,
                50% 0,
                62.9% 1.7%,
                75% 6.7%,
                85.4% 14.6%,
                92.4% 23.5%
            );
            background:
                repeating-radial-gradient(circle, transparent 0 16px, rgba(82,231,255,0.085) 17px, transparent 18px 27px),
                linear-gradient(180deg, rgba(7,137,169,0.98), rgba(3,42,55,0.98));
        }

        .css-sector-horizon {
            clip-path: polygon(
                50% 50%,
                48.3% 100%,
                37.1% 98.3%,
                25% 93.3%,
                14.6% 85.4%,
                6.7% 75%,
                1.7% 62.9%,
                0 50%,
                1.7% 37.1%,
                5.9% 26.5%
            );
            background:
                repeating-radial-gradient(circle, transparent 0 16px, rgba(184,140,255,0.10) 17px, transparent 18px 27px),
                linear-gradient(135deg, rgba(53,31,92,0.98), rgba(20,54,88,0.96));
        }

        .css-sector-scenario {
            clip-path: polygon(
                50% 50%,
                94.1% 26.5%,
                98.3% 37.1%,
                100% 50%,
                98.3% 62.9%,
                93.3% 75%,
                85.4% 85.4%,
                75% 93.3%,
                62.9% 98.3%,
                51.7% 100%
            );
            background:
                repeating-radial-gradient(circle, transparent 0 16px, rgba(255,203,102,0.10) 17px, transparent 18px 27px),
                linear-gradient(225deg, rgba(115,67,20,0.98), rgba(52,43,34,0.96));
        }

        .css-sector:hover,
        .css-sector:focus-visible {
            z-index: 13;
            opacity: 1 !important;
            transform: scale(1.048);
            filter:
                brightness(1.23)
                saturate(1.22)
                drop-shadow(0 0 10px rgba(87,225,255,0.58));
        }

        .css-sector:focus-visible {
            box-shadow: 0 0 0 2px #d8fbff;
        }

        .css-sector.is-active {
            z-index: 14;
            opacity: 1;
            transform: scale(1.074);
            filter:
                brightness(1.24)
                saturate(1.28)
                drop-shadow(0 0 13px rgba(87,225,255,0.72));
        }

        .css-sector.is-active::after {
            border-color: rgba(224,252,255,0.82);
            border-width: 2px;
            box-shadow:
                inset 0 0 38px rgba(74,220,255,0.16),
                0 0 16px rgba(74,220,255,0.20);
        }

        .sector-label-html {
            position: absolute;
            z-index: 16;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            gap: 0.16rem;
            pointer-events: none;
            color: #dffbff;
            font-family: "Cascadia Mono", Consolas, monospace;
            text-align: center;
            text-transform: uppercase;
            transition:
                transform 220ms cubic-bezier(.2,.8,.2,1),
                opacity 190ms ease,
                filter 190ms ease;
        }

        .sector-label-brief {
            top: 13.5%;
            left: 31%;
            width: 38%;
        }

        .sector-label-horizon {
            top: 64%;
            left: 4%;
            width: 34%;
        }

        .sector-label-scenario {
            top: 64%;
            right: 4%;
            width: 34%;
        }

        .sector-code-html {
            color: #63a7b7;
            font-size: clamp(0.36rem, 0.62vw, 0.50rem);
            font-weight: 750;
            letter-spacing: 0.16em;
        }

        .sector-title-html {
            color: #e8fdff;
            font-size: clamp(0.57rem, 1vw, 0.84rem);
            font-weight: 760;
            letter-spacing: 0.08em;
            line-height: 1.08;
            text-shadow: 0 0 10px rgba(99,225,255,0.34);
        }

        .sector-metric-html {
            color: #68e7ff;
            font-size: clamp(0.42rem, 0.77vw, 0.63rem);
            font-weight: 750;
            letter-spacing: 0.055em;
        }

        .sector-label-brief .sector-metric-html { color:#63EBFF; }
        .sector-label-horizon .sector-metric-html { color:#C8AAFF; }
        .sector-label-scenario .sector-metric-html { color:#FFD37C; }

        .sector-sub-html {
            color: #477887;
            font-size: clamp(0.30rem, 0.52vw, 0.43rem);
            font-weight: 650;
            letter-spacing: 0.10em;
            line-height: 1.25;
        }

        .sector-label-html.is-active {
            opacity: 1;
            filter: brightness(1.30) drop-shadow(0 0 7px rgba(82,231,255,0.56));
        }

        .sector-label-brief.is-active {
            transform: translateY(-7px) scale(1.05);
        }

        .sector-label-horizon.is-active {
            transform: translate(-7px, 5px) scale(1.05);
        }

        .sector-label-scenario.is-active {
            transform: translate(7px, 5px) scale(1.05);
        }

        .css-sector-brief:hover ~ .sector-label-brief,
        .css-sector-brief:focus-visible ~ .sector-label-brief {
            opacity: 1 !important;
            transform: translateY(-6px) scale(1.045);
            filter: brightness(1.25) drop-shadow(0 0 7px rgba(82,231,255,0.52));
        }

        .css-sector-horizon:hover ~ .sector-label-horizon,
        .css-sector-horizon:focus-visible ~ .sector-label-horizon {
            opacity: 1 !important;
            transform: translate(-6px, 5px) scale(1.045);
            filter: brightness(1.25) drop-shadow(0 0 7px rgba(82,231,255,0.52));
        }

        .css-sector-scenario:hover ~ .sector-label-scenario,
        .css-sector-scenario:focus-visible ~ .sector-label-scenario {
            opacity: 1 !important;
            transform: translate(6px, 5px) scale(1.045);
            filter: brightness(1.25) drop-shadow(0 0 7px rgba(82,231,255,0.52));
        }

        .dial-spoke-html,
        .dial-vector-line-html {
            position: absolute;
            left: 50%;
            top: 50%;
            z-index: 17;
            height: 1px;
            transform-origin: 0 50%;
            pointer-events: none;
        }

        .dial-spoke-html {
            width: 42.5%;
            opacity: 0.74;
            background: linear-gradient(90deg, transparent 0 38%, rgba(121,231,249,0.64) 52%, rgba(74,183,216,0.16));
            box-shadow: 0 0 5px rgba(82,231,255,0.17);
        }

        .dial-spoke-html::after {
            content: "";
            position: absolute;
            right: -2px;
            top: -2px;
            width: 5px;
            height: 5px;
            border: 1px solid rgba(123,234,251,0.66);
            border-radius: 50%;
            background: #0a2d3b;
            box-shadow: 0 0 8px rgba(82,231,255,0.55);
        }

        .dial-spoke-a { transform: rotate(-30deg); }
        .dial-spoke-b { transform: rotate(90deg); }
        .dial-spoke-c { transform: rotate(210deg); }

        .dial-vector-line-html {
            z-index: 15;
            width: 35%;
            opacity: 0.40;
            background: repeating-linear-gradient(
                90deg,
                rgba(95,220,246,0.65) 0 8px,
                transparent 8px 14px
            );
        }

        .dial-vector-a { transform: rotate(-90deg); }
        .dial-vector-b { transform: rotate(30deg); }
        .dial-vector-c { transform: rotate(150deg); }

        .css-core {
            position: absolute;
            left: 50%;
            top: 50%;
            z-index: 22;
            display: grid;
            width: 34%;
            aspect-ratio: 1;
            place-items: center;
            overflow: hidden;
            color: #eaffff !important;
            border: 1px solid rgba(115,231,249,0.66);
            border-radius: 50%;
            outline: none;
            background:
                radial-gradient(circle at 50% 45%, rgba(32,126,154,0.40), transparent 30%),
                radial-gradient(circle, #0b3c50 0, #062636 46%, #020f18 75%);
            box-shadow:
                inset 0 0 34px rgba(68,224,255,0.16),
                0 0 0 8px rgba(5,31,43,0.82),
                0 0 0 9px rgba(82,231,255,0.28),
                0 0 32px rgba(82,231,255,0.16);
            text-decoration: none !important;
            transform: translate(-50%, -50%);
            transition:
                transform 220ms cubic-bezier(.2,.8,.2,1),
                opacity 190ms ease,
                filter 190ms ease,
                border-color 190ms ease;
        }

        .css-core::before {
            content: "";
            position: absolute;
            inset: 5%;
            border: 1px dashed rgba(115,231,249,0.40);
            border-radius: 50%;
            animation: rotate-cw 24s linear infinite;
        }

        .css-core::after {
            content: "";
            position: absolute;
            inset: 14%;
            border: 2px solid transparent;
            border-top-color: rgba(162,243,255,0.92);
            border-right-color: rgba(108,208,255,0.36);
            border-radius: 50%;
            box-shadow: inset 0 0 18px rgba(82,231,255,0.07);
            animation: rotate-ccw 12s linear infinite;
        }

        .core-orbit-html,
        .core-reactor-html,
        .core-scan-html {
            position: absolute;
            border-radius: 50%;
            pointer-events: none;
        }

        .core-orbit-html {
            inset: 23%;
            opacity: 0.88;
            background: repeating-conic-gradient(
                from 0deg,
                #71eaff 0deg 5deg,
                transparent 5deg 17deg
            );
            -webkit-mask: radial-gradient(circle, transparent 0 78%, #000 80% 97%, transparent 99%);
            mask: radial-gradient(circle, transparent 0 78%, #000 80% 97%, transparent 99%);
            animation: rotate-cw 9s linear infinite;
        }

        .core-reactor-html {
            inset: 33%;
            border: 1px solid rgba(121,236,255,0.65);
            background:
                conic-gradient(from 45deg, rgba(82,231,255,0.85), transparent 14%, rgba(175,137,255,0.78) 26%, transparent 42%, rgba(82,231,255,0.85) 56%, transparent 72%, rgba(109,255,210,0.72) 87%, transparent),
                #062331;
            clip-path: polygon(50% 0, 88% 18%, 100% 50%, 82% 88%, 50% 100%, 12% 82%, 0 50%, 18% 12%);
            box-shadow: 0 0 16px rgba(82,231,255,0.42);
            animation: rotate-ccw 8s linear infinite;
        }

        .core-scan-html {
            left: 20%;
            right: 20%;
            top: 50%;
            height: 1px;
            border-radius: 0;
            background: linear-gradient(90deg, transparent, rgba(130,242,255,0.82), transparent);
            box-shadow: 0 0 8px rgba(82,231,255,0.62);
            animation: core-scan 3.8s ease-in-out infinite;
        }

        .core-copy-html {
            position: relative;
            z-index: 6;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 0.18rem;
            padding: 0 0.7rem;
            color: #eaffff;
            font-family: "Cascadia Mono", Consolas, monospace;
            text-align: center;
            text-transform: uppercase;
        }

        .core-code-html {
            color: #5d96a5;
            font-size: clamp(0.32rem, 0.56vw, 0.45rem);
            font-weight: 750;
            letter-spacing: 0.16em;
        }

        .core-main-html {
            color: #f0feff;
            font-size: clamp(0.62rem, 1.12vw, 0.94rem);
            font-weight: 780;
            letter-spacing: 0.08em;
            line-height: 1.02;
            text-shadow: 0 0 11px rgba(93,230,255,0.62);
        }

        .core-online-html {
            display: inline-flex;
            align-items: center;
            gap: 0.34rem;
            color: #52f1b2;
            font-size: clamp(0.32rem, 0.56vw, 0.45rem);
            font-weight: 750;
            letter-spacing: 0.14em;
        }

        .core-online-html::before {
            content: "";
            width: 5px;
            height: 5px;
            border-radius: 50%;
            background: #52f1b2;
            box-shadow: 0 0 7px #52f1b2;
            animation: bar-pulse 2s ease-in-out infinite;
        }

        .core-hint-html {
            color: #426f7d;
            font-size: clamp(0.26rem, 0.45vw, 0.37rem);
            font-weight: 650;
            letter-spacing: 0.08em;
        }

        .css-core:hover,
        .css-core:focus-visible {
            opacity: 1 !important;
            border-color: #e0fbff;
            transform: translate(-50%, -50%) scale(1.06);
            filter: brightness(1.22) drop-shadow(0 0 13px rgba(82,231,255,0.68));
        }

        .css-core:focus-visible {
            box-shadow:
                0 0 0 2px #e0fbff,
                0 0 32px rgba(82,231,255,0.34);
        }

        .css-core.is-active {
            opacity: 1;
            border-color: #ffffff;
            transform: translate(-50%, -50%) scale(1.085);
            filter:
                brightness(1.24)
                saturate(1.22)
                drop-shadow(0 0 15px rgba(112,229,255,0.75));
        }

        .dial-cardinal-html {
            position: absolute;
            z-index: 18;
            color: #69b7c7;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: clamp(0.32rem, 0.53vw, 0.44rem);
            font-weight: 750;
            letter-spacing: 0.08em;
            pointer-events: none;
            text-transform: uppercase;
        }

        .dial-cardinal-n { top: 0.6%; left: 50%; transform: translateX(-50%); }
        .dial-cardinal-e { right: 0.2%; top: 50%; transform: translateY(-50%); }
        .dial-cardinal-s { bottom: 0.6%; left: 50%; transform: translateX(-50%); }
        .dial-cardinal-w { left: 0.2%; top: 50%; transform: translateY(-50%); }

        .integrated-system.has-selection .css-sector:not(.is-active),
        .integrated-system.has-selection .css-core:not(.is-active) {
            opacity: 0.22;
            filter: saturate(0.42) brightness(0.62);
        }

        .integrated-system.has-selection .sector-label-html:not(.is-active) {
            opacity: 0.26;
            filter: saturate(0.48) brightness(0.66);
        }

        .integrated-system.has-selection .css-sector:not(.is-active):hover,
        .integrated-system.has-selection .css-sector:not(.is-active):focus-visible,
        .integrated-system.has-selection .css-core:not(.is-active):hover,
        .integrated-system.has-selection .css-core:not(.is-active):focus-visible {
            opacity: 0.90;
        }

        @keyframes core-scan {
            0%, 100% { transform: translateY(-11px); opacity: 0.22; }
            50% { transform: translateY(11px); opacity: 0.92; }
        }

        .telemetry-console {
            position: relative;
            z-index: 4;
            min-width: 0;
            padding: 0.95rem 0.9rem;
            background: linear-gradient(145deg, rgba(5,32,45,0.92), rgba(2,16,25,0.88));
            border: 1px solid rgba(82,231,255,0.20);
            box-shadow: inset 0 0 25px rgba(82,231,255,0.035);
        }

        .telemetry-console.console-left {
            clip-path: polygon(0 0, 86% 0, 100% 13%, 100% 87%, 86% 100%, 0 100%);
        }

        .telemetry-console.console-right {
            clip-path: polygon(14% 0, 100% 0, 100% 100%, 14% 100%, 0 87%, 0 13%);
        }

        .telemetry-console::after {
            content: "";
            position: absolute;
            top: 50%;
            width: 44px;
            height: 1px;
            background: linear-gradient(90deg, rgba(82,231,255,0.60), transparent);
            box-shadow: 0 0 7px rgba(82,231,255,0.30);
        }

        .console-left::after { left: 100%; }
        .console-right::after {
            right: 100%;
            transform: rotate(180deg);
        }

        .console-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.5rem;
            margin-bottom: 0.8rem;
            padding-bottom: 0.55rem;
            color: #72dced;
            border-bottom: 1px solid rgba(82,231,255,0.14);
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.57rem;
            font-weight: 750;
            letter-spacing: 0.12em;
            text-transform: uppercase;
        }

        .console-head span:last-child {
            color: #376675;
            font-size: 0.48rem;
        }

        .console-row {
            display: grid;
            grid-template-columns: 1fr auto;
            align-items: center;
            gap: 0.65rem;
            min-width: 0;
            padding: 0.43rem 0;
            border-bottom: 1px solid rgba(82,231,255,0.07);
        }

        .console-row:last-of-type {
            border-bottom: 0;
        }

        .console-label {
            overflow: hidden;
            color: #4d7887;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.52rem;
            letter-spacing: 0.07em;
            text-overflow: ellipsis;
            text-transform: uppercase;
            white-space: nowrap;
        }

        .console-value {
            color: #c9f3f8;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.61rem;
            font-weight: 700;
            text-align: right;
            white-space: nowrap;
        }

        .console-value.signal-alert { color: var(--red); }
        .console-value.signal-watch { color: var(--amber); }
        .console-value.signal-track { color: var(--green); }

        .console-bars {
            display: flex;
            align-items: flex-end;
            gap: 3px;
            height: 28px;
            margin-top: 0.8rem;
            padding-top: 0.45rem;
            border-top: 1px solid rgba(82,231,255,0.09);
        }

        .console-bars span {
            flex: 1;
            min-width: 2px;
            background: linear-gradient(180deg, #65e9ff, rgba(25,104,130,0.24));
            box-shadow: 0 0 5px rgba(82,231,255,0.17);
            animation: bar-pulse 3.4s ease-in-out infinite;
        }

        .console-bars span:nth-child(2n) { animation-delay: -0.7s; }
        .console-bars span:nth-child(3n) { animation-delay: -1.4s; }

        .console-caption {
            margin-top: 0.55rem;
            color: #345e6c;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.45rem;
            letter-spacing: 0.08em;
            line-height: 1.45;
            text-transform: uppercase;
        }

        .system-bottom-rail {
            position: relative;
            z-index: 4;
            display: grid;
            grid-template-columns: 1fr auto 1fr;
            align-items: center;
            gap: 0.8rem;
            margin-top: -0.25rem;
            padding: 0.72rem 0.2rem 0.1rem;
            color: #3e6978;
            border-top: 1px solid rgba(82,231,255,0.11);
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.51rem;
            letter-spacing: 0.09em;
            text-transform: uppercase;
        }

        .system-bottom-rail > span:last-child {
            text-align: right;
        }

        .system-reset {
            display: inline-flex;
            align-items: center;
            gap: 0.45rem;
            padding: 0.34rem 0.7rem;
            color: #78dcec !important;
            background: rgba(82,231,255,0.04);
            border: 1px solid rgba(82,231,255,0.22);
            text-decoration: none !important;
            transition: border-color 160ms ease, box-shadow 160ms ease, color 160ms ease;
        }

        .system-reset:hover {
            color: #ffffff !important;
            border-color: rgba(82,231,255,0.72);
            box-shadow: 0 0 16px rgba(82,231,255,0.12);
        }

        .system-reset.is-home {
            color: #416b79 !important;
            border-color: rgba(82,231,255,0.09);
            pointer-events: none;
        }

        .system-overview-note,
        .active-module-banner {
            position: relative;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            margin: 0.15rem 0 1.15rem;
            padding: 0.72rem 0.95rem;
            background: linear-gradient(90deg, rgba(82,231,255,0.065), rgba(82,231,255,0.01));
            border-left: 2px solid var(--cyan);
            border-top: 1px solid rgba(82,231,255,0.11);
            border-bottom: 1px solid rgba(82,231,255,0.07);
        }

        .overview-title,
        .active-module-name {
            color: #dffaff;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.67rem;
            font-weight: 750;
            letter-spacing: 0.09em;
            text-transform: uppercase;
        }

        .overview-copy,
        .active-module-state {
            color: #527d8c;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.55rem;
            letter-spacing: 0.07em;
            text-align: right;
            text-transform: uppercase;
        }

        @keyframes system-scan {
            from { transform: translateX(0); }
            to { transform: translateX(560%); }
        }

        @keyframes bar-pulse {
            0%, 100% { opacity: 0.45; filter: brightness(0.75); }
            50% { opacity: 1; filter: brightness(1.25); }
        }

        @media (max-width: 1120px) {
            .system-grid {
                grid-template-columns: minmax(140px, 0.46fr) minmax(500px, 1.7fr) minmax(140px, 0.46fr);
            }

            .console-row {
                grid-template-columns: 1fr;
                gap: 0.16rem;
            }

            .console-value {
                text-align: left;
            }
        }

        @media (max-width: 860px) {
            .integrated-system {
                padding-left: 0.7rem;
                padding-right: 0.7rem;
            }

            .system-grid {
                grid-template-columns: 1fr;
                min-height: 0;
            }

            .dial-viewport {
                grid-row: 1;
            }

            .telemetry-console {
                display: none;
            }

            .command-dial-html {
                width: min(100%, 660px);
            }

            .system-bottom-rail {
                grid-template-columns: 1fr auto;
            }

            .system-bottom-rail > span:last-child {
                display: none;
            }

            .system-overview-note,
            .active-module-banner {
                align-items: flex-start;
                flex-direction: column;
                gap: 0.3rem;
            }

            .overview-copy,
            .active-module-state {
                text-align: left;
            }
        }

        @media (max-width: 560px) {
            .sector-sub-html,
            .core-hint-html,
            .dial-cardinal-html {
                display: none;
            }

            .sector-label-horizon {
                left: 2%;
                width: 37%;
            }

            .sector-label-scenario {
                right: 2%;
                width: 37%;
            }
        }

        /* -------------------------------------------------
           STREAMLIT CONTROLS
           ------------------------------------------------- */

        [data-testid="stForm"] {
            padding: 1.2rem 1.25rem 1.3rem;
            background: linear-gradient(145deg, rgba(7, 29, 42, 0.85), rgba(3, 16, 25, 0.82));
            border: 1px solid rgba(82, 231, 255, 0.16);
            border-radius: 0;
            clip-path: polygon(0 0, calc(100% - 16px) 0, 100% 16px, 100% 100%, 0 100%);
        }

        .stSlider [data-baseweb="slider"] > div > div {
            background: rgba(82, 231, 255, 0.18);
        }

        .stSlider [role="slider"] {
            background: var(--cyan) !important;
            border-color: #d9fbff !important;
            box-shadow: 0 0 0 4px rgba(82,231,255,0.10), 0 0 16px rgba(82,231,255,0.75) !important;
        }

        .stSlider label, .stTextInput label {
            color: #a5c9d4 !important;
            font-family: "Cascadia Mono", Consolas, monospace !important;
            font-size: 0.69rem !important;
            letter-spacing: 0.045em;
            text-transform: uppercase;
        }

        div.stButton > button,
        div[data-testid="stFormSubmitButton"] > button {
            min-height: 2.65rem;
            color: var(--cyan-soft);
            background: linear-gradient(120deg, rgba(13, 65, 84, 0.92), rgba(5, 34, 49, 0.94));
            border: 1px solid rgba(82, 231, 255, 0.42);
            border-radius: 0;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.68rem;
            font-weight: 750;
            letter-spacing: 0.055em;
            text-transform: uppercase;
            clip-path: polygon(8px 0, 100% 0, 100% calc(100% - 8px), calc(100% - 8px) 100%, 0 100%, 0 8px);
            box-shadow: inset 0 0 15px rgba(82,231,255,0.035);
            transition: all 160ms ease;
        }

        div.stButton > button:hover,
        div[data-testid="stFormSubmitButton"] > button:hover {
            color: #ffffff;
            border-color: var(--cyan);
            background: linear-gradient(120deg, rgba(18, 89, 112, 0.95), rgba(6, 44, 61, 0.96));
            box-shadow: 0 0 22px rgba(82,231,255,0.15), inset 0 0 22px rgba(82,231,255,0.08);
            transform: translateY(-1px);
        }

        div.stButton > button:focus:not(:active),
        div[data-testid="stFormSubmitButton"] > button:focus:not(:active) {
            border-color: var(--cyan);
            box-shadow: 0 0 0 2px rgba(82,231,255,0.15);
        }

        [data-baseweb="input"] {
            background: rgba(3, 15, 24, 0.92) !important;
            border: 1px solid rgba(82,231,255,0.20) !important;
            border-radius: 0 !important;
        }

        [data-baseweb="input"]:focus-within {
            border-color: rgba(82,231,255,0.62) !important;
            box-shadow: 0 0 18px rgba(82,231,255,0.08);
        }

        [data-testid="stExpander"] {
            background: rgba(4, 18, 28, 0.68);
            border: 1px solid rgba(82, 231, 255, 0.13);
            border-radius: 0;
        }

        [data-testid="stExpander"] summary {
            color: #87afbd;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.68rem;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }

        [data-testid="stMetric"] {
            padding: 0.9rem 1rem;
            background: rgba(5, 28, 40, 0.76);
            border: 1px solid rgba(82,231,255,0.15);
        }

        [data-testid="stMetricLabel"] {
            color: #79a1af;
        }

        [data-testid="stMetricValue"] {
            color: #eaffff;
            font-family: "Cascadia Mono", Consolas, monospace;
        }

        [data-testid="stCaptionContainer"] {
            color: #557f8f;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.66rem;
        }

        [data-testid="stChatMessage"] {
            background: linear-gradient(120deg, rgba(6, 28, 41, 0.84), rgba(3, 16, 25, 0.80));
            border: 1px solid rgba(82, 231, 255, 0.13);
            border-radius: 0;
            margin-bottom: 0.65rem;
            clip-path: polygon(0 0, calc(100% - 12px) 0, 100% 12px, 100% 100%, 0 100%);
        }

        [data-testid="stChatMessage"] [data-testid="stChatMessageAvatarUser"] {
            background: rgba(184, 140, 255, 0.16);
            border: 1px solid rgba(184, 140, 255, 0.38);
        }

        [data-testid="stChatMessage"] [data-testid="stChatMessageAvatarAssistant"] {
            background: rgba(82, 231, 255, 0.12);
            border: 1px solid rgba(82, 231, 255, 0.38);
        }

        [data-testid="stVegaLiteChart"] {
            padding: 0.5rem 0.35rem 0.25rem;
            background:
                linear-gradient(180deg, rgba(6, 27, 39, 0.64), rgba(3, 15, 23, 0.42)),
                linear-gradient(rgba(82,231,255,0.025) 1px, transparent 1px),
                linear-gradient(90deg, rgba(82,231,255,0.025) 1px, transparent 1px);
            background-size: auto, 28px 28px, 28px 28px;
            border: 1px solid rgba(82,231,255,0.11);
        }

        .copilot-intro {
            display: grid;
            grid-template-columns: auto 1fr;
            align-items: center;
            gap: 1rem;
        }

        .copilot-glyph {
            width: 54px;
            height: 54px;
            display: grid;
            place-items: center;
            color: var(--cyan);
            border: 1px solid rgba(82,231,255,0.50);
            background: radial-gradient(circle, rgba(82,231,255,0.18), transparent 66%);
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 1rem;
            clip-path: polygon(50% 0, 100% 25%, 100% 75%, 50% 100%, 0 75%, 0 25%);
            box-shadow: 0 0 24px rgba(82,231,255,0.11);
        }

        .copilot-name {
            color: #ecfdff;
            font-size: 0.98rem;
            font-weight: 680;
            margin-bottom: 0.22rem;
        }

        .copilot-copy {
            color: #789fac;
            font-size: 0.82rem;
            line-height: 1.5;
        }

        .copilot-context-strip {
            display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.55rem; margin:.75rem 0 1rem;
        }
        .copilot-context-item {
            padding:.62rem .72rem; background:rgba(82,231,255,.025); border:1px solid rgba(82,231,255,.10);
        }
        .copilot-context-item span {
            display:block; color:#557f8f; font:700 .50rem "Cascadia Mono",Consolas,monospace; letter-spacing:.10em; text-transform:uppercase;
        }
        .copilot-context-item strong {
            display:block; margin-top:.18rem; color:#e7fbff; font-size:.80rem; font-weight:720;
        }
        .copilot-thread-label {
            color:#52e7ff; font:750 .52rem "Cascadia Mono",Consolas,monospace; letter-spacing:.12em; text-transform:uppercase; margin-bottom:.30rem;
        }
        .copilot-answer-label {
            color:#8eeaff; font:750 .50rem "Cascadia Mono",Consolas,monospace; letter-spacing:.12em; text-transform:uppercase; margin-bottom:.38rem;
        }
        .copilot-user-label {
            color:#b99cff; font:750 .50rem "Cascadia Mono",Consolas,monospace; letter-spacing:.12em; text-transform:uppercase; margin-bottom:.38rem;
        }
        .copilot-command-bar {
            display:flex; align-items:center; justify-content:space-between; gap:.8rem; margin:.55rem 0 .75rem;
            color:#567f8e; font:700 .52rem "Cascadia Mono",Consolas,monospace; letter-spacing:.08em; text-transform:uppercase;
        }
        .copilot-module-dock {
            display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.55rem; margin:1rem 0 .55rem;
        }
        .copilot-module-link {
            display:flex; align-items:center; justify-content:center; min-height:42px; padding:.55rem .7rem;
            color:#9ac8d2 !important; background:rgba(82,231,255,.025); border:1px solid rgba(82,231,255,.12);
            text-decoration:none !important; font:750 .55rem "Cascadia Mono",Consolas,monospace; letter-spacing:.08em; text-transform:uppercase;
            transition:all 160ms ease;
        }
        .copilot-module-link:hover {
            color:#ecfdff !important; border-color:rgba(82,231,255,.42); background:rgba(82,231,255,.08); box-shadow:0 0 18px rgba(82,231,255,.08);
        }
        .copilot-evidence-note {
            color:#547987; font:650 .55rem "Cascadia Mono",Consolas,monospace; letter-spacing:.05em; margin-top:.3rem;
        }
        [data-testid="stChatMessage"] {
            padding:1rem 1.05rem;
        }
        [data-testid="stChatMessage"] p,
        [data-testid="stChatMessage"] li {
            color:#b9ced5; line-height:1.55;
        }
        [data-testid="stChatMessage"] strong { color:#effdff; }
        [data-testid="stChatMessageAvatarUser"],
        [data-testid="stChatMessageAvatarAssistant"] {
            border-radius:0 !important;
            box-shadow:none !important;
        }

        .system-footer {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            margin-top: 2.2rem;
            padding-top: 0.85rem;
            color: #496f7d;
            border-top: 1px solid rgba(82,231,255,0.10);
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.57rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        code, pre {
            font-family: "Cascadia Mono", "SFMono-Regular", Consolas, monospace !important;
        }

        ::-webkit-scrollbar { width: 9px; height: 9px; }
        ::-webkit-scrollbar-track { background: #02080d; }
        ::-webkit-scrollbar-thumb { background: #124355; border: 2px solid #02080d; }
        ::-webkit-scrollbar-thumb:hover { background: #1b6077; }

        @keyframes scan-horizontal {
            from { transform: translateX(0); }
            to { transform: translateX(360%); }
        }

        @keyframes pulse-dot {
            0%, 100% { opacity: 0.65; transform: scale(0.88); }
            50% { opacity: 1; transform: scale(1.08); }
        }

        @keyframes rotate-cw { to { transform: rotate(360deg); } }
        @keyframes rotate-ccw { to { transform: rotate(-360deg); } }

        @keyframes orb-breathe {
            0%, 100% { filter: brightness(0.92); transform: scale(0.98); }
            50% { filter: brightness(1.13); transform: scale(1.015); }
        }

        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after {
                animation-duration: 0.01ms !important;
                animation-iteration-count: 1 !important;
                transition-duration: 0.01ms !important;
            }
        }

        @media (max-width: 900px) {
            .hud-hero {
                grid-template-columns: 1fr;
                padding: 1.55rem;
            }

            .hero-core {
                min-height: 160px;
            }

            .arc-orb {
                width: 142px;
                height: 142px;
            }

            .scenario-summary {
                grid-template-columns: 1fr;
            }

            .diagnostic-grid {
                grid-template-columns: 1fr 1fr;
            }

            .sync-copy {
                display: none;
            }
        }

    </style>
    """
)



# ============================================================
# PHASE 1 — CERTIFIED COCKPIT EXTENSIONS
# ============================================================

render_html(
    """
    <style>
        .kpi-neutral {
            display: flex;
            align-items: center;
            gap: 0.45rem;
            margin-top: 0.78rem;
            color: var(--cyan-soft);
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.015em;
        }

        .kpi-card:has(.kpi-neutral)::before {
            background: linear-gradient(90deg, var(--cyan), transparent);
            box-shadow: 0 0 12px rgba(82,231,255,0.55);
        }

        .brief-grid-label {
            margin: 0.85rem 0 0.45rem;
            color: #608997;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.58rem;
            font-weight: 750;
            letter-spacing: 0.13em;
            text-transform: uppercase;
        }

        .alert-neutral {
            border-left-color: var(--cyan);
            color: var(--cyan);
        }

        .intel-card {
            position: relative;
            padding: 0.95rem 1rem;
            margin-bottom: 0.68rem;
            background: linear-gradient(100deg, rgba(8,31,44,0.92), rgba(4,17,27,0.78));
            border: 1px solid rgba(120,204,223,0.13);
            border-left: 2px solid rgba(82,231,255,0.52);
            clip-path: polygon(0 0, calc(100% - 12px) 0, 100% 12px, 100% 100%, 0 100%);
        }

        .intel-meta {
            color: #5f8d9d;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.57rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        .intel-headline {
            margin-top: 0.35rem;
            color: #e4f8fb;
            font-size: 0.84rem;
            font-weight: 650;
            line-height: 1.42;
        }

        .intel-detail {
            margin-top: 0.35rem;
            color: #7fa6b5;
            font-size: 0.76rem;
            line-height: 1.42;
        }

        .intel-link {
            display: inline-block;
            margin-top: 0.45rem;
            color: var(--cyan) !important;
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.62rem;
            font-weight: 700;
            text-decoration: none !important;
        }

        .intel-link:hover {
            color: #dffcff !important;
            text-shadow: 0 0 10px rgba(82,231,255,0.55);
        }

        .certified-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.25rem 0.5rem;
            color: #8eeaff;
            border: 1px solid rgba(82,231,255,0.22);
            background: rgba(82,231,255,0.04);
            font-family: "Cascadia Mono", Consolas, monospace;
            font-size: 0.56rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
    </style>
    """
)


# ============================================================
# PHASE 2 — RADIAL SUPPORT PANELS + INTELLIGENCE DOCK
# ============================================================

render_html(
    """
    <style>
        .feed-strip {
            display:flex;
            flex-wrap:wrap;
            gap:0.42rem;
            margin:-0.1rem 0 1rem 0;
        }

        .feed-chip {
            display:inline-flex;
            align-items:center;
            gap:0.38rem;
            padding:0.28rem 0.52rem;
            color:#86C8D6;
            background:rgba(82,231,255,0.035);
            border:1px solid rgba(82,231,255,0.13);
            font-family:"Cascadia Mono",Consolas,monospace;
            font-size:0.55rem;
            font-weight:700;
            letter-spacing:0.08em;
            text-transform:uppercase;
        }

        .feed-chip::before {
            content:"";
            width:5px;
            height:5px;
            border-radius:50%;
            background:var(--green);
            box-shadow:0 0 8px rgba(66,245,167,0.8);
        }

        /* The core dial stays visually pure. Secondary intelligence sits
           outside the circle and is accessed through the dock below. */
        .system-grid {
            grid-template-columns:minmax(260px,0.72fr) minmax(560px,1.55fr) minmax(270px,0.76fr) !important;
            gap:0.85rem !important;
            min-height:660px;
        }

        .decision-panel,
        .focus-panel {
            position:relative;
            z-index:5;
            min-width:0;
            overflow:hidden;
            color:#BFDCE4;
            background:
                linear-gradient(145deg,rgba(4,25,37,0.94),rgba(2,15,24,0.92)),
                radial-gradient(circle at 100% 0%,rgba(82,231,255,0.08),transparent 48%);
            border:1px solid rgba(82,231,255,0.22);
            box-shadow:inset 0 0 36px rgba(82,231,255,0.025),0 18px 50px rgba(0,0,0,0.18);
        }

        .decision-panel {
            padding:1.02rem 1rem 0.82rem;
            clip-path:polygon(0 0,calc(100% - 16px) 0,100% 16px,100% 100%,0 100%);
        }

        .focus-panel {
            padding:1.05rem 1.05rem 1rem;
            clip-path:polygon(12px 0,100% 0,100% calc(100% - 14px),calc(100% - 14px) 100%,0 100%,0 12px);
        }

        .side-panel-head {
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:0.6rem;
            padding-bottom:0.72rem;
            border-bottom:1px solid rgba(82,231,255,0.14);
        }

        .side-panel-title {
            color:#E8FBFF;
            font-family:"Cascadia Mono",Consolas,monospace;
            font-size:0.72rem;
            font-weight:780;
            letter-spacing:0.12em;
            text-transform:uppercase;
        }

        .side-live {
            display:inline-flex;
            align-items:center;
            gap:0.35rem;
            color:#65E7B5;
            font-family:"Cascadia Mono",Consolas,monospace;
            font-size:0.50rem;
            font-weight:760;
            letter-spacing:0.12em;
            text-transform:uppercase;
        }

        .side-live::after {
            content:"";
            width:6px;
            height:6px;
            border-radius:50%;
            background:var(--green);
            box-shadow:0 0 10px rgba(66,245,167,0.85);
        }

        .decision-list {
            display:grid;
            gap:0;
        }

        .decision-item {
            display:grid;
            grid-template-columns:44px minmax(0,1fr) 18px;
            align-items:center;
            gap:0.72rem;
            min-height:92px;
            padding:0.78rem 0.05rem;
            border-bottom:1px solid rgba(82,231,255,0.10);
            color:inherit !important;
            text-decoration:none !important;
            transition:background 160ms ease,transform 160ms ease;
        }

        .decision-item:last-child { border-bottom:0; }

        .decision-item:hover {
            transform:translateX(3px);
            background:linear-gradient(90deg,rgba(82,231,255,0.055),transparent);
        }

        .decision-icon {
            width:38px;
            height:38px;
            display:grid;
            place-items:center;
            border-radius:50%;
            border:1px solid rgba(82,231,255,0.42);
            color:#7FEAFF;
            font-family:"Cascadia Mono",Consolas,monospace;
            font-size:0.9rem;
            box-shadow:inset 0 0 18px rgba(82,231,255,0.05),0 0 16px rgba(82,231,255,0.05);
        }

        .decision-icon.is-green {
            color:#55F1B0;
            border-color:rgba(66,245,167,0.55);
            box-shadow:inset 0 0 18px rgba(66,245,167,0.05),0 0 16px rgba(66,245,167,0.07);
        }

        .decision-icon.is-violet {
            color:#C5A7FF;
            border-color:rgba(184,140,255,0.55);
        }

        .decision-copy { min-width:0; }

        .decision-title {
            color:#E5F8FB;
            font-size:0.80rem;
            font-weight:720;
            line-height:1.25;
        }

        .decision-primary {
            margin-top:0.25rem;
            color:#7CCBDA;
            font-family:"Cascadia Mono",Consolas,monospace;
            font-size:0.60rem;
            font-weight:700;
            line-height:1.4;
        }

        .decision-secondary {
            margin-top:0.16rem;
            color:#577F8E;
            font-size:0.64rem;
            line-height:1.38;
        }

        .decision-arrow {
            color:#50CDE5;
            font-size:1.0rem;
            opacity:0.78;
        }

        .focus-head {
            display:grid;
            grid-template-columns:44px minmax(0,1fr) 20px;
            align-items:center;
            gap:0.72rem;
            padding-bottom:0.8rem;
            border-bottom:1px solid rgba(82,231,255,0.14);
        }

        .focus-glyph {
            width:40px;
            height:40px;
            display:grid;
            place-items:center;
            color:#79E9FF;
            border:1px solid rgba(82,231,255,0.42);
            font-family:"Cascadia Mono",Consolas,monospace;
            font-size:0.95rem;
            clip-path:polygon(50% 0,100% 25%,100% 75%,50% 100%,0 75%,0 25%);
            background:rgba(82,231,255,0.04);
        }

        .focus-title {
            color:#EAFBFF;
            font-size:1rem;
            font-weight:760;
            letter-spacing:0.02em;
        }

        .focus-subtitle {
            margin-top:0.18rem;
            color:#5F91A1;
            font-family:"Cascadia Mono",Consolas,monospace;
            font-size:0.48rem;
            font-weight:700;
            letter-spacing:0.09em;
            text-transform:uppercase;
        }

        .focus-open {
            color:#6BE4F7 !important;
            text-decoration:none !important;
            font-size:1rem;
        }

        .focus-metric-grid {
            display:grid;
            grid-template-columns:1fr 1fr;
            gap:0.55rem;
            margin-top:0.78rem;
        }

        .focus-metric {
            min-width:0;
            padding:0.62rem 0.65rem;
            background:rgba(82,231,255,0.025);
            border:1px solid rgba(82,231,255,0.09);
        }

        .focus-metric-label {
            color:#4E7E8E;
            font-family:"Cascadia Mono",Consolas,monospace;
            font-size:0.46rem;
            font-weight:720;
            letter-spacing:0.09em;
            text-transform:uppercase;
        }

        .focus-metric-value {
            margin-top:0.25rem;
            color:#EAFBFF;
            font-family:"Cascadia Mono",Consolas,monospace;
            font-size:0.86rem;
            font-weight:720;
        }

        .focus-metric-sub {
            margin-top:0.16rem;
            color:#5B8796;
            font-size:0.56rem;
            line-height:1.3;
        }

        .focus-chart-head {
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:0.5rem;
            margin-top:0.82rem;
            color:#6FA7B6;
            font-family:"Cascadia Mono",Consolas,monospace;
            font-size:0.48rem;
            font-weight:720;
            letter-spacing:0.09em;
            text-transform:uppercase;
        }

        .sensitivity-svg {
            width:100%;
            height:118px;
            display:block;
            margin-top:0.25rem;
            overflow:visible;
        }

        .focus-cta {
            display:flex;
            align-items:center;
            justify-content:center;
            min-height:34px;
            margin-top:0.55rem;
            color:#86ECFF !important;
            border:1px solid rgba(82,231,255,0.25);
            background:rgba(82,231,255,0.025);
            font-family:"Cascadia Mono",Consolas,monospace;
            font-size:0.53rem;
            font-weight:760;
            letter-spacing:0.08em;
            text-decoration:none !important;
            text-transform:uppercase;
            transition:background 150ms ease,border-color 150ms ease;
        }

        .focus-cta:hover {
            background:rgba(82,231,255,0.07);
            border-color:rgba(137,241,255,0.62);
        }

        .intelligence-dock {
            position:relative;
            z-index:6;
            max-width:1040px;
            margin:-0.25rem auto 1.45rem;
            padding:0.72rem 1rem 0.9rem;
            background:
                linear-gradient(180deg,rgba(4,24,35,0.86),rgba(2,13,21,0.94)),
                radial-gradient(circle at 50% 0%,rgba(82,231,255,0.08),transparent 60%);
            border:1px solid rgba(82,231,255,0.16);
            clip-path:polygon(24px 0,calc(100% - 24px) 0,100% 24px,100% 100%,0 100%,0 24px);
        }

        .dock-kicker {
            display:flex;
            align-items:center;
            justify-content:center;
            gap:0.65rem;
            color:#58CDE2;
            font-family:"Cascadia Mono",Consolas,monospace;
            font-size:0.52rem;
            font-weight:780;
            letter-spacing:0.20em;
            text-transform:uppercase;
        }

        .dock-kicker::before,
        .dock-kicker::after {
            content:"";
            width:95px;
            height:1px;
            background:linear-gradient(90deg,transparent,rgba(82,231,255,0.32));
        }

        .dock-kicker::after {
            background:linear-gradient(90deg,rgba(82,231,255,0.32),transparent);
        }

        .dock-actions {
            display:grid;
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:0.75rem;
            max-width:980px;
            margin:0.68rem auto 0;
        }

        .dock-action {
            display:grid;
            grid-template-columns:36px minmax(0,1fr);
            align-items:center;
            gap:0.62rem;
            min-height:56px;
            padding:0.55rem 0.72rem;
            color:#8BCDDD !important;
            background:rgba(82,231,255,0.018);
            border:1px solid rgba(82,231,255,0.20);
            text-decoration:none !important;
            clip-path:polygon(11px 0,100% 0,100% calc(100% - 11px),calc(100% - 11px) 100%,0 100%,0 11px);
            transition:transform 160ms ease,border-color 160ms ease,background 160ms ease;
        }

        .dock-action:hover {
            transform:translateY(-2px);
            color:#EAFBFF !important;
            border-color:rgba(116,236,255,0.68);
            background:rgba(82,231,255,0.055);
        }

        .dock-action.is-active {
            color:#EAFBFF !important;
            border-color:#58E4FF;
            background:linear-gradient(145deg,rgba(12,80,99,0.44),rgba(26,28,61,0.32));
            box-shadow:0 0 18px rgba(82,231,255,0.11),inset 0 0 18px rgba(82,231,255,0.04);
        }

        .dock-strategy { border-color:rgba(184,140,255,.28); }
        .dock-strategy .dock-icon { color:#C8AAFF; border-color:rgba(184,140,255,.38); }
        .dock-peers { border-color:rgba(82,231,255,.24); }
        .dock-peers .dock-icon { color:#63E8FF; }
        .dock-treasury { border-color:rgba(255,203,102,.28); }
        .dock-treasury .dock-icon { color:#FFD37C; border-color:rgba(255,203,102,.38); }
        .dock-news { border-color:rgba(255,93,122,.25); }
        .dock-news .dock-icon { color:#FF8196; border-color:rgba(255,93,122,.36); }

        .position-capital::before {
            background:linear-gradient(90deg,var(--green),transparent) !important;
            box-shadow:0 0 14px rgba(66,245,167,.50) !important;
        }
        .position-liquidity::before {
            background:linear-gradient(90deg,var(--cyan),transparent) !important;
            box-shadow:0 0 14px rgba(82,231,255,.48) !important;
        }
        .position-earnings::before {
            background:linear-gradient(90deg,var(--violet),transparent) !important;
            box-shadow:0 0 14px rgba(184,140,255,.45) !important;
        }
        .position-risk::before {
            background:linear-gradient(90deg,var(--amber),transparent) !important;
            box-shadow:0 0 14px rgba(255,203,102,.46) !important;
        }

        .position-status-good { color:var(--green); }
        .position-status-neutral { color:var(--cyan-soft); }
        .position-status-watch { color:var(--amber); }

        .balance-footprint {
            display:grid;
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:.62rem;
            margin:.15rem 0 1.1rem;
        }
        .balance-footprint-item {
            padding:.72rem .85rem;
            background:rgba(82,231,255,.022);
            border:1px solid rgba(82,231,255,.10);
        }
        .balance-footprint-label {
            color:#638996;
            font:750 .55rem "Cascadia Mono",Consolas,monospace;
            letter-spacing:.11em;
            text-transform:uppercase;
        }
        .balance-footprint-value {
            margin-top:.25rem;
            color:#E9FBFF;
            font:680 1.05rem "Cascadia Mono",Consolas,monospace;
        }
        .balance-footprint-context {
            margin-top:.18rem;
            color:#557E8D;
            font-size:.64rem;
            line-height:1.35;
        }

        @media (max-width: 1000px) {
            .dock-actions,
            .balance-footprint { grid-template-columns:repeat(2,minmax(0,1fr)); }
        }

        .dock-icon {
            width:34px;
            height:34px;
            display:grid;
            place-items:center;
            color:#62DDF3;
            border:1px solid rgba(82,231,255,0.30);
            border-radius:50%;
            font-family:"Cascadia Mono",Consolas,monospace;
            font-size:0.82rem;
        }

        .dock-copy { min-width:0; }

        .dock-title {
            display:block;
            color:#DFF8FC;
            font-family:"Cascadia Mono",Consolas,monospace;
            font-size:0.66rem;
            font-weight:780;
            letter-spacing:0.08em;
            text-transform:uppercase;
        }

        .dock-metric {
            display:block;
            margin-top:0.15rem;
            overflow:hidden;
            color:#548493;
            font-family:"Cascadia Mono",Consolas,monospace;
            font-size:0.46rem;
            font-weight:690;
            text-overflow:ellipsis;
            white-space:nowrap;
        }

        .trend-up { color:var(--green) !important; }
        .trend-down { color:var(--red) !important; }
        .trend-flat { color:#6F9DAA !important; }

        .strategy-explainer {
            margin:0.8rem 0 1rem;
            padding:1rem 1.05rem;
            background:
                linear-gradient(135deg,rgba(7,34,48,0.92),rgba(7,20,35,0.88)),
                radial-gradient(circle at 10% 0%,rgba(82,231,255,0.08),transparent 42%);
            border:1px solid rgba(82,231,255,0.18);
            clip-path:polygon(0 0,calc(100% - 16px) 0,100% 16px,100% 100%,0 100%);
        }

        .strategy-explainer-grid {
            display:grid;
            grid-template-columns:0.7fr 1.5fr;
            gap:1rem;
            align-items:center;
        }

        .strategy-score-bridge {
            color:#E9FBFF;
            font-family:"Cascadia Mono",Consolas,monospace;
            font-size:1.15rem;
            font-weight:760;
        }

        .strategy-score-bridge span { color:#66E5FA; }

        .strategy-explainer-copy {
            color:#7FA6B5;
            font-size:0.77rem;
            line-height:1.55;
        }

        .strategy-delta-strip {
            display:flex;
            flex-wrap:wrap;
            gap:0.4rem;
            margin-top:0.62rem;
        }

        .strategy-delta-pill {
            padding:0.26rem 0.48rem;
            border:1px solid rgba(82,231,255,0.15);
            background:rgba(82,231,255,0.025);
            color:#8FC8D5;
            font-family:"Cascadia Mono",Consolas,monospace;
            font-size:0.50rem;
            font-weight:700;
        }

        @media (max-width:1120px) {
            .system-grid {
                grid-template-columns:minmax(210px,0.62fr) minmax(520px,1.45fr) minmax(220px,0.64fr) !important;
                gap:0.55rem !important;
            }
            .decision-secondary { display:none; }
            .focus-metric-grid { grid-template-columns:1fr; }
            .sensitivity-svg { height:96px; }
        }

        @media (max-width:860px) {
            .system-grid { grid-template-columns:1fr !important; }
            .decision-panel,.focus-panel { display:none; }
            .dock-actions { grid-template-columns:1fr; }
            .strategy-explainer-grid { grid-template-columns:1fr; }
        }

        /* -------------------------------------------------
           CFO DECISION LAYER / MOTION
           ------------------------------------------------- */
        html { background:#02070c; scroll-behavior:smooth; }

        /* Chrome/Edge can animate same-origin query-parameter navigation.
           Streamlit still reruns Python, but the browser transition hides most
           of the hard page swap and makes vector changes feel continuous. */
        @view-transition { navigation: auto; }
        @keyframes vt-old { to { opacity:0; transform:scale(.998); } }
        @keyframes vt-new { from { opacity:0; transform:translateY(5px); } }
        ::view-transition-old(root) { animation:90ms ease-out both vt-old; }
        ::view-transition-new(root) { animation:220ms cubic-bezier(.2,.8,.2,1) both vt-new; }

        @keyframes page-enter {
            from { opacity:0.72; filter:blur(1px); }
            to { opacity:1; filter:blur(0); }
        }
        @keyframes module-enter {
            from { opacity:0; transform:translateY(8px); filter:blur(1.5px); }
            to { opacity:1; transform:translateY(0); filter:blur(0); }
        }
        .stApp { animation:page-enter 200ms ease-out both; }
        .active-module-banner,.system-overview-note,.decision-flow-card,.cfo-decision-panel,.cfo-change-panel,.intelligence-dock {
            animation:module-enter 260ms cubic-bezier(.2,.8,.2,1) both;
        }
        .executive-delta {
            display:flex; align-items:center; gap:.42rem; margin-top:.68rem; color:#9cecff;
            font-family:"Cascadia Mono",Consolas,monospace; font-size:.70rem; font-weight:700;
        }
        .executive-context { margin-top:.35rem; color:#6f98a7; font-size:.70rem; line-height:1.4; }
        .cfo-change-panel,.cfo-decision-panel {
            position:relative; min-width:0; min-height:410px; padding:1rem 1rem .9rem;
            background:linear-gradient(145deg,rgba(5,27,40,.95),rgba(2,14,23,.86));
            border:1px solid rgba(82,231,255,.18);
            clip-path:polygon(0 0,calc(100% - 13px) 0,100% 13px,100% 100%,0 100%);
        }
        .cfo-panel-kicker { color:#52e7ff; font:700 .56rem "Cascadia Mono",Consolas,monospace; letter-spacing:.16em; text-transform:uppercase; margin-bottom:.22rem; }
        .cfo-panel-title { color:#effdff; font-size:1rem; font-weight:700; margin-bottom:.8rem; }
        .change-row { display:block; text-decoration:none; color:inherit; padding:.84rem 0; border-top:1px solid rgba(82,231,255,.10); transition:transform 160ms ease; }
        .change-row:first-of-type { border-top:0; }
        .change-row:hover { transform:translateX(4px); }
        .change-row-head { display:flex; justify-content:space-between; gap:.6rem; align-items:baseline; }
        .change-name { color:#dff9ff; font-size:.80rem; font-weight:700; }
        .change-value { color:#52e7ff; font:750 .75rem "Cascadia Mono",Consolas,monospace; white-space:nowrap; }
        .change-detail { margin-top:.30rem; color:#7399a7; font-size:.68rem; line-height:1.45; }
        .decision-lens-item { padding:.78rem 0 .82rem; border-top:1px solid rgba(82,231,255,.10); }
        .decision-lens-item:first-of-type { border-top:0; }
        .decision-lens-title { color:#e9fbff; font-size:.78rem; font-weight:700; margin-bottom:.45rem; }
        .decision-lens-line { display:grid; grid-template-columns:50px 1fr; gap:.48rem; margin:.22rem 0; font-size:.66rem; line-height:1.42; }
        .decision-lens-label { color:#52e7ff; font:700 .55rem "Cascadia Mono",Consolas,monospace; letter-spacing:.08em; text-transform:uppercase; }
        .decision-lens-copy { color:#8db0bc; }
        .decision-flow-card { position:relative; padding:1rem 1.05rem; margin-bottom:.72rem; background:linear-gradient(145deg,rgba(7,31,44,.92),rgba(3,17,27,.82)); border:1px solid rgba(82,231,255,.14); clip-path:polygon(0 0,calc(100% - 12px) 0,100% 12px,100% 100%,0 100%); }
        .flow-title { color:#edfaff; font-size:.88rem; font-weight:700; margin-bottom:.62rem; }
        .flow-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.48rem; }
        .flow-cell { padding:.58rem .62rem; background:rgba(82,231,255,.025); border:1px solid rgba(82,231,255,.08); min-width:0; }
        .flow-label { display:block; color:#52e7ff; font:700 .52rem "Cascadia Mono",Consolas,monospace; letter-spacing:.10em; text-transform:uppercase; margin-bottom:.28rem; }
        .flow-copy { color:#93b5c0; font-size:.68rem; line-height:1.42; }
        .decision-strip { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.72rem; margin:0 0 1rem; }
        .decision-strip-item { padding:.85rem .92rem; background:rgba(82,231,255,.025); border:1px solid rgba(82,231,255,.11); }
        .decision-strip-item strong { display:block; color:#e9fbff; font-size:.83rem; margin:.20rem 0 .28rem; }
        .decision-strip-item span:last-child { color:#789eab; font-size:.68rem; line-height:1.42; }
        .dock-metric { line-height:1.35; }
        .intelligence-dock { max-width:1120px; margin-left:auto; margin-right:auto; }
        .dock-actions { gap:.85rem; }
        .dock-action { padding:1rem 1.1rem; min-height:78px; }

        .comparison-basis {
            display:flex; flex-wrap:wrap; gap:.45rem; margin:-.15rem 0 1rem;
        }
        .comparison-chip {
            display:inline-flex; align-items:center; gap:.35rem; padding:.30rem .55rem;
            color:#7fa8b5; background:rgba(82,231,255,.025); border:1px solid rgba(82,231,255,.10);
            font:700 .54rem "Cascadia Mono",Consolas,monospace; letter-spacing:.07em; text-transform:uppercase;
        }
        .comparison-chip strong { color:#bfeef7; font-weight:750; }

        .copilot-action {
            display:inline-flex; align-items:center; gap:.35rem; margin-top:.55rem; padding:.34rem .52rem;
            color:#8eeaff !important; background:rgba(82,231,255,.045); border:1px solid rgba(82,231,255,.18);
            text-decoration:none !important; font:750 .55rem "Cascadia Mono",Consolas,monospace; letter-spacing:.06em; text-transform:uppercase;
            transition:transform 150ms ease, border-color 150ms ease, background 150ms ease, box-shadow 150ms ease;
        }
        .copilot-action:hover {
            transform:translateX(2px); background:rgba(82,231,255,.09); border-color:rgba(82,231,255,.42);
            box-shadow:0 0 18px rgba(82,231,255,.09); color:#e5fcff !important;
        }


        .forward-lens-panel {
            position:relative; padding:1.05rem 1.05rem 1rem;
            background:linear-gradient(145deg,rgba(7,31,44,.92),rgba(3,17,27,.84));
            border:1px solid rgba(82,231,255,.15);
            clip-path:polygon(0 0,calc(100% - 14px) 0,100% 14px,100% 100%,0 100%);
        }
        .forward-lens-kicker {
            color:#52e7ff; font:750 .55rem "Cascadia Mono",Consolas,monospace;
            letter-spacing:.14em; text-transform:uppercase; margin-bottom:.28rem;
        }
        .forward-lens-title {
            color:#effdff; font-size:1rem; font-weight:720; margin-bottom:.75rem;
        }
        .forward-lens-row {
            display:grid; grid-template-columns:92px 1fr; gap:.72rem; align-items:start;
            padding:.70rem 0; border-top:1px solid rgba(82,231,255,.09);
        }
        .forward-lens-row:first-of-type { border-top:0; }
        .forward-lens-label {
            color:#52e7ff; font:750 .54rem "Cascadia Mono",Consolas,monospace;
            letter-spacing:.08em; text-transform:uppercase;
        }
        .forward-lens-value {
            color:#8fb2be; font-size:.72rem; line-height:1.48;
        }
        .forward-lens-value strong { color:#e6fbff; font-weight:720; }
        .forward-lens-meaning {
            margin-top:.85rem; padding:.78rem .82rem;
            background:rgba(82,231,255,.035); border:1px solid rgba(82,231,255,.10);
            color:#9fc1cb; font-size:.70rem; line-height:1.48;
        }
        .forward-lens-meaning strong {
            display:block; margin-bottom:.25rem; color:#dff9ff;
            font:750 .56rem "Cascadia Mono",Consolas,monospace;
            letter-spacing:.08em; text-transform:uppercase;
        }
        .module-action-row {
            display:flex; gap:.75rem; flex-wrap:wrap; margin-top:.85rem;
        }
        .module-action-link {
            flex:0 1 320px; display:flex; align-items:center; justify-content:center;
            min-height:44px; padding:.72rem 1rem; text-decoration:none !important;
            color:#d9f9ff !important;
            background:linear-gradient(90deg,rgba(13,92,116,.58),rgba(6,49,69,.42));
            border:1px solid rgba(82,231,255,.34);
            clip-path:polygon(0 0,calc(100% - 11px) 0,100% 11px,100% 100%,11px 100%,0 calc(100% - 11px));
            font-size:.78rem; font-weight:650; letter-spacing:.02em;
            transition:transform 160ms ease,box-shadow 160ms ease,border-color 160ms ease;
        }
        .module-action-link:hover {
            transform:translateY(-2px); border-color:rgba(82,231,255,.70);
            box-shadow:0 0 24px rgba(82,231,255,.11);
        }
        .scenario-impact-grid {
            display:grid; grid-template-columns:repeat(3,minmax(0,1fr));
            gap:.65rem; margin:.75rem 0 1rem;
        }
        .scenario-impact-cell {
            padding:.78rem .82rem; background:rgba(82,231,255,.025);
            border:1px solid rgba(82,231,255,.10);
        }
        .scenario-impact-label {
            color:#52e7ff; font:750 .52rem "Cascadia Mono",Consolas,monospace;
            letter-spacing:.08em; text-transform:uppercase;
        }
        .scenario-impact-value {
            margin-top:.28rem; color:#edfaff;
            font:700 .88rem "Cascadia Mono",Consolas,monospace;
        }
        .scenario-impact-copy {
            margin-top:.22rem; color:#749aa8; font-size:.65rem; line-height:1.4;
        }
        .scenario-decision-card {
            margin-top:.85rem; padding:1rem 1.05rem;
            background:linear-gradient(145deg,rgba(7,31,44,.90),rgba(3,17,27,.82));
            border:1px solid rgba(82,231,255,.14);
        }
        .scenario-decision-line {
            display:grid; grid-template-columns:68px 1fr; gap:.6rem;
            padding:.36rem 0; font-size:.70rem; line-height:1.45;
        }
        .scenario-decision-line span:first-child {
            color:#52e7ff; font:750 .53rem "Cascadia Mono",Consolas,monospace;
            letter-spacing:.07em; text-transform:uppercase;
        }
        .scenario-decision-line span:last-child { color:#8fb1bd; }

        .news-section-head {
            display:flex; align-items:flex-end; justify-content:space-between; gap:1rem; margin-bottom:.75rem;
        }
        .news-section-copy { color:#668e9d; font-size:.68rem; line-height:1.4; max-width:320px; text-align:right; }
        .news-card {
            position:relative; padding:1rem 1.05rem .95rem; margin-bottom:.72rem; overflow:hidden;
            background:linear-gradient(105deg,rgba(8,31,44,.95),rgba(4,17,27,.80));
            border:1px solid rgba(82,231,255,.14); border-left:2px solid rgba(82,231,255,.60);
            clip-path:polygon(0 0,calc(100% - 12px) 0,100% 12px,100% 100%,0 100%);
        }
        .news-card::after {
            content:""; position:absolute; right:-32px; top:-32px; width:90px; height:90px; border-radius:50%;
            border:1px solid rgba(82,231,255,.09); box-shadow:0 0 0 12px rgba(82,231,255,.018),0 0 0 24px rgba(82,231,255,.010);
        }
        .news-topline { display:flex; align-items:center; gap:.5rem; margin-bottom:.42rem; }
        .news-badge {
            display:inline-flex; align-items:center; gap:.30rem; padding:.20rem .42rem; color:#051219; background:#52e7ff;
            font:850 .50rem "Cascadia Mono",Consolas,monospace; letter-spacing:.10em; text-transform:uppercase;
        }
        .news-meta { color:#668f9f; font:700 .55rem "Cascadia Mono",Consolas,monospace; letter-spacing:.07em; text-transform:uppercase; }
        .news-headline { color:#edfaff; font-size:.86rem; font-weight:720; line-height:1.38; margin-bottom:.52rem; }
        .news-context-grid { display:grid; grid-template-columns:1fr; gap:.28rem; }
        .news-context-line { display:grid; grid-template-columns:82px 1fr; gap:.45rem; font-size:.72rem; line-height:1.4; }
        .news-context-label { color:#52e7ff; font:700 .52rem "Cascadia Mono",Consolas,monospace; letter-spacing:.07em; text-transform:uppercase; }
        .news-context-copy { color:#82a7b4; }
        .news-footer { display:flex; align-items:center; justify-content:space-between; gap:.75rem; margin-top:.58rem; }
        .news-source-link { color:#8eeaff !important; text-decoration:none !important; font:750 .57rem "Cascadia Mono",Consolas,monospace; text-transform:uppercase; letter-spacing:.06em; }
        .news-source-link:hover { color:#e5fcff !important; text-shadow:0 0 10px rgba(82,231,255,.4); }
        .news-public-note { color:#4f7786; font:650 .50rem "Cascadia Mono",Consolas,monospace; letter-spacing:.05em; text-transform:uppercase; }

        @media (max-width:1100px) { .flow-grid,.decision-strip { grid-template-columns:repeat(2,minmax(0,1fr)); } .news-section-head{align-items:flex-start;flex-direction:column;} .news-section-copy{text-align:left;} }
        @media (max-width:760px) { .flow-grid,.decision-strip { grid-template-columns:1fr; } .news-context-line{grid-template-columns:1fr;} }
    </style>
    """
)


# ============================================================
# CONNECTION FAILURE
# ============================================================

if not connection_ok:

    st.error(
        "Unable to load the CFO Cockpit data."
    )

    with st.expander(
        "Technical details"
    ):

        st.exception(
            connection_error
        )

    st.stop()


# ============================================================
# CERTIFIED COCKPIT VALUES
# ============================================================

reporting_date_ts = pd.to_datetime(current_position["as_of_date"])
reporting_date = reporting_date_ts.strftime("%d %B %Y")

cet1_ratio = safe_float(current_position["cet1_ratio_pct"])
total_capital_ratio = safe_float(current_position["total_capital_ratio_pct"])
lcr_ratio = safe_float(current_position["lcr_pct"])
loan_to_deposit_ratio = safe_float(current_position["loan_to_deposit_pct"])
ytd_roe_proxy = safe_float(current_position["annualised_ytd_roe_proxy_pct"])
ytd_cost_income = safe_float(current_position["ytd_cost_income_ratio_pct"])
ytd_nii = safe_float(current_position["ytd_nii_m"])
current_loans_m = safe_float(current_position["loans_m"])
current_deposits_m = safe_float(current_position["deposits_m"])
total_assets = safe_float(current_position["total_assets_m"])
rwa = safe_float(current_position["rwa_m"])
cet1_capital = safe_float(current_position["cet1_capital_m"])
hqla = safe_float(current_position["hqla_m"])
ytd_net_profit = safe_float(current_position["ytd_net_profit_m"])
months_observed = int(safe_float(current_position["months_observed"], 0))
rwa_density_pct = (rwa / total_assets * 100.0) if total_assets else 0.0

# Genuine historical change context.
financial_history_df["date"] = pd.to_datetime(financial_history_df["date"])
for _col in ["deposits_m","stage_2_share_pct","stage_3_share_pct","cet1_capital_m","cet1_ratio_pct","lcr_pct","loan_to_deposit_pct","nii_m","operating_income_m","operating_costs_m","net_profit_m"]:
    financial_history_df[_col] = pd.to_numeric(financial_history_df[_col], errors="coerce")
financial_history_df = financial_history_df.sort_values("date").reset_index(drop=True)
latest_history = financial_history_df.iloc[-1]
previous_history = financial_history_df.iloc[-2] if len(financial_history_df) >= 2 else latest_history
previous_month_label = pd.to_datetime(previous_history["date"]).strftime("%b")
cet1_mom_pp = cet1_ratio - safe_float(previous_history["cet1_ratio_pct"])
lcr_mom_pp = lcr_ratio - safe_float(previous_history["lcr_pct"])
current_stage2_pct = safe_float(latest_history["stage_2_share_pct"])
current_stage3_pct = safe_float(latest_history["stage_3_share_pct"])
stage2_mom_pp = current_stage2_pct - safe_float(previous_history["stage_2_share_pct"])
stage3_mom_pp = current_stage3_pct - safe_float(previous_history["stage_3_share_pct"])

def ytd_metrics_through(history_df, cutoff_date):
    cutoff_date = pd.to_datetime(cutoff_date)
    local = history_df[(history_df["date"].dt.year == cutoff_date.year) & (history_df["date"] <= cutoff_date)].copy()
    if local.empty:
        return None, None
    months = int(local["date"].dt.month.nunique())
    avg_cet1 = local["cet1_capital_m"].mean()
    net_profit = local["net_profit_m"].sum()
    op_income = local["operating_income_m"].sum()
    op_cost = local["operating_costs_m"].sum()
    roe = None if not avg_cet1 or months <= 0 else (net_profit * (12.0 / months) / avg_cet1 * 100.0)
    cir = None if not op_income else (op_cost / op_income * 100.0)
    return roe, cir

prev_ytd_roe, prev_ytd_ci = ytd_metrics_through(financial_history_df, previous_history["date"])
ytd_roe_delta_pp = ytd_roe_proxy - safe_float(prev_ytd_roe, ytd_roe_proxy)
ytd_ci_delta_pp = ytd_cost_income - safe_float(prev_ytd_ci, ytd_cost_income)

monthly_nim_cert_df["month"] = pd.to_datetime(monthly_nim_cert_df["month"])
monthly_nim_cert_df["nim_pct"] = pd.to_numeric(monthly_nim_cert_df["nim_pct"], errors="coerce")
monthly_nim_cert_df["monthly_nii_m"] = pd.to_numeric(monthly_nim_cert_df["monthly_nii_m"], errors="coerce")
valid_nim = monthly_nim_cert_df.dropna(subset=["nim_pct"]).sort_values("month")
latest_cert_nim_row = valid_nim.iloc[-1]
previous_cert_nim_row = valid_nim.iloc[-2] if len(valid_nim) >= 2 else latest_cert_nim_row
cert_current_nim = safe_float(latest_cert_nim_row["nim_pct"])
cert_current_monthly_nii = safe_float(latest_cert_nim_row["monthly_nii_m"])
cert_nim_months = int(monthly_nim_cert_df["month"].nunique())
nim_mom_bps = (cert_current_nim - safe_float(previous_cert_nim_row["nim_pct"])) * 100.0
monthly_nii_change_m = cert_current_monthly_nii - safe_float(previous_cert_nim_row["monthly_nii_m"])

latest_daily_nim = cert_current_nim
latest_daily_nii = 0.0
daily_anomaly_flag = 0
loan_rate_30d_bps = 0.0
deposit_rate_30d_bps = 0.0
spread_30d_bps = 0.0
if daily_latest_df is not None and not daily_latest_df.empty:
    latest_daily = daily_latest_df.iloc[0]
    latest_daily_nim = safe_float(latest_daily["annualised_daily_nim_pct"])
    latest_daily_nii = safe_float(latest_daily["daily_nii_m"])
    daily_anomaly_flag = int(safe_float(latest_daily["has_anomaly"], 0))
if daily_recent_df is not None and not daily_recent_df.empty:
    daily_recent = daily_recent_df.copy()
    daily_recent["date"] = pd.to_datetime(daily_recent["date"])
    for _col in ["weighted_loan_rate_pct","weighted_deposit_rate_pct"]:
        daily_recent[_col] = pd.to_numeric(daily_recent[_col], errors="coerce")
    daily_recent = daily_recent.dropna(subset=["weighted_loan_rate_pct","weighted_deposit_rate_pct"]).sort_values("date")
    if not daily_recent.empty:
        _d0, _d1 = daily_recent.iloc[0], daily_recent.iloc[-1]
        loan_rate_30d_bps = (safe_float(_d1["weighted_loan_rate_pct"]) - safe_float(_d0["weighted_loan_rate_pct"])) * 100.0
        deposit_rate_30d_bps = (safe_float(_d1["weighted_deposit_rate_pct"]) - safe_float(_d0["weighted_deposit_rate_pct"])) * 100.0
        spread_30d_bps = loan_rate_30d_bps - deposit_rate_30d_bps

deposit_leader = None
deposit_laggard = None
negative_deposit_countries = 0
total_deposit_30d_change_m = 0.0
total_deposit_30d_change_pct = 0.0
if deposit_country_df is not None and not deposit_country_df.empty:
    for _col in ["deposit_change_30d_pct","deposit_balance_m","deposit_change_30d_m"]:
        deposit_country_df[_col] = pd.to_numeric(deposit_country_df[_col], errors="coerce")
    deposit_leader = deposit_country_df.sort_values("deposit_change_30d_pct", ascending=False).iloc[0]
    deposit_laggard = deposit_country_df.sort_values("deposit_change_30d_pct", ascending=True).iloc[0]
    negative_deposit_countries = int((deposit_country_df["deposit_change_30d_pct"] < 0).sum())
    _current_deposits = deposit_country_df["deposit_balance_m"].sum()
    total_deposit_30d_change_m = deposit_country_df["deposit_change_30d_m"].sum()
    _prior_deposits = _current_deposits - total_deposit_30d_change_m
    if _prior_deposits:
        total_deposit_30d_change_pct = total_deposit_30d_change_m / _prior_deposits * 100.0

current_credit_watch_count = 0
credit_hotspot = None
credit_hotspot_stage2_delta_pp = None
if credit_detail_df is not None and not credit_detail_df.empty:
    credit_detail_df["credit_watch_flag"] = pd.to_numeric(credit_detail_df["credit_watch_flag"], errors="coerce").fillna(0)
    credit_detail_df["weighted_stage_2_share_pct"] = pd.to_numeric(credit_detail_df["weighted_stage_2_share_pct"], errors="coerce")
    credit_detail_df["weighted_stage_3_share_pct"] = pd.to_numeric(credit_detail_df["weighted_stage_3_share_pct"], errors="coerce")
    current_credit_watch_count = int(credit_detail_df["credit_watch_flag"].sum())
    credit_hotspot = credit_detail_df.sort_values(["credit_watch_flag","weighted_stage_2_share_pct","weighted_stage_3_share_pct"], ascending=[False,False,False]).iloc[0]
    if credit_trend_df is not None and not credit_trend_df.empty:
        ct = credit_trend_df.copy()
        ct["date"] = pd.to_datetime(ct["date"])
        ct["weighted_stage_2_share_pct"] = pd.to_numeric(ct["weighted_stage_2_share_pct"], errors="coerce")
        match = ct[(ct["country"] == credit_hotspot["country"]) & (ct["business_line"] == credit_hotspot["business_line"])].sort_values("date")
        if len(match) >= 2:
            credit_hotspot_stage2_delta_pp = safe_float(match.iloc[-1]["weighted_stage_2_share_pct"]) - safe_float(match.iloc[0]["weighted_stage_2_share_pct"])

high_impact_news_count = 0
top_news = None
geo_focus = None
if news_recent_df is not None and not news_recent_df.empty:
    potential_levels = news_recent_df["potential_impact_level"].fillna("").astype(str).str.upper()
    high_impact_news_count = int((potential_levels == "HIGH").sum())
    top_news = news_recent_df.iloc[0]
if geo_news_df is not None and not geo_news_df.empty:
    geo_focus = geo_news_df.iloc[0]

treasury_market_value_m = treasury_unrealised_pnl_m = treasury_duration = treasury_dv01 = 0.0
if treasury_summary_df is not None and not treasury_summary_df.empty:
    treasury_summary = treasury_summary_df.iloc[0]
    treasury_market_value_m = safe_float(treasury_summary["market_value_m"])
    treasury_unrealised_pnl_m = safe_float(treasury_summary["unrealized_pnl_m"])
    treasury_duration = safe_float(treasury_summary["weighted_modified_duration"])
    treasury_dv01 = safe_float(treasury_summary["portfolio_dv01_m_per_bp"])
else:
    treasury_summary = None

treasury_rate50_impact_m = 0.0
if treasury_rate50_df is not None and not treasury_rate50_df.empty:
    treasury_rate50 = treasury_rate50_df.iloc[0]
    treasury_rate50_impact_m = safe_float(treasury_rate50["economic_value_impact_m"])
else:
    treasury_rate50 = None
treasury_rate50_text = f"-€{abs(treasury_rate50_impact_m) / 1000:.2f}bn" if treasury_rate50_impact_m < 0 else f"+€{treasury_rate50_impact_m / 1000:.2f}bn" if treasury_rate50_impact_m > 0 else "—"

treasury_market_change_m = treasury_market_change_pct = None
treasury_market_trend_label = "Prior snapshot"
treasury_market_trend_css = "trend-flat"
if treasury_snapshot_history_df is not None and len(treasury_snapshot_history_df) >= 2:
    treasury_hist = treasury_snapshot_history_df.copy()
    treasury_hist["as_of_date"] = pd.to_datetime(treasury_hist["as_of_date"])
    treasury_hist["market_value_m"] = pd.to_numeric(treasury_hist["market_value_m"], errors="coerce")
    treasury_hist = treasury_hist.dropna().sort_values("as_of_date", ascending=False)
    if len(treasury_hist) >= 2:
        current_snap, prior_snap = treasury_hist.iloc[0], treasury_hist.iloc[1]
        treasury_market_change_m = float(current_snap["market_value_m"] - prior_snap["market_value_m"])
        if float(prior_snap["market_value_m"]) != 0:
            treasury_market_change_pct = treasury_market_change_m / float(prior_snap["market_value_m"]) * 100.0
        day_gap = int((current_snap["as_of_date"] - prior_snap["as_of_date"]).days)
        treasury_market_trend_label = "1D move" if day_gap == 1 else "vs prev snapshot"
        treasury_market_trend_css = "trend-up" if treasury_market_change_m > 0 else "trend-down" if treasury_market_change_m < 0 else "trend-flat"
treasury_market_trend_text = "— / unavailable" if treasury_market_change_m is None else f"{treasury_market_change_m:+,.0f}m" if treasury_market_change_pct is None else f"{treasury_market_change_m:+,.0f}m / {treasury_market_change_pct:+.2f}%"

peer_profitability_median = peer_cet1_median = peer_cost_income_median = 0.0
peer_count = 0
peer_plot_df = pd.DataFrame()
if peer_benchmark_df is not None and not peer_benchmark_df.empty:
    peer_count = len(peer_benchmark_df)
    profit_values = peer_benchmark_df["profitability_peer_median_pct"].dropna()
    cet1_values = peer_benchmark_df["cet1_peer_median_pct"].dropna()
    cost_values = peer_benchmark_df["cost_income_peer_median_pct"].dropna()
    peer_profitability_median = safe_float(profit_values.iloc[0]) if not profit_values.empty else 0.0
    peer_cet1_median = safe_float(cet1_values.iloc[0]) if not cet1_values.empty else 0.0
    peer_cost_income_median = safe_float(cost_values.iloc[0]) if not cost_values.empty else 0.0
    peer_plot_df = peer_benchmark_df[["bank_name","reported_return_pct","cet1_ratio_pct","cost_income_ratio_pct","total_assets_m","return_metric_type"]].copy()
    peer_plot_df["is_our_bank"] = "Peer"
    our_row = pd.DataFrame([{"bank_name":"Our Bank","reported_return_pct":ytd_roe_proxy,"cet1_ratio_pct":cet1_ratio,"cost_income_ratio_pct":ytd_cost_income,"total_assets_m":total_assets,"return_metric_type":"Annualised YTD ROE proxy","is_our_bank":"Our Bank"}])
    peer_plot_df = pd.concat([peer_plot_df, our_row], ignore_index=True)

roe_peer_gap_pp = ytd_roe_proxy - peer_profitability_median
cet1_peer_gap_pp = cet1_ratio - peer_cet1_median
efficiency_peer_advantage_pp = peer_cost_income_median - ytd_cost_income

top_strategy = None
top_capability_gap = None
if strategic_radar_df is not None and not strategic_radar_df.empty:
    top_strategy = strategic_radar_df.sort_values("opportunity_rank").iloc[0]
if capability_gaps_df is not None and not capability_gaps_df.empty:
    top_capability_gap = capability_gaps_df.sort_values("capability_gap", ascending=False).iloc[0]

strongest_hedge = None
if hedge_options_df is not None and not hedge_options_df.empty:
    strongest_hedge = hedge_options_df.sort_values("dv01_reduction_pct", ascending=False).iloc[0]

def arrow_delta(value, unit="pp"):
    arrow = "↑" if value > 0 else "↓" if value < 0 else "→"
    return f"{arrow} {abs(value):.1f}{unit}"

def clip_ui_text(value, max_chars=62):
    text_value = str(value or "").strip()
    if len(text_value) <= max_chars:
        return text_value
    return text_value[: max_chars - 1].rstrip() + "…"


def build_rate_sensitivity_svg(df, width=300, height=118):
    """Build a compact certified rate-sensitivity mini chart for the home HUD."""
    if df is None or df.empty:
        return '<svg class="sensitivity-svg" viewBox="0 0 300 118"></svg>'
    local = df.copy()
    for column in ["rate_shock_bps", "credit_spread_shock_bps", "economic_value_impact_m"]:
        local[column] = pd.to_numeric(local[column], errors="coerce")
    local["credit_spread_shock_bps"] = local["credit_spread_shock_bps"].fillna(0.0)
    local = local[local["credit_spread_shock_bps"].abs() < 0.001]
    local = local.dropna(subset=["rate_shock_bps", "economic_value_impact_m"]).sort_values("rate_shock_bps")
    if len(local) < 2:
        return '<svg class="sensitivity-svg" viewBox="0 0 300 118"></svg>'
    x_values = local["rate_shock_bps"].astype(float).tolist()
    y_values = local["economic_value_impact_m"].astype(float).tolist()
    left, right, top, bottom = 24.0, width - 12.0, 12.0, height - 22.0
    x_min, x_max = min(x_values), max(x_values)
    y_min, y_max = min(y_values + [0.0]), max(y_values + [0.0])
    if x_max == x_min:
        x_max = x_min + 1.0
    if y_max == y_min:
        y_max = y_min + 1.0
    def sx(x):
        return left + (x - x_min) / (x_max - x_min) * (right - left)
    def sy(y):
        return bottom - (y - y_min) / (y_max - y_min) * (bottom - top)
    points = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in zip(x_values, y_values))
    zero_y = sy(0.0)
    circles = []
    labels = []
    for x, y in zip(x_values, y_values):
        px, py = sx(x), sy(y)
        circles.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.4" fill="#DDFBFF" stroke="#52E7FF" stroke-width="1.2" />')
        labels.append(f'<text x="{px:.1f}" y="{height - 5:.1f}" text-anchor="middle" fill="#557F8E" font-size="8" font-family="Cascadia Mono, Consolas, monospace">{x:+.0f}bp</text>')
    return (
        f'<svg class="sensitivity-svg" viewBox="0 0 {width} {height}" role="img" aria-label="Certified treasury economic-value sensitivity to pure rate shocks">'
        f'<line x1="{left}" y1="{zero_y:.1f}" x2="{right}" y2="{zero_y:.1f}" stroke="#1A4B5A" stroke-width="1" stroke-dasharray="3 4" />'
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#123744" stroke-width="1" />'
        f'<polyline points="{points}" fill="none" stroke="#52E7FF" stroke-width="2.2" filter="drop-shadow(0 0 4px rgba(82,231,255,0.35))" />'
        + "".join(circles) + "".join(labels) + '</svg>'
    )


executive_change_count = 3

deposit_signal_primary = "Deposit movement unavailable"
deposit_signal_secondary = "No latest country deposit observation"
if deposit_leader is not None and deposit_laggard is not None:
    deposit_signal_primary = f"{total_deposit_30d_change_pct:+.2f}% / €{total_deposit_30d_change_m / 1000:+.2f}bn over 30D"
    deposit_signal_secondary = f"{html.escape(str(deposit_leader['country']))} leads {safe_float(deposit_leader['deposit_change_30d_pct']):+.1f}% · {html.escape(str(deposit_laggard['country']))} lowest {safe_float(deposit_laggard['deposit_change_30d_pct']):+.1f}%"

credit_signal_primary = "Credit movement unavailable"
credit_signal_secondary = "No latest credit observation"
if credit_hotspot is not None:
    credit_delta_text = "30D comparison unavailable" if credit_hotspot_stage2_delta_pp is None else f"{credit_hotspot_stage2_delta_pp:+.2f}pp vs 30D"
    credit_signal_primary = f"{html.escape(str(credit_hotspot['country']))} / {html.escape(str(credit_hotspot['business_line']))} Stage 2 {safe_float(credit_hotspot['weighted_stage_2_share_pct']):.1f}%"
    credit_signal_secondary = f"{credit_delta_text} · {current_credit_watch_count} current certified watch(es)"

news_signal_primary = "External intelligence unavailable"
news_signal_secondary = "No recent public-source item in the configured window"
news_why = "No current external-development context available."
news_impact = "—"
news_next = "Review external-intelligence feed when new items arrive."
if top_news is not None:
    news_signal_primary = html.escape(clip_ui_text(top_news["headline"], 58))
    news_signal_secondary = f"{html.escape(str(top_news['source']))} · potential metric: {html.escape(str(top_news['primary_affected_metric']))}"
    news_why = html.escape(clip_ui_text(top_news.get("bank_impact_summary", ""), 120))
    news_impact = html.escape(str(top_news["primary_affected_metric"]))
    news_next = html.escape(clip_ui_text(top_news.get("suggested_action", ""), 105))

nim_signal_primary = f"NIM {cert_current_nim:.2f}% / {nim_mom_bps:+.1f} bps MoM"
nim_signal_secondary = f"Monthly NII €{cert_current_monthly_nii:,.0f}m · pricing spread {spread_30d_bps:+.1f} bps over 30D"
spread_direction = "widened" if spread_30d_bps > 0 else "narrowed" if spread_30d_bps < 0 else "was unchanged"
nim_why = f"Loan-versus-deposit pricing spread {spread_direction} by {abs(spread_30d_bps):.1f} bps over 30D."
nim_impact = f"Latest monthly NII is €{cert_current_monthly_nii:,.0f}m ({monthly_nii_change_m:+,.0f}m vs prior month)."
nim_next = "Inspect country and business-line pricing/pass-through drivers in Morning Brief or Copilot."
deposit_why = f"Growth is uneven: {str(deposit_leader['country']) if deposit_leader is not None else '—'} leads while {str(deposit_laggard['country']) if deposit_laggard is not None else '—'} is slowest."
deposit_impact = f"Funding base changed by €{total_deposit_30d_change_m / 1000:+.2f}bn over 30D."
deposit_next = "Review slower-growth markets and business lines before changing deposit pricing."
credit_why = "Stage 2 concentration is highest in the identified country/business line; the certified data does not establish the underlying cause."
credit_impact = f"Stage 2 is {safe_float(credit_hotspot['weighted_stage_2_share_pct']):.1f}%" if credit_hotspot is not None else "Credit impact unavailable"
credit_next = "Investigate migration drivers and provisioning exposure before taking action."

treasury_sensitivity_svg = build_rate_sensitivity_svg(treasury_scenarios_df)

# Strategy ranking explainer. The X/Y opportunity map visualises only strategic
# fit and financial attractiveness; the ranking itself uses the full seven-factor
# composite defined upstream in generate_strategic_radar.py.
second_strategy = None
strategy_score_gap = 0.0
strategy_delta_df = pd.DataFrame()
strategy_advantage_pills = []

if strategic_radar_df is not None and len(strategic_radar_df) >= 2:
    ranked_strategy = strategic_radar_df.sort_values("opportunity_rank").reset_index(drop=True)
    top_strategy = ranked_strategy.iloc[0]
    second_strategy = ranked_strategy.iloc[1]
    strategy_score_gap = (
        safe_float(top_strategy["overall_opportunity_score"])
        - safe_float(second_strategy["overall_opportunity_score"])
    )

    component_spec = [
        ("Strategic fit", "strategic_fit_score", 0.30, False),
        ("Financial attractiveness", "financial_attractiveness_score", 0.15, False),
        ("Integration feasibility", "integration_feasibility_score", 0.15, False),
        ("Affordability", "affordability_score", 0.10, False),
        ("Innovation", "innovation_score", 0.15, False),
        ("Time to value", "time_to_value_score", 0.10, False),
        ("Regulatory simplicity", "regulatory_complexity_score", 0.05, True),
    ]

    delta_rows = []
    for label, column, weight, inverse in component_spec:
        top_value = safe_float(top_strategy[column])
        second_value = safe_float(second_strategy[column])
        if inverse:
            top_value = 100.0 - top_value
            second_value = 100.0 - second_value
        delta = weight * (top_value - second_value)
        delta_rows.append({"Component": label, "Weighted delta": delta})

    strategy_delta_df = pd.DataFrame(delta_rows)

    positive = strategy_delta_df[strategy_delta_df["Weighted delta"] > 0].sort_values(
        "Weighted delta", ascending=False
    )
    for _, row in positive.head(3).iterrows():
        strategy_advantage_pills.append(
            f"{row['Component']} +{row['Weighted delta']:.1f} pts"
        )


# ============================================================
# CERTIFIED HORIZON BASELINE
# ============================================================
# The Horizon is a deterministic "momentum-decay" baseline built from the
# refreshed certified actuals. It answers a narrow question:
#
#   "If the latest balance-sheet trend continues and the most recent repricing
#    momentum fades progressively, where does the current run-rate land?"
#
# It is NOT an official forecast, budget or management guidance. The financial
# logic is explicit and repeatable so that the CFO can challenge the assumptions.


def build_horizon_baseline(
    monthly_df: pd.DataFrame,
    months_ahead: int,
    current_loans_m: float,
    current_deposits_m: float,
    current_loan_rate_pct: float,
    current_deposit_rate_pct: float,
    loan_rate_30d_bps: float,
    deposit_rate_30d_bps: float,
    deposit_growth_30d_pct: float,
):
    local = monthly_df.copy().sort_values("month").dropna(
        subset=["nim_pct", "monthly_nii_m", "avg_interest_earning_assets_m"]
    )
    if local.empty:
        return pd.DataFrame(), {}

    for col in ["nim_pct", "monthly_nii_m", "avg_interest_earning_assets_m"]:
        local[col] = pd.to_numeric(local[col], errors="coerce")
    local = local.dropna(
        subset=["nim_pct", "monthly_nii_m", "avg_interest_earning_assets_m"]
    )

    latest = local.iloc[-1]
    latest_month = pd.Timestamp(latest["month"]).to_period("M").to_timestamp()
    latest_nim = float(latest["nim_pct"])

    assets = local["avg_interest_earning_assets_m"].astype(float)
    asset_growth_series = (
        assets.pct_change()
        .replace([float("inf"), float("-inf")], pd.NA)
        .dropna()
    )
    monthly_asset_growth = (
        float(asset_growth_series.tail(3).median())
        if not asset_growth_series.empty
        else 0.0
    )
    monthly_asset_growth = max(-0.02, min(0.02, monthly_asset_growth))

    monthly_deposit_growth = max(
        -0.03,
        min(0.03, float(deposit_growth_30d_pct) / 100.0),
    )

    base_annual_nii = latest_nim / 100.0 * float(current_loans_m)
    simplified_base_nii = (
        float(current_loans_m) * float(current_loan_rate_pct) / 100.0
        - float(current_deposits_m) * float(current_deposit_rate_pct) / 100.0
    )
    residual_annual_nii = base_annual_nii - simplified_base_nii

    rows = []
    for _, row in local.iterrows():
        rows.append(
            {
                "month": pd.Timestamp(row["month"]).to_period("M").to_timestamp(),
                "month_label": pd.Timestamp(row["month"]).strftime("%b"),
                "nim_pct": float(row["nim_pct"]),
                "monthly_nii_m": float(row["monthly_nii_m"]),
                "avg_interest_earning_assets_m": float(
                    row["avg_interest_earning_assets_m"]
                ),
                "series": "Actual",
                "loan_rate_pct": None,
                "deposit_rate_pct": None,
            }
        )

    projected_assets = float(current_loans_m)
    projected_deposits = float(current_deposits_m)
    projected_loan_rate = float(current_loan_rate_pct)
    projected_deposit_rate = float(current_deposit_rate_pct)
    forecast_nii_total = 0.0

    repricing_decay = [0.50, 0.25, 0.125, 0.0625]

    for step in range(1, months_ahead + 1):
        month = latest_month + pd.offsets.MonthBegin(step)
        decay = repricing_decay[min(step - 1, len(repricing_decay) - 1)]

        projected_assets *= (1.0 + monthly_asset_growth)
        projected_deposits *= (1.0 + monthly_deposit_growth)

        projected_loan_rate += (float(loan_rate_30d_bps) / 100.0) * decay
        projected_deposit_rate += (
            float(deposit_rate_30d_bps) / 100.0
        ) * decay

        annual_nii = (
            projected_assets * projected_loan_rate / 100.0
            - projected_deposits * projected_deposit_rate / 100.0
            + residual_annual_nii
        )

        forecast_nim = (
            annual_nii / projected_assets * 100.0
            if projected_assets
            else latest_nim
        )

        days = int(pd.Period(month, freq="M").days_in_month)
        forecast_nii = annual_nii * days / 365.0
        forecast_nii_total += forecast_nii

        rows.append(
            {
                "month": month,
                "month_label": month.strftime("%b"),
                "nim_pct": forecast_nim,
                "monthly_nii_m": forecast_nii,
                "avg_interest_earning_assets_m": projected_assets,
                "series": "Baseline",
                "loan_rate_pct": projected_loan_rate,
                "deposit_rate_pct": projected_deposit_rate,
            }
        )

    output = pd.DataFrame(rows).sort_values("month").reset_index(drop=True)

    actual_nii_ytd = float(local["monthly_nii_m"].sum())
    year_end_nim = float(output.iloc[-1]["nim_pct"])
    current_to_year_end_bps = (year_end_nim - latest_nim) * 100.0
    full_year_nii = actual_nii_ytd + forecast_nii_total

    forward = output[output["series"] == "Baseline"].copy()
    first_forward_nim = (
        float(forward.iloc[0]["nim_pct"])
        if not forward.empty
        else latest_nim
    )
    implied_first_month_bps = (first_forward_nim - latest_nim) * 100.0

    metrics = {
        "latest_nim_pct": latest_nim,
        "year_end_nim_pct": year_end_nim,
        "current_to_year_end_bps": current_to_year_end_bps,
        "first_month_nim_change_bps": implied_first_month_bps,
        "trailing_asset_growth_pct": monthly_asset_growth * 100.0,
        "deposit_growth_run_rate_pct": monthly_deposit_growth * 100.0,
        "forecast_nii_remaining_m": forecast_nii_total,
        "full_year_nii_m": full_year_nii,
        "actual_nii_ytd_m": actual_nii_ytd,
        "actual_months": int(len(local)),
        "residual_annual_nii_m": residual_annual_nii,
        "baseline_method": (
            "Latest certified NIM and balance sheet; earning assets follow the "
            "median of the latest 3 monthly moves; deposits use the latest 30D "
            "growth rate; only 50% of the latest 30D loan/deposit repricing is "
            "carried into September and that repricing momentum halves each month."
        ),
    }
    return output, metrics


current_loan_rate_pct = 0.0
current_deposit_rate_pct = 0.0
if daily_recent_df is not None and not daily_recent_df.empty:
    _horizon_daily = daily_recent_df.copy()
    _horizon_daily["date"] = pd.to_datetime(_horizon_daily["date"])
    _horizon_daily = _horizon_daily.sort_values("date")
    _latest_rate_row = _horizon_daily.iloc[-1]
    current_loan_rate_pct = safe_float(
        _latest_rate_row["weighted_loan_rate_pct"]
    )
    current_deposit_rate_pct = safe_float(
        _latest_rate_row["weighted_deposit_rate_pct"]
    )


horizon_baseline_df, horizon_metrics = build_horizon_baseline(
    monthly_nim_cert_df,
    months_ahead=4,
    current_loans_m=current_loans_m,
    current_deposits_m=current_deposits_m,
    current_loan_rate_pct=current_loan_rate_pct,
    current_deposit_rate_pct=current_deposit_rate_pct,
    loan_rate_30d_bps=loan_rate_30d_bps,
    deposit_rate_30d_bps=deposit_rate_30d_bps,
    deposit_growth_30d_pct=total_deposit_30d_change_pct,
)

horizon_year_end_nim = safe_float(
    horizon_metrics.get("year_end_nim_pct"), cert_current_nim
)
horizon_change_bps = safe_float(
    horizon_metrics.get("current_to_year_end_bps"), 0.0
)
horizon_first_month_bps = safe_float(
    horizon_metrics.get("first_month_nim_change_bps"), 0.0
)
horizon_full_year_nii_m = safe_float(
    horizon_metrics.get("full_year_nii_m"), ytd_nii
)
horizon_remaining_nii_m = safe_float(
    horizon_metrics.get("forecast_nii_remaining_m"), 0.0
)
horizon_asset_growth_pct = safe_float(
    horizon_metrics.get("trailing_asset_growth_pct"), 0.0
)
horizon_deposit_growth_pct = safe_float(
    horizon_metrics.get("deposit_growth_run_rate_pct"), 0.0
)
horizon_method_text = str(
    horizon_metrics.get("baseline_method", "")
)


# ============================================================
# CERTIFIED-ANCHOR WHAT-IF ENGINE
# ============================================================


def calculate_certified_scenario(
    ecb_shock_bps: float,
    deposit_balance_shock_pct: float,
    horizon_days: int,
    loan_beta_pct: float = 35.0,
    deposit_beta_pct: float = 55.0,
    replacement_funding_rate_pct: float = 3.25,
):
    horizon_factor = max(
        0.0,
        min(1.0, float(horizon_days) / 365.0),
    )

    loan_beta = float(loan_beta_pct) / 100.0
    deposit_beta = float(deposit_beta_pct) / 100.0

    base_loan_rate = float(current_loan_rate_pct)
    base_deposit_rate = float(current_deposit_rate_pct)
    base_loans = float(current_loans_m)
    base_deposits = float(current_deposits_m)

    loan_rate_change_pp = (
        float(ecb_shock_bps) / 100.0 * loan_beta * horizon_factor
    )
    deposit_rate_change_pp = (
        float(ecb_shock_bps) / 100.0 * deposit_beta * horizon_factor
    )

    scenario_loan_rate = base_loan_rate + loan_rate_change_pp
    scenario_deposit_rate = base_deposit_rate + deposit_rate_change_pp

    scenario_deposits = (
        base_deposits
        * (1.0 + float(deposit_balance_shock_pct) / 100.0)
    )

    lost_deposits_m = max(
        0.0,
        base_deposits - scenario_deposits,
    )
    added_deposits_m = max(
        0.0,
        scenario_deposits - base_deposits,
    )

    base_annual_nii_m = (
        cert_current_nim / 100.0 * base_loans
    )

    loan_repricing_impact_m = (
        base_loans * loan_rate_change_pp / 100.0
    )

    base_deposit_expense_m = (
        base_deposits * base_deposit_rate / 100.0
    )

    scenario_deposit_expense_m = (
        scenario_deposits * scenario_deposit_rate / 100.0
    )

    replacement_funding_expense_m = (
        lost_deposits_m
        * float(replacement_funding_rate_pct)
        / 100.0
    )

    funding_cost_change_m = (
        scenario_deposit_expense_m
        + replacement_funding_expense_m
        - base_deposit_expense_m
    )

    scenario_annual_nii_m = (
        base_annual_nii_m
        + loan_repricing_impact_m
        - funding_cost_change_m
    )

    annual_nii_impact_m = (
        scenario_annual_nii_m - base_annual_nii_m
    )

    horizon_nii_impact_m = (
        annual_nii_impact_m * horizon_factor
    )

    scenario_nim_pct = (
        scenario_annual_nii_m / base_loans * 100.0
        if base_loans
        else cert_current_nim
    )

    nim_impact_bps = (
        scenario_nim_pct - cert_current_nim
    ) * 100.0

    return {
        "current_annual_nii_m": base_annual_nii_m,
        "scenario_annual_nii_m": scenario_annual_nii_m,
        "annual_nii_impact_m": annual_nii_impact_m,
        "horizon_nii_impact_m": horizon_nii_impact_m,
        "current_nim_pct": cert_current_nim,
        "scenario_nim_pct": scenario_nim_pct,
        "nim_impact_bps": nim_impact_bps,
        "current_loan_rate_pct": base_loan_rate,
        "scenario_loan_rate_pct": scenario_loan_rate,
        "current_deposit_rate_pct": base_deposit_rate,
        "scenario_deposit_rate_pct": scenario_deposit_rate,
        "loan_repricing_impact_m": loan_repricing_impact_m,
        "funding_cost_change_m": funding_cost_change_m,
        "lost_deposits_m": lost_deposits_m,
        "added_deposits_m": added_deposits_m,
        "replacement_funding_expense_m": replacement_funding_expense_m,
        "horizon_factor": horizon_factor,
    }


# A single deterministic preview is shown on the home radial so the CFO can
# see the current -> outlook -> stress storyline without opening the full module.
home_scenario_preview = calculate_certified_scenario(
    ecb_shock_bps=-50,
    deposit_balance_shock_pct=0.0,
    horizon_days=365,
)
home_scenario_nim_impact_bps = safe_float(home_scenario_preview["nim_impact_bps"])
home_scenario_nii_impact_m = safe_float(home_scenario_preview["horizon_nii_impact_m"])
home_scenario_nim_pct = safe_float(home_scenario_preview["scenario_nim_pct"])


# ============================================================
# STATUS HELPERS
# ============================================================

def status_class(status):

    if status == "ALERT":
        return "kpi-alert"

    if status == "WATCH":
        return "kpi-watch"

    return "kpi-track"


def alert_class(status):

    if status == "ALERT":
        return "alert-red"

    if status == "WATCH":
        return "alert-amber"

    return "alert-green"


def signal_class(status):

    if status == "ALERT":
        return "signal-alert"

    if status == "WATCH":
        return "signal-watch"

    return "signal-track"


# ============================================================
# CERTIFIED MORNING-BRIEF CHARTS
# ============================================================

cert_nim_chart_df = (
    monthly_nim_cert_df[["month", "nim_pct"]]
    .dropna()
    .rename(columns={"nim_pct": "NIM"})
    .sort_values("month")
    .copy()
)
cert_nim_chart_df["month_label"] = cert_nim_chart_df["month"].dt.strftime("%b")
cert_nim_chart_df["month_order"] = range(len(cert_nim_chart_df))


def build_certified_nim_chart(height=300):
    """Render the certified Jan-Aug NIM path without an area baseline.

    Vega-Lite area marks introduce a zero baseline, which can flatten a narrow
    percentage series visually. A single quantitative scale keeps the 1.x% path
    correctly expanded.
    """
    chart_df = cert_nim_chart_df.dropna(subset=["NIM"]).copy()
    if chart_df.empty:
        return alt.Chart(pd.DataFrame({"month_label": [], "NIM": []})).mark_line()

    chart_df["NIM"] = pd.to_numeric(chart_df["NIM"], errors="coerce")
    chart_df = chart_df.dropna(subset=["NIM"]).reset_index(drop=True)
    chart_df["month_order"] = range(len(chart_df))

    y_min = float(chart_df["NIM"].min())
    y_max = float(chart_df["NIM"].max())
    spread = max(y_max - y_min, 0.04)
    padding = spread * 0.22
    month_sort = chart_df["month_label"].tolist()

    base = alt.Chart(chart_df).encode(
        x=alt.X(
            "month_label:O",
            sort=month_sort,
            title=None,
            axis=alt.Axis(
                labelAngle=0,
                grid=False,
                labelColor="#789EAC",
                labelFont="Cascadia Mono",
                labelFontSize=11,
                labelPadding=10,
                domainColor="#173B49",
                tickColor="#173B49",
            ),
        ),
        y=alt.Y(
            "NIM:Q",
            title="Certified NIM (%)",
            scale=alt.Scale(domain=[y_min - padding, y_max + padding], zero=False, nice=False),
            axis=alt.Axis(
                format=".2f",
                tickCount=5,
                labelColor="#789EAC",
                labelFont="Cascadia Mono",
                labelFontSize=11,
                titleColor="#789EAC",
                titleFont="Cascadia Mono",
                titleFontSize=10,
                grid=True,
                gridColor="#12313E",
                gridOpacity=0.72,
                domain=False,
                ticks=False,
            ),
        ),
        tooltip=[
            alt.Tooltip("month:T", title="Month", format="%B %Y"),
            alt.Tooltip("NIM:Q", title="NIM", format=".3f"),
        ],
    )

    line = base.mark_line(strokeWidth=3, color="#52E7FF", interpolate="linear")
    points = base.mark_circle(size=58, color="#52E7FF", stroke="#DDFBFF", strokeWidth=1.2)
    return (line + points).properties(height=height).configure_view(
        stroke=None,
        fill="transparent",
    )


def build_deposit_country_chart(height=245):

    chart_df = deposit_country_df.copy()
    chart_df = chart_df.dropna(subset=["deposit_change_30d_pct"])

    if chart_df.empty:
        return alt.Chart(
            pd.DataFrame({"country": [], "deposit_change_30d_pct": []})
        ).mark_bar()

    return (
        alt.Chart(chart_df)
        .mark_bar(
            cornerRadiusEnd=3,
            color="#52E7FF",
            opacity=0.78,
        )
        .encode(
            x=alt.X(
                "deposit_change_30d_pct:Q",
                title="30-day deposit change (%)",
                axis=alt.Axis(
                    labelColor="#789EAC",
                    titleColor="#789EAC",
                    gridColor="#12313E",
                    gridOpacity=0.55,
                    domain=False,
                ),
            ),
            y=alt.Y(
                "country:N",
                title=None,
                sort="-x",
                axis=alt.Axis(
                    labelColor="#B8D4DC",
                    labelFontSize=11,
                    domain=False,
                    ticks=False,
                ),
            ),
            tooltip=[
                alt.Tooltip("country:N", title="Country"),
                alt.Tooltip(
                    "deposit_change_30d_pct:Q",
                    title="30-day change",
                    format="+.2f",
                ),
                alt.Tooltip(
                    "deposit_balance_m:Q",
                    title="Deposits (€m)",
                    format=",.0f",
                ),
            ],
        )
        .properties(height=height)
        .configure_view(stroke=None, fill="transparent")
    )


# ============================================================
# SECONDARY INTELLIGENCE CHARTS
# ============================================================

def build_treasury_scenario_chart(height=300):
    if treasury_scenarios_df is None or treasury_scenarios_df.empty:
        return alt.Chart(pd.DataFrame({"scenario_name": [], "economic_value_impact_m": []})).mark_bar()

    chart_df = treasury_scenarios_df.copy()
    chart_df["economic_value_impact_m"] = pd.to_numeric(
        chart_df["economic_value_impact_m"], errors="coerce"
    )

    return (
        alt.Chart(chart_df)
        .mark_bar(cornerRadiusEnd=3, color="#B88CFF", opacity=0.82)
        .encode(
            x=alt.X(
                "economic_value_impact_m:Q",
                title="Economic value impact (€m)",
                axis=alt.Axis(
                    labelColor="#789EAC", titleColor="#789EAC",
                    gridColor="#12313E", gridOpacity=0.55, domain=False,
                ),
            ),
            y=alt.Y(
                "scenario_name:N", title=None, sort="x",
                axis=alt.Axis(labelColor="#B8D4DC", domain=False, ticks=False),
            ),
            tooltip=[
                alt.Tooltip("scenario_name:N", title="Scenario"),
                alt.Tooltip("economic_value_impact_m:Q", title="Economic value (€m)", format=",.0f"),
                alt.Tooltip("estimated_oci_impact_m:Q", title="OCI (€m)", format=",.0f"),
                alt.Tooltip("estimated_immediate_pnl_impact_m:Q", title="Immediate P&L (€m)", format=",.0f"),
            ],
        )
        .properties(height=height)
        .configure_view(stroke=None, fill="transparent")
    )


def build_peer_positioning_chart(height=390):
    if peer_plot_df is None or peer_plot_df.empty:
        return alt.Chart(pd.DataFrame({"reported_return_pct": [], "cet1_ratio_pct": []})).mark_circle()

    base = alt.Chart(peer_plot_df).encode(
        x=alt.X(
            "reported_return_pct:Q",
            title="Reported return / own ROE proxy (%)",
            axis=alt.Axis(labelColor="#789EAC", titleColor="#789EAC", gridColor="#12313E", domain=False),
        ),
        y=alt.Y(
            "cet1_ratio_pct:Q",
            title="CET1 ratio (%)",
            axis=alt.Axis(labelColor="#789EAC", titleColor="#789EAC", gridColor="#12313E", domain=False),
        ),
        size=alt.Size("total_assets_m:Q", legend=None, scale=alt.Scale(range=[120, 900])),
        color=alt.Color(
            "is_our_bank:N",
            scale=alt.Scale(domain=["Peer", "Our Bank"], range=["#52E7FF", "#B88CFF"]),
            legend=alt.Legend(title=None, labelColor="#9BBECA", orient="top"),
        ),
        tooltip=[
            alt.Tooltip("bank_name:N", title="Bank"),
            alt.Tooltip("reported_return_pct:Q", title="Return", format=".1f"),
            alt.Tooltip("return_metric_type:N", title="Return metric"),
            alt.Tooltip("cet1_ratio_pct:Q", title="CET1", format=".1f"),
            alt.Tooltip("cost_income_ratio_pct:Q", title="Cost / income", format=".1f"),
        ],
    )

    points = base.mark_circle(opacity=0.84, stroke="#DDFBFF", strokeWidth=0.5)
    labels = (
        alt.Chart(peer_plot_df[peer_plot_df["is_our_bank"] == "Our Bank"])
        .mark_text(dy=-18, font="Cascadia Mono", fontSize=11, color="#EAFDFF")
        .encode(x="reported_return_pct:Q", y="cet1_ratio_pct:Q", text="bank_name:N")
    )

    return (points + labels).properties(height=height).configure_view(stroke=None, fill="transparent")


def build_strategy_radar_chart(height=390):
    if strategic_radar_df is None or strategic_radar_df.empty:
        return alt.Chart(pd.DataFrame({"strategic_fit_score": [], "financial_attractiveness_score": []})).mark_circle()

    chart_df = strategic_radar_df.copy()
    base = alt.Chart(chart_df).encode(
        x=alt.X(
            "strategic_fit_score:Q", title="Strategic fit",
            scale=alt.Scale(domain=[50, 100]),
            axis=alt.Axis(labelColor="#789EAC", titleColor="#789EAC", gridColor="#12313E", domain=False),
        ),
        y=alt.Y(
            "financial_attractiveness_score:Q", title="Financial attractiveness",
            scale=alt.Scale(domain=[50, 100]),
            axis=alt.Axis(labelColor="#789EAC", titleColor="#789EAC", gridColor="#12313E", domain=False),
        ),
        size=alt.Size(
            "overall_opportunity_score:Q", legend=None, scale=alt.Scale(range=[160, 1050])
        ),
        color=alt.Color(
            "preferred_route:N",
            legend=alt.Legend(title="Route", labelColor="#9BBECA", titleColor="#9BBECA", orient="top"),
        ),
        tooltip=[
            alt.Tooltip("opportunity_rank:Q", title="Rank"),
            alt.Tooltip("company_name:N", title="Company"),
            alt.Tooltip("capability_domain:N", title="Capability"),
            alt.Tooltip("preferred_route:N", title="Preferred route"),
            alt.Tooltip("strategic_fit_score:Q", title="Strategic fit", format=".1f"),
            alt.Tooltip("financial_attractiveness_score:Q", title="Financial attractiveness", format=".1f"),
            alt.Tooltip("overall_opportunity_score:Q", title="Overall score", format=".1f"),
        ],
    )

    points = base.mark_circle(opacity=0.82, stroke="#DDFBFF", strokeWidth=0.6)
    labels = (
        alt.Chart(chart_df.head(5))
        .mark_text(dy=-17, font="Cascadia Mono", fontSize=10, color="#CDEFF5")
        .encode(x="strategic_fit_score:Q", y="financial_attractiveness_score:Q", text="company_name:N")
    )

    return (points + labels).properties(height=height).configure_view(stroke=None, fill="transparent")


def build_strategy_delta_chart(height=245):
    if strategy_delta_df is None or strategy_delta_df.empty:
        return alt.Chart(pd.DataFrame({"Component": [], "Weighted delta": []})).mark_bar()

    chart_df = strategy_delta_df.copy()
    chart_df["Leader"] = chart_df["Weighted delta"].apply(
        lambda value: str(top_strategy["company_name"]) if value >= 0 else str(second_strategy["company_name"])
    )

    bars = (
        alt.Chart(chart_df)
        .mark_bar(cornerRadius=3, opacity=0.86)
        .encode(
            x=alt.X(
                "Weighted delta:Q",
                title=f"Weighted score contribution: {top_strategy['company_name']} minus {second_strategy['company_name']}",
                axis=alt.Axis(
                    labelColor="#789EAC", titleColor="#789EAC",
                    gridColor="#12313E", domain=False
                ),
            ),
            y=alt.Y(
                "Component:N", title=None, sort="-x",
                axis=alt.Axis(labelColor="#B8D4DC", domain=False, ticks=False),
            ),
            color=alt.condition(
                alt.datum["Weighted delta"] >= 0,
                alt.value("#52E7FF"),
                alt.value("#B88CFF"),
            ),
            tooltip=[
                alt.Tooltip("Component:N", title="Component"),
                alt.Tooltip("Weighted delta:Q", title="Weighted score delta", format="+.2f"),
                alt.Tooltip("Leader:N", title="Advantage"),
            ],
        )
    )

    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(
        color="#3E6978", strokeDash=[3, 3]
    ).encode(x="x:Q")

    return (bars + zero).properties(height=height).configure_view(stroke=None, fill="transparent")


def build_capability_gap_chart(height=280):
    if capability_gaps_df is None or capability_gaps_df.empty:
        return alt.Chart(pd.DataFrame({"capability": [], "capability_gap": []})).mark_bar()

    return (
        alt.Chart(capability_gaps_df)
        .mark_bar(cornerRadiusEnd=3, color="#52E7FF", opacity=0.78)
        .encode(
            x=alt.X(
                "capability_gap:Q", title="Capability gap",
                axis=alt.Axis(labelColor="#789EAC", titleColor="#789EAC", gridColor="#12313E", domain=False),
            ),
            y=alt.Y(
                "capability:N", title=None, sort="-x",
                axis=alt.Axis(labelColor="#B8D4DC", domain=False, ticks=False),
            ),
            tooltip=[
                alt.Tooltip("capability:N", title="Capability"),
                alt.Tooltip("current_score:Q", title="Current", format=".0f"),
                alt.Tooltip("target_score:Q", title="Target", format=".0f"),
                alt.Tooltip("capability_gap:Q", title="Gap", format=".0f"),
                alt.Tooltip("priority:N", title="Priority"),
            ],
        )
        .properties(height=height)
        .configure_view(stroke=None, fill="transparent")
    )


# ============================================================
# CERTIFIED HORIZON CHART
# ============================================================


def build_horizon_outlook_chart(height=360):
    chart_df = horizon_baseline_df.copy()
    if chart_df.empty:
        return alt.Chart(pd.DataFrame({"month_label": [], "nim_pct": []})).mark_line()

    chart_df["nim_pct"] = pd.to_numeric(chart_df["nim_pct"], errors="coerce")
    chart_df = chart_df.dropna(subset=["nim_pct"]).sort_values("month").reset_index(drop=True)
    month_sort = chart_df["month_label"].tolist()

    y_min = float(chart_df["nim_pct"].min())
    y_max = float(chart_df["nim_pct"].max())
    spread = max(y_max - y_min, 0.05)
    padding = spread * 0.20

    actual = chart_df[chart_df["series"] == "Actual"].copy()
    baseline = chart_df[chart_df["series"] == "Baseline"].copy()

    # Add the last actual point to the baseline so the handover is continuous.
    if not actual.empty and not baseline.empty:
        bridge = actual.tail(1).copy()
        bridge["series"] = "Baseline"
        baseline = pd.concat([bridge, baseline], ignore_index=True)

    x_axis = alt.X(
        "month_label:O",
        sort=month_sort,
        title=None,
        axis=alt.Axis(
            labelAngle=0,
            grid=False,
            labelColor="#789EAC",
            labelFont="Cascadia Mono",
            labelFontSize=11,
            labelPadding=10,
            domainColor="#173B49",
            tickColor="#173B49",
        ),
    )
    y_axis = alt.Y(
        "nim_pct:Q",
        title="NIM (%)",
        scale=alt.Scale(domain=[y_min - padding, y_max + padding], zero=False, nice=False),
        axis=alt.Axis(
            format=".2f",
            tickCount=5,
            labelColor="#789EAC",
            labelFont="Cascadia Mono",
            labelFontSize=11,
            titleColor="#789EAC",
            titleFont="Cascadia Mono",
            titleFontSize=10,
            grid=True,
            gridColor="#12313E",
            gridOpacity=0.72,
            domain=False,
            ticks=False,
        ),
    )

    actual_line = alt.Chart(actual).mark_line(
        strokeWidth=3,
        color="#52E7FF",
    ).encode(
        x=x_axis,
        y=y_axis,
        tooltip=[
            alt.Tooltip("month:T", title="Month", format="%B %Y"),
            alt.Tooltip("nim_pct:Q", title="Actual NIM", format=".3f"),
        ],
    )
    actual_points = alt.Chart(actual).mark_circle(
        size=58,
        color="#52E7FF",
        stroke="#DDFBFF",
        strokeWidth=1.2,
    ).encode(x=x_axis, y=y_axis)

    forecast_line = alt.Chart(baseline).mark_line(
        strokeWidth=3,
        strokeDash=[7, 5],
        color="#B88CFF",
    ).encode(
        x=x_axis,
        y=y_axis,
        tooltip=[
            alt.Tooltip("month:T", title="Month", format="%B %Y"),
            alt.Tooltip("nim_pct:Q", title="Baseline NIM", format=".3f"),
        ],
    )
    forecast_points = alt.Chart(baseline.iloc[1:] if len(baseline) > 1 else baseline).mark_circle(
        size=56,
        fill="#031019",
        stroke="#C7A8FF",
        strokeWidth=2,
    ).encode(x=x_axis, y=y_axis)

    return (actual_line + actual_points + forecast_line + forecast_points).properties(
        height=height
    ).configure_view(stroke=None, fill="transparent")


def render_horizon_legend():
    render_html(
        """
        <div class="nim-legend">
            <div class="legend-item"><span class="legend-dot legend-actual"></span>Actual</div>
            <div class="legend-item"><span class="legend-line legend-forecast"></span>Deterministic baseline</div>
        </div>
        """
    )


# ============================================================
# HERO
# ============================================================

render_html(
    f"""
    <div class="hud-hero">
        <div class="hero-copy">
            <div class="system-kicker">AI CFO COMMAND CENTER</div>
            <h1 class="hero-title">MORNING <strong>COMMAND</strong></h1>
            <div class="hero-subtitle">
                What changed. Why it matters. What to investigate or act on next.
                The cockpit keeps the underlying systems invisible unless you need them.
            </div>
            <div class="hero-status-row">
                <span class="data-pill">Report date / {reporting_date}</span>
                <span class="data-pill">{executive_change_count} changes summarized</span>
            </div>
        </div>
        <div class="hero-core">
            <div class="arc-orb"><div class="orb-readout"><span class="orb-number">{executive_change_count:02d}</span><span class="orb-label">Changes</span></div></div>
        </div>
    </div>
    """
)


# ============================================================
# CFO POSITION — COMFORT FIRST, THEN SCALE / RISK
# ============================================================

render_html(
    f"""
    <div class="section-heading">
        <div>
            <div class="module-code">Position / current bank condition</div>
            <div class="section-title">Can the CFO be comfortable with the bank today?</div>
            <div class="section-subtitle">
                Capital, liquidity, earnings and asset quality first. Balance-sheet scale and risk
                sit directly underneath so the position is visible without turning the landing page
                into a regulatory report.
            </div>
        </div>
        <div class="sync-copy">As of {reporting_date}</div>
    </div>
    """
)

col1, col2, col3, col4 = st.columns(4)

with col1:
    render_html(
        f"""<div class="kpi-card position-capital" data-module="CAP / 01">
        <div class="kpi-label">CAPITAL RESILIENCE</div>
        <div class="kpi-value">{cet1_ratio:.1f}%</div>
        <div class="executive-delta position-status-good">CET1 · {arrow_delta(cet1_mom_pp)} vs {previous_month_label}</div>
        <div class="executive-context">Total capital {total_capital_ratio:.1f}% · €{cet1_capital / 1000:.1f}bn CET1 · RWA €{rwa / 1000:.1f}bn</div>
        <span class="micro-line"></span></div>"""
    )

with col2:
    render_html(
        f"""<div class="kpi-card position-liquidity" data-module="LIQ / 02">
        <div class="kpi-label">LIQUIDITY & FUNDING</div>
        <div class="kpi-value">{lcr_ratio:.1f}%</div>
        <div class="executive-delta position-status-neutral">LCR · {arrow_delta(lcr_mom_pp)} vs {previous_month_label}</div>
        <div class="executive-context">HQLA €{hqla / 1000:.1f}bn · L/D {loan_to_deposit_ratio:.1f}% · deposits €{current_deposits_m / 1000:.1f}bn</div>
        <span class="micro-line"></span></div>"""
    )

with col3:
    render_html(
        f"""<div class="kpi-card position-earnings" data-module="ERN / 03">
        <div class="kpi-label">EARNINGS CAPACITY</div>
        <div class="kpi-value">€{ytd_nii / 1000:.2f}bn</div>
        <div class="executive-delta" style="color:#C8AAFF;">YTD NII · ROE proxy {ytd_roe_proxy:.1f}%</div>
        <div class="executive-context">Net profit €{ytd_net_profit / 1000:.2f}bn · cost / income {ytd_cost_income:.1f}% · NIM {cert_current_nim:.2f}%</div>
        <span class="micro-line"></span></div>"""
    )

with col4:
    risk_delta_class = "position-status-watch" if stage2_mom_pp > 0 or stage3_mom_pp > 0 else "position-status-good"
    render_html(
        f"""<div class="kpi-card position-risk" data-module="CRD / 04">
        <div class="kpi-label">ASSET QUALITY</div>
        <div class="kpi-value">{current_stage2_pct:.1f}%</div>
        <div class="executive-delta {risk_delta_class}">Stage 2 · {stage2_mom_pp:+.2f}pp vs {previous_month_label}</div>
        <div class="executive-context">Stage 3 {current_stage3_pct:.1f}% ({stage3_mom_pp:+.2f}pp) · {current_credit_watch_count} current watch(es)</div>
        <span class="micro-line"></span></div>"""
    )

render_html(
    f"""
    <div class="balance-footprint">
        <div class="balance-footprint-item">
            <div class="balance-footprint-label">Total assets</div>
            <div class="balance-footprint-value">€{total_assets / 1000:.1f}bn</div>
            <div class="balance-footprint-context">Bank scale / balance-sheet footprint</div>
        </div>
        <div class="balance-footprint-item">
            <div class="balance-footprint-label">Risk-weighted assets</div>
            <div class="balance-footprint-value">€{rwa / 1000:.1f}bn</div>
            <div class="balance-footprint-context">RWA density {rwa_density_pct:.1f}% of total assets</div>
        </div>
        <div class="balance-footprint-item">
            <div class="balance-footprint-label">Loan exposure</div>
            <div class="balance-footprint-value">€{current_loans_m / 1000:.1f}bn</div>
            <div class="balance-footprint-context">Current certified loan book</div>
        </div>
        <div class="balance-footprint-item">
            <div class="balance-footprint-label">Deposits</div>
            <div class="balance-footprint-value">€{current_deposits_m / 1000:.1f}bn</div>
            <div class="balance-footprint-context">{total_deposit_30d_change_pct:+.2f}% / €{total_deposit_30d_change_m / 1000:+.2f}bn over 30D</div>
        </div>
    </div>
    """
)


# ============================================================
# NAVIGATION
# ============================================================

selected_module = get_selected_module()

module_metadata = {
    "home": (
        "CFO overview",
        "Current state, changes and next investigations",
    ),
    "brief": (
        "Module 01 / Morning Brief",
        "What changed, why it matters and what to investigate next",
    ),
    "horizon": (
        "Module 02 / Horizon",
        "Deterministic run-rate outlook from certified actuals",
    ),
    "scenario": (
        "Module 03 / What-If Engine",
        "Governed balance-sheet shock simulation",
    ),
    "treasury": (
        "Intelligence 05 / Treasury",
        "Portfolio sensitivity, scenario impacts and hedge alternatives",
    ),
    "peers": (
        "Intelligence 06 / Peers",
        "Directional European peer positioning and performance comparison",
    ),
    "strategy": (
        "Intelligence 07 / Strategy",
        "Strategic opportunity radar and capability-gap intelligence",
    ),
    "news": (
        "Intelligence 08 / External",
        "Public developments and the bank metrics they may affect",
    ),
    "copilot": (
        "Module 04 / CFO Copilot",
        "Conversational investigation over governed finance data",
    ),
}

active_module_name, active_module_description = module_metadata[
    selected_module
]

selection_class = (
    "has-selection"
    if selected_module != "home"
    else ""
)


def radial_active(module):
    return "is-active" if selected_module == module else ""


def radial_href(module):
    """Return a stable destination for radial navigation.

    Clicking the active vector keeps that module open. The dedicated Overview
    control is the only action that collapses the cockpit back to home.
    """

    return module


def radial_url(module):
    """Build the module URL and keep collapse focused on the dial."""

    destination = radial_href(module)
    anchor = (
        "radial-command"
        if destination == "home"
        else "module-output"
    )

    return f"?module={destination}#{anchor}"


render_html(
    f"""
    <div class="integrated-system {selection_class}" id="radial-command">
        <div class="system-topline"><span></span><span><strong>CFO decision cockpit</strong> / {reporting_date}</span><span></span></div>
        <div class="system-grid">
            <div class="cfo-change-panel">
                <div class="cfo-panel-kicker">Change / reference period</div><div class="cfo-panel-title">What moved?</div>
                <a class="change-row" href="{radial_url('brief')}" target="_self"><div class="change-row-head"><span class="change-name">Net interest margin</span><span class="change-value">{nim_mom_bps:+.1f} bps MoM</span></div><div class="change-detail">Current {cert_current_nim:.2f}% vs {safe_float(previous_cert_nim_row['nim_pct']):.2f}% in {previous_month_label} · {nim_signal_secondary}</div></a>
                <a class="change-row" href="{radial_url('brief')}" target="_self"><div class="change-row-head"><span class="change-name">Deposits</span><span class="change-value">{total_deposit_30d_change_pct:+.2f}% vs 30D</span></div><div class="change-detail">€{total_deposit_30d_change_m / 1000:+.2f}bn over 30 days · {deposit_signal_secondary}</div></a>
                <a class="change-row" href="{radial_url('brief')}" target="_self"><div class="change-row-head"><span class="change-name">Credit migration</span><span class="change-value">{('—' if credit_hotspot_stage2_delta_pp is None else f'{credit_hotspot_stage2_delta_pp:+.2f}pp vs 30D')}</span></div><div class="change-detail">{credit_signal_primary}</div></a>
            </div>

            <div class="dial-viewport">
                <div class="command-dial-html" role="navigation" aria-label="Interactive CFO command dial">
                    <span class="dial-grid-disc-html" aria-hidden="true"></span><span class="dial-crosshair-html" aria-hidden="true"></span><span class="dial-tick-shell-html" aria-hidden="true"></span><span class="dial-rotor-html rotor-outer" aria-hidden="true"></span><span class="dial-rotor-html rotor-inner" aria-hidden="true"></span><span class="dial-annulus-bed-html" aria-hidden="true"></span>
                    <a class="css-sector css-sector-brief {radial_active('brief')}" href="{radial_url('brief')}" target="_self" aria-label="Open Morning Brief" title="Morning Brief — click to open"><span class="dial-hit-copy">Morning Brief</span></a>
                    <a class="css-sector css-sector-horizon {radial_active('horizon')}" href="{radial_url('horizon')}" target="_self" aria-label="Open Horizon" title="Horizon — click to open"><span class="dial-hit-copy">Horizon</span></a>
                    <a class="css-sector css-sector-scenario {radial_active('scenario')}" href="{radial_url('scenario')}" target="_self" aria-label="Open What-If Engine" title="What-If Engine — click to open"><span class="dial-hit-copy">What-If Engine</span></a>
                    <span class="sector-label-html sector-label-brief {radial_active('brief')}"><strong class="sector-title-html">Morning Brief</strong><span class="sector-metric-html">NIM {cert_current_nim:.2f}% · {nim_mom_bps:+.1f} bps MoM</span><span class="sector-sub-html">Change · context · impact · next</span></span>
                    <span class="sector-label-html sector-label-horizon {radial_active('horizon')}"><strong class="sector-title-html">Horizon</strong><span class="sector-metric-html">Dec {horizon_year_end_nim:.2f}% · {horizon_change_bps:+.1f} bps vs Aug</span><span class="sector-sub-html">Actual → baseline → assumptions</span></span>
                    <span class="sector-label-html sector-label-scenario {radial_active('scenario')}"><strong class="sector-title-html">What-If Engine</strong><span class="sector-metric-html">−50bp preview · NIM {home_scenario_nim_impact_bps:+.1f} bps</span><span class="sector-sub-html">Stress · quantify · compare</span></span>
                    <span class="dial-vector-line-html dial-vector-a" aria-hidden="true"></span><span class="dial-vector-line-html dial-vector-b" aria-hidden="true"></span><span class="dial-vector-line-html dial-vector-c" aria-hidden="true"></span><span class="dial-spoke-html dial-spoke-a" aria-hidden="true"></span><span class="dial-spoke-html dial-spoke-b" aria-hidden="true"></span><span class="dial-spoke-html dial-spoke-c" aria-hidden="true"></span>
                    <a class="css-core {radial_active('copilot')}" href="{radial_url('copilot')}" target="_self" aria-label="Open CFO Copilot" title="Ask CFO Copilot — click to open"><span class="core-orbit-html" aria-hidden="true"></span><span class="core-reactor-html" aria-hidden="true"></span><span class="core-scan-html" aria-hidden="true"></span><span class="core-copy-html"><span class="core-code-html">AI / Investigate</span><strong class="core-main-html">Ask CFO<br>Copilot</strong><span class="core-online-html">Question → evidence</span><span class="core-hint-html">Select core to investigate</span></span></a>
                    <span class="dial-cardinal-html dial-cardinal-n" aria-hidden="true">N / 000</span><span class="dial-cardinal-html dial-cardinal-e" aria-hidden="true">E / 090</span><span class="dial-cardinal-html dial-cardinal-s" aria-hidden="true">S / 180</span><span class="dial-cardinal-html dial-cardinal-w" aria-hidden="true">W / 270</span>
                </div>
            </div>

            <div class="cfo-decision-panel">
                <div class="cfo-panel-kicker">Decision path</div><div class="cfo-panel-title">Current → outlook → stress</div>

                <div class="decision-lens-item">
                    <div class="decision-lens-title">01 / Current performance</div>
                    <div class="decision-lens-line"><span class="decision-lens-label">Actual</span><span class="decision-lens-copy">NIM {cert_current_nim:.2f}% · monthly NII €{cert_current_monthly_nii:,.0f}m.</span></div>
                    <div class="decision-lens-line"><span class="decision-lens-label">Change</span><span class="decision-lens-copy">{nim_mom_bps:+.1f} bps NIM vs {previous_month_label} · deposits {total_deposit_30d_change_pct:+.2f}% over 30D.</span></div>
                    <a class="copilot-action" href="?module=brief#module-output" target="_self">Open Morning Brief →</a>
                </div>

                <div class="decision-lens-item">
                    <div class="decision-lens-title">02 / Forward baseline</div>
                    <div class="decision-lens-line"><span class="decision-lens-label">December</span><span class="decision-lens-copy">NIM {horizon_year_end_nim:.2f}% · {horizon_change_bps:+.1f} bps vs August.</span></div>
                    <div class="decision-lens-line"><span class="decision-lens-label">FY NII</span><span class="decision-lens-copy">€{horizon_full_year_nii_m / 1000:.2f}bn mechanical run-rate; not an official management forecast.</span></div>
                    <a class="copilot-action" href="?module=horizon#module-output" target="_self">Open Horizon →</a>
                </div>

                <div class="decision-lens-item">
                    <div class="decision-lens-title">03 / Stress preview</div>
                    <div class="decision-lens-line"><span class="decision-lens-label">Assumption</span><span class="decision-lens-copy">ECB −50 bps · no deposit-volume shock · 365 days.</span></div>
                    <div class="decision-lens-line"><span class="decision-lens-label">Impact</span><span class="decision-lens-copy">NIM {home_scenario_nim_impact_bps:+.1f} bps · NII €{home_scenario_nii_impact_m:+,.0f}m over horizon.</span></div>
                    <a class="copilot-action" href="?module=scenario#module-output" target="_self">Open What-If Engine →</a>
                </div>
            </div>
        </div>
        <div class="system-bottom-rail"><span>Current view / {active_module_name}</span><a class="system-reset {'is-home' if selected_module == 'home' else ''}" href="?module=home#radial-command" target="_self">◎ Overview</a><span>Select a vector to investigate</span></div>
    </div>
    """
)


render_html(
    f"""
    <div class="intelligence-dock">
        <div class="dock-kicker">Context beyond the core financial engine</div>
        <div class="dock-actions">
            <a class="dock-action dock-strategy {radial_active('strategy')}" href="{radial_url('strategy')}" target="_self"><span class="dock-icon">◎</span><span class="dock-copy"><strong class="dock-title">Strategy</strong><span class="dock-metric">#1 {html.escape(str(top_strategy['company_name'])) if top_strategy is not None else '—'} · opportunity / capability lens</span></span></a>
            <a class="dock-action dock-peers {radial_active('peers')}" href="{radial_url('peers')}" target="_self"><span class="dock-icon">◌</span><span class="dock-copy"><strong class="dock-title">Peers</strong><span class="dock-metric">ROE proxy {roe_peer_gap_pp:+.1f}pp vs median · capital / efficiency context</span></span></a>
            <a class="dock-action dock-treasury {radial_active('treasury')}" href="{radial_url('treasury')}" target="_self"><span class="dock-icon">△</span><span class="dock-copy"><strong class="dock-title">Treasury</strong><span class="dock-metric">+50bp EVE {treasury_rate50_text} · DV01 / hedge trade-off</span></span></a>
            <a class="dock-action dock-news {radial_active('news')}" href="{radial_url('news')}" target="_self"><span class="dock-icon">◇</span><span class="dock-copy"><strong class="dock-title">External</strong><span class="dock-metric">{news_signal_primary}</span></span></a>
        </div>
    </div>
    """
)


if selected_module == "home":

    render_html(
        """
        <div class="system-overview-note" id="module-output">
            <span class="overview-title">CFO storyline</span>
            <span class="overview-copy">Position is shown first for comfort. Use the radial to move from actual performance to forward baseline to stress. Strategy, peers, Treasury and external intelligence remain one layer out so they add context without crowding the core decision path.</span>
        </div>
        """
    )

else:

    render_html(
        f"""
        <div class="active-module-banner" id="module-output">
            <span class="active-module-name">{active_module_name}</span>
            <span class="active-module-state">{active_module_description}</span>
        </div>
        """
    )


# ============================================================
# MORNING BRIEF — CHANGE → WHY → IMPACT → NEXT
# ============================================================

if selected_module == "brief":
    render_html("""<div class="module-code">Morning brief / executive view</div><div class="section-title">What changed — and what should I do with it?</div><div class="section-subtitle">Three movements worth reviewing this morning, each shown against its reference period with the financial implication and a direct path to investigate further.</div>""")

    render_html(f"""
    <div class="comparison-basis">
        <span class="comparison-chip"><strong>NIM</strong> vs {previous_month_label} / prior month</span>
        <span class="comparison-chip"><strong>Deposits</strong> vs 30 days prior</span>
        <span class="comparison-chip"><strong>Credit</strong> vs 30 days prior</span>
    </div>
    <div class="decision-flow-card"><div class="flow-title">01 / Net interest margin</div><div class="flow-grid"><div class="flow-cell"><span class="flow-label">Change vs prior month</span><span class="flow-copy">NIM {cert_current_nim:.2f}% · {nim_mom_bps:+.1f} bps vs {previous_month_label}</span></div><div class="flow-cell"><span class="flow-label">Why</span><span class="flow-copy">{nim_why}</span></div><div class="flow-cell"><span class="flow-label">Impact</span><span class="flow-copy">{nim_impact}</span></div><div class="flow-cell"><span class="flow-label">Next</span><span class="flow-copy">{nim_next}</span><a class="copilot-action" href="?module=copilot&investigate=nim#module-output" target="_self">Ask Copilot →</a></div></div></div>
    <div class="decision-flow-card"><div class="flow-title">02 / Deposits and funding</div><div class="flow-grid"><div class="flow-cell"><span class="flow-label">Change vs 30 days prior</span><span class="flow-copy">Deposits {total_deposit_30d_change_pct:+.2f}% · €{total_deposit_30d_change_m / 1000:+.2f}bn</span></div><div class="flow-cell"><span class="flow-label">Why</span><span class="flow-copy">{deposit_why}</span></div><div class="flow-cell"><span class="flow-label">Impact</span><span class="flow-copy">{deposit_impact}</span></div><div class="flow-cell"><span class="flow-label">Next</span><span class="flow-copy">{deposit_next}</span><a class="copilot-action" href="?module=copilot&investigate=deposits#module-output" target="_self">Ask Copilot →</a></div></div></div>
    <div class="decision-flow-card"><div class="flow-title">03 / Credit migration</div><div class="flow-grid"><div class="flow-cell"><span class="flow-label">Change vs 30 days prior</span><span class="flow-copy">{credit_signal_primary} · {('comparison unavailable' if credit_hotspot_stage2_delta_pp is None else f'{credit_hotspot_stage2_delta_pp:+.2f}pp')}</span></div><div class="flow-cell"><span class="flow-label">Why</span><span class="flow-copy">{credit_why}</span></div><div class="flow-cell"><span class="flow-label">Impact</span><span class="flow-copy">{credit_impact} · Stage 3 {safe_float(credit_hotspot['weighted_stage_3_share_pct']) if credit_hotspot is not None else 0:.1f}%</span></div><div class="flow-cell"><span class="flow-label">Next</span><span class="flow-copy">{credit_next}</span><a class="copilot-action" href="?module=copilot&investigate=credit#module-output" target="_self">Ask Copilot →</a></div></div></div>
    """)

    left, right = st.columns([1.4,1])
    with left:
        render_html("""<div class="module-code">Performance trend</div><div class="section-title">NIM trajectory</div>""")
        st.altair_chart(build_certified_nim_chart(height=290), use_container_width=True)
        render_html("""<div class="module-code" style="margin-top:.8rem;">Funding trend</div><div class="section-title">30-day deposit movement by country</div>""")
        st.altair_chart(build_deposit_country_chart(height=235), use_container_width=True)
    with right:
        render_html("""
        <div class="news-section-head">
            <div><div class="module-code">External news / public sources</div><div class="section-title">Latest developments</div></div>
            <div class="news-section-copy">Recent public news with a prepared view of why it may matter to the bank.</div>
        </div>
        """)
        if news_recent_df is not None and not news_recent_df.empty:
            for _, article in news_recent_df.head(3).iterrows():
                headline = html.escape(str(article["headline"]))
                source = html.escape(str(article["source"]))
                source_url = html.escape(str(article["source_url"]), quote=True)
                affected_metric = html.escape(str(article["primary_affected_metric"]))
                article_date = pd.to_datetime(article["published_date"]).strftime("%d %b")
                impact_summary = html.escape(clip_ui_text(article.get("bank_impact_summary", ""),112))
                next_action = html.escape(clip_ui_text(article.get("suggested_action", ""),96))
                category = html.escape(str(article.get("category", "External development")))
                render_html(f"""
                <div class="news-card">
                    <div class="news-topline"><span class="news-badge">News</span><span class="news-meta">{source} · {article_date} · {category}</span></div>
                    <div class="news-headline">{headline}</div>
                    <div class="news-context-grid">
                        <div class="news-context-line"><span class="news-context-label">Why it matters</span><span class="news-context-copy">{impact_summary}</span></div>
                        <div class="news-context-line"><span class="news-context-label">Potential metric</span><span class="news-context-copy">{affected_metric}</span></div>
                        <div class="news-context-line"><span class="news-context-label">Next</span><span class="news-context-copy">{next_action}</span></div>
                    </div>
                    <div class="news-footer"><a class="news-source-link" href="{source_url}" target="_blank" rel="noopener noreferrer">Open article ↗</a><span class="news-public-note">Public source · bank impact is prototype analysis</span></div>
                </div>
                """)
        else:
            st.caption("No recent public-news records available.")
        if st.button("Investigate the morning brief with CFO Copilot →", key="brief_to_copilot", use_container_width=True):
            st.session_state["brief_copilot_prompt"] = "Based on the latest certified CFO morning brief, explain what changed in NIM, deposits and credit, why the observed data may matter, quantify the financial impact available in the certified views, and recommend the next investigation. Separate facts from interpretation and do not invent causality."
            navigate_to_module("copilot")


# ============================================================
# HORIZON
# ============================================================

if selected_module == "horizon":

    horizon_direction = (
        "higher" if horizon_change_bps > 0
        else "lower" if horizon_change_bps < 0
        else "flat"
    )
    repricing_direction = (
        "supports margin" if spread_30d_bps > 0
        else "pressures margin" if spread_30d_bps < 0
        else "is neutral for margin"
    )

    render_html(
        f"""
        <div class="module-code">Module 02 / Forward view</div>
        <div class="section-title">Where are we heading?</div>
        <div class="section-subtitle">
            A transparent momentum-decay baseline projects the current certified
            operating run-rate through December. It is a mechanical reference
            point for decisions — not the bank's official plan or forecast.
        </div>
        """
    )

    h1, h2, h3, h4 = st.columns(4)

    with h1:
        render_html(
            f"""<div class="kpi-card" data-module="OUT / 02">
            <div class="kpi-label">DECEMBER NIM BASELINE</div>
            <div class="kpi-value">{horizon_year_end_nim:.2f}%</div>
            <div class="executive-delta">{arrow_delta(horizon_change_bps, ' bps')} vs Aug</div>
            <div class="executive-context">Mechanical run-rate, not official plan</div>
            <span class="micro-line"></span></div>"""
        )

    with h2:
        render_html(
            f"""<div class="kpi-card" data-module="NII / 02">
            <div class="kpi-label">FY NII BASELINE</div>
            <div class="kpi-value">€{horizon_full_year_nii_m / 1000:.2f}bn</div>
            <div class="executive-delta">€{horizon_remaining_nii_m / 1000:.2f}bn Sep-Dec</div>
            <div class="executive-context">Actual YTD + forward run-rate</div>
            <span class="micro-line"></span></div>"""
        )

    with h3:
        render_html(
            f"""<div class="kpi-card" data-module="MOM / 02">
            <div class="kpi-label">SEP NIM STEP</div>
            <div class="kpi-value">{horizon_first_month_bps:+.1f}</div>
            <div class="executive-delta">bps vs Aug</div>
            <div class="executive-context">First month of decaying repricing momentum</div>
            <span class="micro-line"></span></div>"""
        )

    with h4:
        render_html(
            f"""<div class="kpi-card" data-module="BAL / 02">
            <div class="kpi-label">BALANCE-SHEET RUN-RATE</div>
            <div class="kpi-value">{horizon_asset_growth_pct:+.2f}%</div>
            <div class="executive-delta">earning assets / month</div>
            <div class="executive-context">Deposits {horizon_deposit_growth_pct:+.2f}% monthly run-rate</div>
            <span class="micro-line"></span></div>"""
        )

    st.write("")
    chart_col, lens_col = st.columns([1.72, 0.9])

    with chart_col:
        render_html(
            """<div class="module-code">Forward trajectory / actual → baseline</div>
            <div class="section-title">NIM outlook</div>"""
        )
        render_horizon_legend()
        st.altair_chart(
            build_horizon_outlook_chart(height=355),
            use_container_width=True,
        )
        st.caption(
            "Baseline assumptions: earning assets follow the median of the latest 3 monthly moves; "
            "deposits use the latest 30-day growth rate; 50% of the latest 30-day repricing is carried "
            "into September and that repricing momentum halves each month thereafter."
        )

    with lens_col:
        render_html(
            f"""
            <div class="forward-lens-panel">
                <div class="forward-lens-kicker">Forward lens</div>
                <div class="forward-lens-title">What is the baseline telling us?</div>

                <div class="forward-lens-row">
                    <span class="forward-lens-label">Repricing</span>
                    <span class="forward-lens-value">
                        Loan yield moved <strong>{loan_rate_30d_bps:+.1f} bps</strong> and
                        deposit cost <strong>{deposit_rate_30d_bps:+.1f} bps</strong> over 30D.
                        The net pricing spread move of <strong>{spread_30d_bps:+.1f} bps</strong>
                        currently {repricing_direction}.
                    </span>
                </div>

                <div class="forward-lens-row">
                    <span class="forward-lens-label">Funding</span>
                    <span class="forward-lens-value">
                        Deposits are running at <strong>{horizon_deposit_growth_pct:+.2f}%</strong>
                        per month in the baseline, anchored to the latest 30D move.
                    </span>
                </div>

                <div class="forward-lens-row">
                    <span class="forward-lens-label">Outcome</span>
                    <span class="forward-lens-value">
                        If those observed trends continue but repricing momentum fades,
                        December NIM lands at <strong>{horizon_year_end_nim:.2f}%</strong> —
                        <strong>{abs(horizon_change_bps):.1f} bps {horizon_direction}</strong>
                        than August.
                    </span>
                </div>

                <div class="forward-lens-row">
                    <span class="forward-lens-label">Plan gap</span>
                    <span class="forward-lens-value">
                        The official budget/planning comparator is not yet in the refreshed
                        certified layer, so this view should not be read as "ahead/behind plan".
                    </span>
                </div>

                <div class="forward-lens-meaning">
                    <strong>How to use it</strong>
                    Treat this as the no-new-action reference case. The useful question is not
                    whether {horizon_year_end_nim:.2f}% is "the forecast", but which assumption
                    would move it most — rates, deposit pricing, funding volume or asset growth.
                </div>
            </div>
            """
        )

    render_html(
        """
        <div class="module-action-row">
            <a class="module-action-link" href="?module=scenario&source=horizon#module-output" target="_self">
                Stress key assumptions →
            </a>
            <a class="module-action-link" href="?module=copilot&investigate=horizon#module-output" target="_self">
                Ask Copilot about the outlook →
            </a>
        </div>
        """
    )


# ============================================================
# WHAT-IF ENGINE
# ============================================================

if selected_module == "scenario":

    render_html(
        """
        <div class="module-code">Module 03 / Decision stress</div>
        <div class="section-title">What-If Engine</div>
        <div class="section-subtitle">
            Change the assumptions and quantify the effect on the refreshed
            certified NII/NIM baseline. The financial output is deterministic;
            Copilot can explain the result, but does not calculate it.
        </div>
        """
    )

    controls, results = st.columns([0.86, 1.55])

    with controls:
        render_html("""<div class="module-code">Scenario assumptions</div>""")

        with st.form("scenario_form"):
            selected_ecb_shock = st.slider(
                "ECB rate shock",
                min_value=-100,
                max_value=100,
                value=-50,
                step=5,
                format="%d bps",
            )

            selected_deposit_shock = st.slider(
                "Deposit balance shock",
                min_value=-10.0,
                max_value=5.0,
                value=0.0,
                step=0.5,
                format="%.1f%%",
            )

            selected_horizon = st.slider(
                "Scenario horizon",
                min_value=30,
                max_value=365,
                value=365,
                step=5,
                format="%d days",
            )

            with st.expander(
                "Advanced repricing assumptions",
                expanded=False,
            ):
                selected_loan_beta = st.slider(
                    "Loan pass-through to ECB shock",
                    min_value=0,
                    max_value=100,
                    value=35,
                    step=5,
                    format="%d%%",
                )
                selected_deposit_beta = st.slider(
                    "Deposit pass-through to ECB shock",
                    min_value=0,
                    max_value=100,
                    value=55,
                    step=5,
                    format="%d%%",
                )
                selected_replacement_rate = st.number_input(
                    "Replacement funding rate (%)",
                    min_value=0.0,
                    max_value=10.0,
                    value=3.25,
                    step=0.05,
                    format="%.2f",
                )

            run_button = st.form_submit_button(
                "Run scenario",
                use_container_width=True,
            )

        render_html(
            f"""
            <div class="forward-lens-panel" style="margin-top:.85rem;">
                <div class="forward-lens-kicker">Current certified anchor</div>
                <div class="forward-lens-row"><span class="forward-lens-label">NIM</span><span class="forward-lens-value"><strong>{cert_current_nim:.2f}%</strong></span></div>
                <div class="forward-lens-row"><span class="forward-lens-label">Loan rate</span><span class="forward-lens-value"><strong>{current_loan_rate_pct:.2f}%</strong></span></div>
                <div class="forward-lens-row"><span class="forward-lens-label">Deposit rate</span><span class="forward-lens-value"><strong>{current_deposit_rate_pct:.2f}%</strong></span></div>
                <div class="forward-lens-row"><span class="forward-lens-label">Deposits</span><span class="forward-lens-value"><strong>€{current_deposits_m / 1000:.1f}bn</strong></span></div>
            </div>
            """
        )

    if "certified_scenario_inputs" not in st.session_state:
        st.session_state["certified_scenario_inputs"] = {
            "ecb": -50,
            "deposit": 0.0,
            "horizon": 365,
            "loan_beta": 35,
            "deposit_beta": 55,
            "replacement_rate": 3.25,
        }

    if run_button:
        st.session_state["certified_scenario_inputs"] = {
            "ecb": selected_ecb_shock,
            "deposit": selected_deposit_shock,
            "horizon": selected_horizon,
            "loan_beta": selected_loan_beta,
            "deposit_beta": selected_deposit_beta,
            "replacement_rate": selected_replacement_rate,
        }

    inputs = st.session_state["certified_scenario_inputs"]

    scenario = calculate_certified_scenario(
        ecb_shock_bps=inputs["ecb"],
        deposit_balance_shock_pct=inputs["deposit"],
        horizon_days=inputs["horizon"],
        loan_beta_pct=inputs["loan_beta"],
        deposit_beta_pct=inputs["deposit_beta"],
        replacement_funding_rate_pct=inputs["replacement_rate"],
    )

    with results:
        render_html(
            """<div class="module-code">Scenario result</div>
            <div class="section-title">What changes?</div>"""
        )

        c1, c2, c3 = st.columns(3)

        with c1:
            nim_class = (
                "kpi-alert"
                if scenario["nim_impact_bps"] < 0
                else "kpi-track"
            )
            render_html(
                f"""<div class="kpi-card" data-module="SIM / NIM">
                <div class="kpi-label">NIM IMPACT</div>
                <div class="kpi-value">{scenario['nim_impact_bps']:+.1f} bps</div>
                <div class="{nim_class}">{scenario['current_nim_pct']:.2f}% → {scenario['scenario_nim_pct']:.2f}%</div>
                <span class="micro-line"></span></div>"""
            )

        with c2:
            nii_class = (
                "kpi-alert"
                if scenario["horizon_nii_impact_m"] < 0
                else "kpi-track"
            )
            render_html(
                f"""<div class="kpi-card" data-module="SIM / NII">
                <div class="kpi-label">NII IMPACT / HORIZON</div>
                <div class="kpi-value">€{scenario['horizon_nii_impact_m']:+,.0f}m</div>
                <div class="{nii_class}">{inputs['horizon']} day impact</div>
                <span class="micro-line"></span></div>"""
            )

        with c3:
            funding_m = scenario["lost_deposits_m"]
            funding_text = (
                f"€{funding_m / 1000:.2f}bn"
                if funding_m > 0
                else "€0.00bn"
            )
            render_html(
                f"""<div class="kpi-card" data-module="SIM / FUND">
                <div class="kpi-label">REPLACEMENT FUNDING</div>
                <div class="kpi-value">{funding_text}</div>
                <div class="executive-delta">{inputs['deposit']:+.1f}% deposit shock</div>
                <span class="micro-line"></span></div>"""
            )

        render_html(
            f"""
            <div class="scenario-impact-grid">
                <div class="scenario-impact-cell">
                    <div class="scenario-impact-label">Loan repricing</div>
                    <div class="scenario-impact-value">€{scenario['loan_repricing_impact_m']:+,.0f}m / yr</div>
                    <div class="scenario-impact-copy">{scenario['current_loan_rate_pct']:.2f}% → {scenario['scenario_loan_rate_pct']:.2f}%</div>
                </div>

                <div class="scenario-impact-cell">
                    <div class="scenario-impact-label">Funding-cost change</div>
                    <div class="scenario-impact-value">€{scenario['funding_cost_change_m']:+,.0f}m / yr</div>
                    <div class="scenario-impact-copy">Deposit rate {scenario['current_deposit_rate_pct']:.2f}% → {scenario['scenario_deposit_rate_pct']:.2f}%</div>
                </div>

                <div class="scenario-impact-cell">
                    <div class="scenario-impact-label">Annualised NII</div>
                    <div class="scenario-impact-value">€{scenario['scenario_annual_nii_m'] / 1000:.2f}bn</div>
                    <div class="scenario-impact-copy">vs €{scenario['current_annual_nii_m'] / 1000:.2f}bn certified-anchor run-rate</div>
                </div>
            </div>
            """
        )

        if scenario["nim_impact_bps"] < 0:
            decision_copy = (
                "The selected assumptions compress margin. Review funding "
                "pass-through and deposit-volume sensitivity before accepting "
                "the outcome."
            )
        elif scenario["nim_impact_bps"] > 0:
            decision_copy = (
                "The selected assumptions expand margin. Check whether the "
                "assumed loan/deposit pass-through is realistic before treating "
                "the upside as actionable."
            )
        else:
            decision_copy = (
                "The selected assumptions leave margin broadly unchanged. "
                "The result is most sensitive to the repricing betas and any "
                "deposit outflow."
            )

        if inputs["ecb"] > 0:
            next_copy = (
                "Compare the bank-margin benefit with the Treasury +50bp "
                "economic-value loss before making a rate-risk decision."
            )
        elif inputs["ecb"] < 0:
            next_copy = (
                "Review how quickly asset yields reprice relative to deposit "
                "costs and whether funding growth offsets the margin pressure."
            )
        else:
            next_copy = (
                "Focus on the deposit-volume shock and replacement-funding "
                "assumption."
            )

        render_html(
            f"""
            <div class="scenario-decision-card">
                <div class="scenario-decision-line"><span>Change</span><span>ECB {inputs['ecb']:+.0f} bps · deposits {inputs['deposit']:+.1f}% · {inputs['horizon']} days.</span></div>
                <div class="scenario-decision-line"><span>Impact</span><span>NIM {scenario['nim_impact_bps']:+.1f} bps and NII €{scenario['horizon_nii_impact_m']:+,.0f}m over the selected horizon.</span></div>
                <div class="scenario-decision-line"><span>Meaning</span><span>{decision_copy}</span></div>
                <div class="scenario-decision-line"><span>Next</span><span>{next_copy}</span></div>
            </div>
            """
        )

        render_html(
            """
            <div class="module-action-row">
                <a class="module-action-link" href="?module=copilot&investigate=scenario#module-output" target="_self">
                    Ask Copilot to interpret →
                </a>
                <a class="module-action-link" href="?module=treasury#module-output" target="_self">
                    Compare with Treasury →
                </a>
            </div>
            """
        )

        st.caption(
            "Prototype deterministic scenario: current certified NIM/balances/rates are the anchor. "
            "Loan and deposit pass-through, replacement funding and deposit shock are explicit assumptions. "
            "The next production step is to move this calculation upstream into the governed certified scenario layer."
        )


# ============================================================
# TREASURY INTELLIGENCE
# ============================================================

if selected_module == "treasury":
    render_html(
        """
        <div class="module-code">Intelligence 05 / Treasury and hedge intelligence</div>
        <div class="section-title">Treasury Pulse</div>
        <div class="section-subtitle">
            Certified portfolio sensitivity, predefined market-risk scenarios and
            deterministic hedge alternatives. Economic value, OCI and immediate P&L
            remain explicitly separated.
        </div>
        """
    )

    strongest_hedge_name = html.escape(str(strongest_hedge["hedge_name"])) if strongest_hedge is not None else "No predefined hedge available"
    strongest_hedge_reduction = safe_float(strongest_hedge["dv01_reduction_pct"]) if strongest_hedge is not None else 0.0
    strongest_hedge_carry = safe_float(strongest_hedge["estimated_annual_carry_m"]) if strongest_hedge is not None else 0.0
    treasury_change_copy = f"Market value {treasury_market_trend_text} ({treasury_market_trend_label})" if treasury_market_change_m is not None else "No prior treasury snapshot is available, so day-over-day market-value change cannot yet be measured."
    render_html(f"""<div class="decision-strip"><div class="decision-strip-item"><span class="flow-label">Change</span><strong>{treasury_change_copy}</strong><span>Trend appears automatically once a prior snapshot exists.</span></div><div class="decision-strip-item"><span class="flow-label">Why</span><strong>Duration {treasury_duration:.2f}y · DV01 €{treasury_dv01:.1f}m/bp</strong><span>These certified sensitivity measures explain why parallel rate moves affect economic value.</span></div><div class="decision-strip-item"><span class="flow-label">Impact</span><strong>+50bp → {treasury_rate50_text}</strong><span>Certified economic-value impact; OCI and immediate P&amp;L remain separately reported below.</span></div><div class="decision-strip-item"><span class="flow-label">Next option</span><strong>{strongest_hedge_name}</strong><span>Largest predefined DV01 reduction: {strongest_hedge_reduction:.0f}% · carry €{strongest_hedge_carry:+,.0f}m/year. Prototype option, not a trading recommendation.</span></div></div>""")

    t1, t2, t3, t4 = st.columns(4)
    with t1:
        render_html(f"""<div class="kpi-card" data-module="MKT / 05"><div class="kpi-label">MARKET VALUE</div><div class="kpi-value">€{treasury_market_value_m / 1000:.1f}bn</div><div class="{treasury_market_trend_css}">{treasury_market_trend_label}: {treasury_market_trend_text}</div><span class="micro-line"></span></div>""")
    with t2:
        render_html(f"""<div class="kpi-card" data-module="RISK / 05"><div class="kpi-label">PORTFOLIO DV01</div><div class="kpi-value">€{treasury_dv01:.1f}m</div><div class="kpi-neutral">per 1 bp parallel rate move</div><span class="micro-line"></span></div>""")
    with t3:
        render_html(f"""<div class="kpi-card" data-module="DUR / 05"><div class="kpi-label">MODIFIED DURATION</div><div class="kpi-value">{treasury_duration:.2f}y</div><div class="kpi-neutral">market-value weighted</div><span class="micro-line"></span></div>""")
    with t4:
        impact_css = "kpi-alert" if treasury_rate50_impact_m < 0 else "kpi-track"
        render_html(f"""<div class="kpi-card" data-module="SIM / 05"><div class="kpi-label">RATES +50BP</div><div class="kpi-value">{treasury_rate50_text}</div><div class="{impact_css}">certified economic-value impact</div><span class="micro-line"></span></div>""")

    tleft, tright = st.columns([1.25, 1])
    with tleft:
        render_html("""<div class="module-code">Scenario lattice / Certified outputs</div><div class="section-title">Market-risk scenarios</div>""")
        st.altair_chart(build_treasury_scenario_chart(height=330), use_container_width=True)
        st.caption("Scenario outputs are taken directly from cfo_treasury_scenarios; the UI does not reprice the portfolio.")
    with tright:
        render_html("""<div class="module-code">Hedge lattice / Predefined alternatives</div><div class="section-title">Hedge options</div>""")
        if hedge_options_df is not None and not hedge_options_df.empty:
            best_hedge = hedge_options_df.iloc[0]
            render_html(f"""<div class="feature-callout"><div class="feature-callout-title">Largest DV01 reduction / {html.escape(str(best_hedge['hedge_name']))}</div><div class="feature-callout-copy">Indicative notional €{safe_float(best_hedge['hedge_notional_m']) / 1000:.1f}bn · DV01 reduction {safe_float(best_hedge['dv01_reduction_pct']):.0f}% · annual carry €{safe_float(best_hedge['estimated_annual_carry_m']):+,.0f}m. Prototype estimate, not an executable trading recommendation.</div></div>""")
            hedge_display = hedge_options_df[["hedge_name", "hedge_notional_m", "dv01_reduction_pct", "rates_plus_50bp_pnl_after_m", "estimated_annual_carry_m"]].copy()
            hedge_display.columns = ["Hedge", "Notional (€m)", "DV01 reduction (%)", "+50bp impact after hedge (€m)", "Annual carry (€m)"]
            st.dataframe(hedge_display, use_container_width=True, hide_index=True)
        else:
            st.caption("No certified hedge alternatives available.")

    if treasury_market_change_m is None:
        st.info("The current treasury dataset contains no prior market-value snapshot, so a genuine day-over-day move cannot be shown yet. The cockpit is wired to display the change automatically when a previous snapshot is added.")


# ============================================================
# PEER INTELLIGENCE
# ============================================================

if selected_module == "peers":
    render_html("""<div class="module-code">Intelligence 06 / European peer positioning</div><div class="section-title">Peer Benchmarking</div><div class="section-subtitle">Directional comparison with public FY2025 peer disclosures. Peer profitability mixes ROE, RoTE and Net RoTE; the fictional bank is shown using its annualised YTD ROE proxy, so return comparisons are not fully like-for-like.</div>""")
    p1, p2, p3 = st.columns(3)
    with p1:
        render_html(f"""<div class="kpi-card" data-module="RET / 06"><div class="kpi-label">OUR ROE PROXY</div><div class="kpi-value">{ytd_roe_proxy:.1f}%</div><div class="kpi-neutral">peer median {peer_profitability_median:.1f}%</div><span class="micro-line"></span></div>""")
    with p2:
        render_html(f"""<div class="kpi-card" data-module="CAP / 06"><div class="kpi-label">OUR CET1</div><div class="kpi-value">{cet1_ratio:.1f}%</div><div class="kpi-neutral">peer median {peer_cet1_median:.1f}%</div><span class="micro-line"></span></div>""")
    with p3:
        render_html(f"""<div class="kpi-card" data-module="EFF / 06"><div class="kpi-label">OUR COST / INCOME</div><div class="kpi-value">{ytd_cost_income:.1f}%</div><div class="kpi-neutral">peer median {peer_cost_income_median:.1f}%</div><span class="micro-line"></span></div>""")

    return_gap_word = "below" if roe_peer_gap_pp < 0 else "above"
    efficiency_word = "better" if efficiency_peer_advantage_pp > 0 else "worse" if efficiency_peer_advantage_pp < 0 else "in line"
    render_html(f"""<div class="decision-strip"><div class="decision-strip-item"><span class="flow-label">Gap</span><strong>ROE proxy {abs(roe_peer_gap_pp):.1f}pp {return_gap_word} median</strong><span>Directional only because peers mix ROE, RoTE and Net RoTE.</span></div><div class="decision-strip-item"><span class="flow-label">Why</span><strong>CET1 {cet1_peer_gap_pp:+.1f}pp vs median</strong><span>Capital position and reported return should be read together, not as a one-dimensional ranking.</span></div><div class="decision-strip-item"><span class="flow-label">Impact</span><strong>Cost/income {abs(efficiency_peer_advantage_pp):.1f}pp {efficiency_word} than median</strong><span>Shows whether the return gap is accompanied by an efficiency gap.</span></div><div class="decision-strip-item"><span class="flow-label">Next</span><strong>Investigate return levers</strong><span>Separate revenue/NII, fee income, cost and capital-deployment drivers before drawing conclusions.</span></div></div>""")

    pleft, pright = st.columns([1.45, 1])
    with pleft:
        render_html("""<div class="module-code">Position matrix / Return × capital</div><div class="section-title">Where do we sit?</div>""")
        st.altair_chart(build_peer_positioning_chart(height=400), use_container_width=True)
    with pright:
        render_html("""<div class="module-code">Peer ledger / Public disclosures</div><div class="section-title">Comparison set</div>""")
        if peer_benchmark_df is not None and not peer_benchmark_df.empty:
            peer_display = peer_benchmark_df[["bank_name", "reported_return_pct", "return_metric_type", "cet1_ratio_pct", "cost_income_ratio_pct"]].copy()
            peer_display.columns = ["Bank", "Return (%)", "Metric", "CET1 (%)", "Cost / income (%)"]
            st.dataframe(peer_display, use_container_width=True, hide_index=True, height=410)


# ============================================================
# STRATEGIC RADAR
# ============================================================

if selected_module == "strategy":
    render_html("""<div class="module-code">Intelligence 07 / Strategic opportunity radar</div><div class="section-title">Strategy Radar</div><div class="section-subtitle">Public company facts are separated from synthetic management assessments. Strategic fit, attractiveness and capability scores are prototype decision-support inputs — not claims that a company is for sale or a transaction recommendation.</div>""")

    if top_strategy is not None:
        s1, s2, s3 = st.columns(3)
        with s1:
            render_html(f"""<div class="kpi-card" data-module="TOP / 07"><div class="kpi-label">TOP OPPORTUNITY</div><div class="kpi-value" style="font-size:1.75rem;">{html.escape(str(top_strategy['company_name']))}</div><div class="kpi-neutral">rank #{int(top_strategy['opportunity_rank'])} · {safe_float(top_strategy['overall_opportunity_score']):.1f}/100</div><span class="micro-line"></span></div>""")
        with s2:
            render_html(f"""<div class="kpi-card" data-module="FIT / 07"><div class="kpi-label">STRATEGIC FIT</div><div class="kpi-value">{safe_float(top_strategy['strategic_fit_score']):.0f}</div><div class="kpi-neutral">synthetic management score</div><span class="micro-line"></span></div>""")
        with s3:
            gap_name = html.escape(str(top_capability_gap['capability'])) if top_capability_gap is not None else "—"
            gap_value = safe_float(top_capability_gap['capability_gap']) if top_capability_gap is not None else 0.0
            render_html(f"""<div class="kpi-card" data-module="GAP / 07"><div class="kpi-label">LARGEST CAPABILITY GAP</div><div class="kpi-value" style="font-size:1.55rem;">{gap_name}</div><div class="kpi-neutral">gap {gap_value:.0f} points</div><span class="micro-line"></span></div>""")

    if top_strategy is not None and second_strategy is not None:
        advantage_html = "".join(
            f'<span class="strategy-delta-pill">{html.escape(item)}</span>'
            for item in strategy_advantage_pills
        )
        render_html(
            f"""
            <div class="strategy-explainer">
                <div class="strategy-explainer-grid">
                    <div>
                        <div class="module-code">Why rank #1?</div>
                        <div class="strategy-score-bridge">
                            {html.escape(str(top_strategy['company_name']))} <span>{safe_float(top_strategy['overall_opportunity_score']):.1f}</span>
                            vs {html.escape(str(second_strategy['company_name']))} {safe_float(second_strategy['overall_opportunity_score']):.1f}
                        </div>
                    </div>
                    <div class="strategy-explainer-copy">
                        The opportunity map below shows only <strong>strategic fit</strong> and
                        <strong>financial attractiveness</strong>, which together represent 45% of the
                        composite score. The rank uses seven weighted dimensions.
                        {html.escape(str(top_strategy['company_name']))} gives up some points on the two
                        map axes, but gains more through integration feasibility, affordability and time to value.
                        <div class="strategy-delta-strip">{advantage_html}</div>
                    </div>
                </div>
            </div>
            """
        )

    if top_strategy is not None:
        render_html(f"""<div class="decision-strip"><div class="decision-strip-item"><span class="flow-label">Why #1</span><strong>{html.escape(str(top_strategy['company_name']))} / {safe_float(top_strategy['overall_opportunity_score']):.1f}</strong><span>Full seven-factor composite, not just the two map axes.</span></div><div class="decision-strip-item"><span class="flow-label">Impact</span><strong>{html.escape(clip_ui_text(top_strategy['strategic_gap_addressed'],72))}</strong><span>{html.escape(clip_ui_text(top_strategy['strategic_rationale'],110))}</span></div><div class="decision-strip-item"><span class="flow-label">Route</span><strong>{html.escape(str(top_strategy['preferred_route']))}</strong><span>Prototype management route, not a statement that the company is for sale.</span></div><div class="decision-strip-item"><span class="flow-label">Key risk</span><strong>{html.escape(clip_ui_text(top_strategy['key_risk'],78))}</strong><span>Use this risk alongside affordability, integration and regulatory complexity.</span></div></div>""")

    sleft, sright = st.columns([1.35, 1])
    with sleft:
        render_html("""<div class="module-code">Opportunity matrix / 2 of 7 scoring dimensions</div><div class="section-title">Strategic opportunity map</div><div class="section-subtitle">X/Y show fit and financial attractiveness. Bubble size represents the full seven-factor composite score used for ranking.</div>""")
        st.altair_chart(build_strategy_radar_chart(height=410), use_container_width=True)
    with sright:
        render_html("""<div class="module-code">Composite bridge / #1 vs #2</div><div class="section-title">What drives the ranking?</div>""")
        if not strategy_delta_df.empty:
            st.altair_chart(build_strategy_delta_chart(height=250), use_container_width=True)
        render_html("""<div class="module-code" style="margin-top:0.8rem;">Capability vector / Current-to-target gap</div><div class="section-title">Capability gaps</div>""")
        st.altair_chart(build_capability_gap_chart(height=245), use_container_width=True)

    if strategic_radar_df is not None and not strategic_radar_df.empty:
        strategy_display = strategic_radar_df[[
            "opportunity_rank", "company_name", "capability_domain",
            "strategic_fit_score", "financial_attractiveness_score",
            "integration_feasibility_score", "affordability_score",
            "time_to_value_score", "overall_opportunity_score"
        ]].head(7).copy()
        strategy_display.columns = [
            "Rank", "Company", "Capability", "Strategic fit",
            "Financial attractiveness", "Integration", "Affordability",
            "Time to value", "Overall score"
        ]
        st.dataframe(strategy_display, use_container_width=True, hide_index=True)



# ============================================================
# EXTERNAL INTELLIGENCE
# ============================================================

if selected_module == "news":
    render_html(
        """
        <div class="module-code">Intelligence 08 / External developments</div>
        <div class="section-title">External Intelligence</div>
        <div class="section-subtitle">
            Public developments are kept separate from internal financial facts.
            The prepared bank-impact fields are prototype interpretation, not proof of causality.
        </div>
        """
    )

    n1, n2, n3 = st.columns(3)
    with n1:
        render_html(
            f"""<div class="kpi-card" data-module="NEWS / 08">
            <div class="kpi-label">HIGH-IMPACT ITEMS</div>
            <div class="kpi-value">{high_impact_news_count}</div>
            <div class="kpi-neutral">recent configured news window</div>
            <span class="micro-line"></span></div>"""
        )
    with n2:
        geo_name = html.escape(str(geo_focus["country"])) if geo_focus is not None else "—"
        geo_score = safe_float(geo_focus["geo_attention_score"]) if geo_focus is not None else 0.0
        render_html(
            f"""<div class="kpi-card" data-module="GEO / 08">
            <div class="kpi-label">GEO ATTENTION</div>
            <div class="kpi-value" style="font-size:1.7rem;">{geo_name}</div>
            <div class="kpi-neutral">attention score {geo_score:.1f}</div>
            <span class="micro-line"></span></div>"""
        )
    with n3:
        affected = html.escape(str(top_news["primary_affected_metric"])) if top_news is not None else "—"
        render_html(
            f"""<div class="kpi-card" data-module="MET / 08">
            <div class="kpi-label">TOP AFFECTED METRIC</div>
            <div class="kpi-value" style="font-size:1.55rem;">{affected}</div>
            <div class="kpi-neutral">potential impact only</div>
            <span class="micro-line"></span></div>"""
        )

    if news_recent_df is not None and not news_recent_df.empty:
        render_html(
            """<div class="module-code" style="margin-top:1rem;">Public-source feed</div>
            <div class="section-title">What may matter now?</div>"""
        )
        for _, article in news_recent_df.head(6).iterrows():
            headline = html.escape(str(article["headline"]))
            source = html.escape(str(article["source"]))
            source_url = html.escape(str(article["source_url"]), quote=True)
            affected_metric = html.escape(str(article["primary_affected_metric"]))
            article_date = pd.to_datetime(article["published_date"]).strftime("%d %b")
            impact_summary = html.escape(clip_ui_text(article.get("bank_impact_summary", ""), 150))
            next_action = html.escape(clip_ui_text(article.get("suggested_action", ""), 125))
            category = html.escape(str(article.get("category", "External development")))
            render_html(
                f"""
                <div class="news-card">
                    <div class="news-topline"><span class="news-badge">News</span><span class="news-meta">{source} · {article_date} · {category}</span></div>
                    <div class="news-headline">{headline}</div>
                    <div class="news-context-grid">
                        <div class="news-context-line"><span class="news-context-label">Why it may matter</span><span class="news-context-copy">{impact_summary}</span></div>
                        <div class="news-context-line"><span class="news-context-label">Potential metric</span><span class="news-context-copy">{affected_metric}</span></div>
                        <div class="news-context-line"><span class="news-context-label">Next investigation</span><span class="news-context-copy">{next_action}</span></div>
                    </div>
                    <div class="news-footer"><a class="news-source-link" href="{source_url}" target="_blank" rel="noopener noreferrer">Open article ↗</a><span class="news-public-note">Public source · bank impact is prototype analysis</span></div>
                </div>
                """
            )

        if st.button(
            "Ask CFO Copilot to connect external developments to the bank →",
            key="news_to_copilot",
            use_container_width=True,
        ):
            st.session_state["brief_copilot_prompt"] = COPILOT_INVESTIGATION_PROMPTS.get(
                "news",
                "Review the latest external developments and connect them to the bank's certified financial position without inventing causality.",
            )
            navigate_to_module("copilot")
    else:
        st.info("No recent public-source records are available in the configured window.")



# One-click investigation links from the cockpit / morning brief.
# The query parameter is consumed once per visit so Genie does not rerun the
# same question repeatedly after its own Streamlit rerun.
investigate_topic = get_query_value("investigate", "").lower().strip()
if selected_module != "copilot":
    st.session_state.pop("_last_investigation_topic", None)

COPILOT_INVESTIGATION_PROMPTS = {
    "nim": (
        "Investigate the latest NIM movement. Quantify the change versus the prior month, "
        "show the available loan-yield and deposit-cost movements, identify country or business-line "
        "drivers supported by the certified views, quantify the NII impact, and separate observed facts "
        "from interpretation."
    ),
    "deposits": (
        "Investigate the latest 30-day deposit movement. Quantify the bank-level change in EUR and percent, "
        "identify the countries and business lines driving the movement, and explain what the CFO should review "
        "before changing deposit pricing. Use certified views only."
    ),
    "credit": (
        "Investigate the current credit-migration signal. Focus on the country and business line with the highest "
        "Stage 2 concentration, quantify the 30-day change and Stage 3 position, and identify what can and cannot be "
        "concluded about the underlying cause from the certified data."
    ),
    "news": (
        "Review the latest public news developments in the certified news-intelligence view. Lead with the actual "
        "headlines and sources, explain the potentially affected bank metrics, and suggest the next investigation. "
        "Do not present news as proven causality for internal financial movements."
    ),
    "horizon": (
        "Explain the Horizon run-rate baseline using the certified actuals. Distinguish clearly between the mechanical "
        "momentum-decay baseline and an official forecast or budget. Identify which observed repricing, funding and "
        "balance-sheet assumptions matter most, and suggest what the CFO should stress next."
    ),
    "scenario": (
        "Interpret the latest What-If scenario shown in the cockpit. Explain the NIM and NII impact, the role of loan "
        "and deposit pass-through assumptions, any replacement-funding effect, and what the CFO should compare next. "
        "Do not recalculate or replace the deterministic scenario output."
    ),
}

if selected_module == "copilot" and investigate_topic in COPILOT_INVESTIGATION_PROMPTS:
    if st.session_state.get("_last_investigation_topic") != investigate_topic:
        st.session_state["brief_copilot_prompt"] = COPILOT_INVESTIGATION_PROMPTS[investigate_topic]
        st.session_state["_last_investigation_topic"] = investigate_topic


# ============================================================
# CFO COPILOT
# ============================================================

if selected_module == "copilot":

    render_html(
        """
        <div class="module-code">Module 04 / Decision intelligence</div>
        <div class="section-title">
            CFO AI Decision Partner
        </div>
        <div class="section-subtitle">
            Challenge the numbers, connect signals across the cockpit and turn evidence into a decision path.
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
                        Ask what changed, why it matters, what the trade-offs are and what should happen next.
                        The assistant investigates governed finance data; deterministic scenario outputs remain in What-If.
                    </div>
                </div>
            </div>
            <div class="copilot-context-strip">
                <div class="copilot-context-item"><span>As of</span><strong>{reporting_date}</strong></div>
                <div class="copilot-context-item"><span>NIM</span><strong>{cert_current_nim:.2f}%</strong></div>
                <div class="copilot-context-item"><span>CET1</span><strong>{cet1_ratio:.1f}%</strong></div>
                <div class="copilot-context-item"><span>LCR</span><strong>{lcr_ratio:.1f}%</strong></div>
            </div>
        </div>
        """
    )

    # --------------------------------------------------------
    # SESSION STATE
    # --------------------------------------------------------

    if "cfo_copilot_messages" not in st.session_state:
        st.session_state.cfo_copilot_messages = []

    if "cfo_copilot_suggestions" not in st.session_state:
        st.session_state.cfo_copilot_suggestions = []

    if "cfo_genie_conversation_id" not in st.session_state:
        st.session_state.cfo_genie_conversation_id = None

    # --------------------------------------------------------
    # COMMAND BAR / RESET
    # --------------------------------------------------------

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
        if st.button(
            "Clear context",
            key="reset_cfo_copilot",
            use_container_width=True,
        ):
            st.session_state.cfo_copilot_messages = []
            st.session_state.cfo_copilot_suggestions = []
            st.session_state.cfo_genie_conversation_id = None
            st.rerun()

    # --------------------------------------------------------
    # HIGH-VALUE CFO COMMANDS
    # --------------------------------------------------------

    suggested_prompt = st.session_state.pop(
        "brief_copilot_prompt",
        None,
    )

    c1, c2, c3, c4 = st.columns(4)

    with c1:
        if st.button(
            "Brief me on what changed",
            key="copilot_suggestion_brief",
            use_container_width=True,
        ):
            suggested_prompt = (
                "Give me the CFO morning decision brief. Rank the most material observed changes, explain why each may matter, "
                "quantify the impact where certified data supports it, and tell me what to investigate or decide next."
            )

    with c2:
        if st.button(
            "Challenge the outlook",
            key="copilot_suggestion_horizon",
            use_container_width=True,
        ):
            suggested_prompt = COPILOT_INVESTIGATION_PROMPTS["horizon"]

    with c3:
        if st.button(
            "Where are we behind peers?",
            key="copilot_suggestion_peers",
            use_container_width=True,
        ):
            suggested_prompt = (
                "Compare our latest certified position with the European peer set. Identify the most decision-relevant gaps in return, "
                "capital and efficiency, distinguish unlike-for-like return metrics, and recommend the first management question to pursue."
            )

    with c4:
        if st.button(
            "What is our treasury trade-off?",
            key="copilot_suggestion_treasury",
            use_container_width=True,
        ):
            suggested_prompt = (
                "Summarize the treasury portfolio trade-off for the CFO: current DV01 and duration, the certified +50bp economic-value and OCI impact, "
                "and which predefined hedge alternative changes the exposure most. Separate economic value, OCI and immediate P&L."
            )

    # --------------------------------------------------------
    # CONVERSATION THREAD
    # --------------------------------------------------------

    if not st.session_state.cfo_copilot_messages:
        render_html(
            """
            <div class="panel" style="margin-top:0.85rem;">
                <div class="readout-label">Start with a decision, not a search</div>
                <div style="margin-top:0.45rem; color:#789fac; font-size:0.82rem; line-height:1.5;">
                    Ask the assistant to challenge an assumption, compare alternatives, connect a market development to the bank's exposures,
                    or tell you what evidence would change a decision.
                </div>
            </div>
            """
        )

    else:
        render_html('<div class="copilot-thread-label" style="margin-top:1rem;">Decision thread</div>')

        for message_index, message in enumerate(
            st.session_state.cfo_copilot_messages
        ):
            role = message.get("role", "assistant")
            avatar = ":material/person:" if role == "user" else ":material/monitoring:"

            with st.chat_message(role, avatar=avatar):
                if role == "user":
                    render_html('<div class="copilot-user-label">CFO / question</div>')
                else:
                    render_html('<div class="copilot-answer-label">CFO AI / decision brief</div>')

                st.markdown(message.get("content", ""))

                queries = message.get("queries", [])

                if role == "assistant" and queries:
                    with st.expander(
                        "Evidence trail / governed SQL",
                        expanded=False,
                    ):
                        for query_index, query_info in enumerate(queries):
                            title = query_info.get("title", "Evidence query")
                            description = query_info.get("description", "")
                            st.markdown(f"**{title}**")
                            if description:
                                st.caption(description)
                            st.code(query_info.get("sql", ""), language="sql")
                            if query_index < len(queries) - 1:
                                st.divider()

    # --------------------------------------------------------
    # NEXT INVESTIGATIONS
    # --------------------------------------------------------

    active_followups = st.session_state.cfo_copilot_suggestions[:3]
    if not active_followups and st.session_state.cfo_copilot_messages:
        active_followups = [
            "What evidence would change this conclusion?",
            "What is the main downside or trade-off?",
            "What should I monitor next?",
        ]

    if active_followups:
        render_html('<div class="module-code" style="margin-top:0.8rem;">Next investigations</div>')
        follow_up_cols = st.columns(len(active_followups))
        for index, suggestion in enumerate(active_followups):
            with follow_up_cols[index]:
                if st.button(
                    suggestion,
                    key=f"copilot_followup_{index}",
                    use_container_width=True,
                ):
                    suggested_prompt = suggestion

    # --------------------------------------------------------
    # QUESTION INPUT
    # --------------------------------------------------------

    question = st.chat_input(
        "Ask a CFO question — challenge the evidence, compare options or decide what to do next..."
    )

    question_to_run = None
    if suggested_prompt:
        question_to_run = suggested_prompt
    elif question and question.strip():
        question_to_run = question.strip()

    # --------------------------------------------------------
    # CALL GENIE
    # --------------------------------------------------------

    if question_to_run:
        request_for_genie = build_copilot_request(question_to_run)

        st.session_state.cfo_copilot_messages.append(
            {
                "role": "user",
                "content": question_to_run,
            }
        )

        try:
            with st.spinner("Analyzing governed evidence and decision implications..."):
                (
                    answer,
                    generated_queries,
                    genie_suggestions,
                ) = ask_cfo_genie(request_for_genie)

            st.session_state.cfo_copilot_messages.append(
                {
                    "role": "assistant",
                    "content": answer,
                    "queries": generated_queries,
                }
            )
            st.session_state.cfo_copilot_suggestions = genie_suggestions[:3]

        except Exception as e:
            st.session_state.cfo_copilot_messages.append(
                {
                    "role": "assistant",
                    "content": (
                        "**Decision view**\n\nThe governed-data investigation could not complete. "
                        "No financial conclusion has been generated from incomplete evidence.\n\n"
                        f"Technical detail: `{e}`"
                    ),
                    "queries": [],
                }
            )

        st.rerun()

    # --------------------------------------------------------
    # CROSS-MODULE DECISION ACTIONS
    # --------------------------------------------------------

    render_html(
        """
        <div class="copilot-module-dock">
            <a class="copilot-module-link" href="?module=brief#module-output" target="_self">Morning Brief</a>
            <a class="copilot-module-link" href="?module=horizon#module-output" target="_self">Horizon</a>
            <a class="copilot-module-link" href="?module=scenario#module-output" target="_self">What-If</a>
            <a class="copilot-module-link" href="?module=treasury#module-output" target="_self">Treasury</a>
        </div>
        <div class="copilot-evidence-note">
            Financial conclusions are grounded in certified CFO views. Scenario calculations remain deterministic in What-If.
            Technical lineage is available in the evidence trail and diagnostics only when needed.
        </div>
        """
    )


# ============================================================
# CONNECTION STATUS
# ============================================================

with st.expander(
    "System diagnostics / Databricks connection",
    expanded=False,
):
    render_html(
        """
        <div class="diagnostic-grid">
            <div class="diagnostic-item">
                <span class="status-dot"></span>
                <div>
                    <div class="readout-label">Current state</div>
                    <div class="diagnostic-value">cfo_current_position</div>
                </div>
            </div>
            <div class="diagnostic-item">
                <span class="status-dot"></span>
                <div>
                    <div class="readout-label">NIM actuals</div>
                    <div class="diagnostic-value">cfo_monthly_nim</div>
                </div>
            </div>
            <div class="diagnostic-item">
                <span class="status-dot"></span>
                <div>
                    <div class="readout-label">Signal layer</div>
                    <div class="diagnostic-value">deposit + credit certified views</div>
                </div>
            </div>
            <div class="diagnostic-item">
                <span class="status-dot"></span>
                <div>
                    <div class="readout-label">External intel</div>
                    <div class="diagnostic-value">cfo_news_intelligence</div>
                </div>
            </div>
        </div>
        """
    )
    st.caption(
        "Horizon and What-If are now anchored to the refreshed certified cfo_* state. "
        "Their deterministic calculations still run in the app for the prototype; "
        "the production step is to persist them upstream as governed certified views/functions."
    )


# ============================================================
# SYSTEM FOOTER
# ============================================================

render_html(
    f"""
    <div class="system-footer">
        <span>A.R.C. / CFO decision intelligence</span>
        <span>Reporting state / {reporting_date}</span>
        <span>Financial outputs / Governed</span>
    </div>
    """
)
