from __future__ import annotations

"""
Build the certified / curated CFO layer on top of the raw Delta tables.

Source schema:
    <catalog>.<schema>

Design principle:
    Raw data -> deterministic finance logic -> certified CFO views -> Genie/App.

No LLM calculations are used here. Ratios are recalculated from underlying
amounts where aggregation is required. Balance-sheet stocks are never summed
across dates.
"""

import argparse
import os
from pyspark.sql import SparkSession

DEFAULT_CATALOG = os.getenv("CFO_DATA_CATALOG", "frbg3as_studio_a")
DEFAULT_SCHEMA = os.getenv("CFO_DATA_SCHEMA", "cfo_cockpit")


def build_certified_views(
    catalog: str = DEFAULT_CATALOG,
    schema: str = DEFAULT_SCHEMA,
) -> None:
    spark = SparkSession.builder.getOrCreate()
    q = f"{catalog}.{schema}"

    print("=" * 78)
    print("CFO MORNING COCKPIT — BUILD CERTIFIED VIEWS")
    print("=" * 78)
    print(f"Target schema: {q}")
    print()

    statements = {}

    statements["cfo_financial_history"] = f"""
    CREATE OR REPLACE VIEW {q}.cfo_financial_history AS
    SELECT
        CAST(date AS DATE) AS date,
        CAST(loans AS DOUBLE) AS loans_m,
        CAST(deposits AS DOUBLE) AS deposits_m,
        CAST(deposit_movement AS DOUBLE) AS deposit_movement_m,
        CAST(loan_growth_mom_pct AS DOUBLE) AS loan_growth_mom_pct,

        CAST(gca AS DOUBLE) AS gross_carrying_amount_m,
        CAST(ead AS DOUBLE) AS ead_m,
        CAST(provisions AS DOUBLE) AS provisions_m,

        CAST(stage_1_share_pct AS DOUBLE) AS stage_1_share_pct,
        CAST(stage_2_share_pct AS DOUBLE) AS stage_2_share_pct,
        CAST(stage_3_share_pct AS DOUBLE) AS stage_3_share_pct,

        CAST(rwa AS DOUBLE) AS rwa_m,
        CAST(cet1_capital AS DOUBLE) AS cet1_capital_m,
        CAST(at1_capital AS DOUBLE) AS at1_capital_m,
        CAST(tier2_capital AS DOUBLE) AS tier2_capital_m,

        CAST(hqla AS DOUBLE) AS hqla_m,
        CAST(net_cash_outflows AS DOUBLE) AS net_cash_outflows_m,

        CAST(ecb_rate_pct AS DOUBLE) AS ecb_rate_pct,
        CAST(avg_loan_yield_pct AS DOUBLE) AS avg_loan_yield_pct,
        CAST(avg_deposit_cost_pct AS DOUBLE) AS avg_deposit_cost_pct,

        CAST(nii AS DOUBLE) AS nii_m,
        CAST(fee_income AS DOUBLE) AS fee_income_m,
        CAST(other_income AS DOUBLE) AS other_income_m,
        CAST(operating_income AS DOUBLE) AS operating_income_m,
        CAST(operating_costs AS DOUBLE) AS operating_costs_m,
        CAST(provision_charge AS DOUBLE) AS provision_charge_m,

        CAST(pre_tax_profit AS DOUBLE) AS pre_tax_profit_m,
        CAST(tax_expense AS DOUBLE) AS tax_expense_m,
        CAST(net_profit AS DOUBLE) AS net_profit_m,
        CAST(dividends AS DOUBLE) AS dividends_m,
        CAST(retained_earnings AS DOUBLE) AS retained_earnings_m,

        CAST(cost_income_ratio_pct AS DOUBLE) AS cost_income_ratio_pct,
        CAST(cet1_ratio_pct AS DOUBLE) AS cet1_ratio_pct,
        CAST(lcr_pct AS DOUBLE) AS lcr_pct,
        CAST(loan_to_deposit_pct AS DOUBLE) AS loan_to_deposit_pct,

        CASE
            WHEN CAST(rwa AS DOUBLE) <> 0
            THEN (
                CAST(cet1_capital AS DOUBLE)
                + CAST(at1_capital AS DOUBLE)
                + CAST(tier2_capital AS DOUBLE)
            ) / CAST(rwa AS DOUBLE) * 100
        END AS total_capital_ratio_pct,

        CAST(total_assets AS DOUBLE) AS total_assets_m,
        CAST(total_liabilities AS DOUBLE) AS total_liabilities_m

    FROM {q}.raw_bank_history
    """

    statements["cfo_current_position"] = f"""
    CREATE OR REPLACE VIEW {q}.cfo_current_position AS
    WITH latest AS (
        SELECT MAX(CAST(date AS DATE)) AS latest_date
        FROM {q}.raw_bank_history
    ),
    current_row AS (
        SELECT h.*
        FROM {q}.raw_bank_history h
        CROSS JOIN latest l
        WHERE CAST(h.date AS DATE) = l.latest_date
    ),
    ytd AS (
        SELECT
            YEAR(l.latest_date) AS reporting_year,
            COUNT(DISTINCT MONTH(CAST(h.date AS DATE))) AS months_observed,
            SUM(CAST(h.nii AS DOUBLE)) AS ytd_nii_m,
            SUM(CAST(h.fee_income AS DOUBLE)) AS ytd_fee_income_m,
            SUM(CAST(h.operating_income AS DOUBLE)) AS ytd_operating_income_m,
            SUM(CAST(h.operating_costs AS DOUBLE)) AS ytd_operating_costs_m,
            SUM(CAST(h.provision_charge AS DOUBLE)) AS ytd_provision_charge_m,
            SUM(CAST(h.pre_tax_profit AS DOUBLE)) AS ytd_pre_tax_profit_m,
            SUM(CAST(h.net_profit AS DOUBLE)) AS ytd_net_profit_m,
            AVG(CAST(h.cet1_capital AS DOUBLE)) AS avg_ytd_cet1_capital_m
        FROM {q}.raw_bank_history h
        CROSS JOIN latest l
        WHERE YEAR(CAST(h.date AS DATE)) = YEAR(l.latest_date)
        GROUP BY YEAR(l.latest_date)
    )
    SELECT
        CAST(c.date AS DATE) AS as_of_date,
        CAST(c.loans AS DOUBLE) AS loans_m,
        CAST(c.deposits AS DOUBLE) AS deposits_m,
        CAST(c.total_assets AS DOUBLE) AS total_assets_m,
        CAST(c.total_liabilities AS DOUBLE) AS total_liabilities_m,

        CAST(c.rwa AS DOUBLE) AS rwa_m,
        CAST(c.cet1_capital AS DOUBLE) AS cet1_capital_m,
        CAST(c.at1_capital AS DOUBLE) AS at1_capital_m,
        CAST(c.tier2_capital AS DOUBLE) AS tier2_capital_m,
        CAST(c.cet1_ratio_pct AS DOUBLE) AS cet1_ratio_pct,

        CASE
            WHEN CAST(c.rwa AS DOUBLE) <> 0
            THEN (
                CAST(c.cet1_capital AS DOUBLE)
                + CAST(c.at1_capital AS DOUBLE)
                + CAST(c.tier2_capital AS DOUBLE)
            ) / CAST(c.rwa AS DOUBLE) * 100
        END AS total_capital_ratio_pct,

        CAST(c.hqla AS DOUBLE) AS hqla_m,
        CAST(c.net_cash_outflows AS DOUBLE) AS net_cash_outflows_m,
        CAST(c.lcr_pct AS DOUBLE) AS lcr_pct,
        CAST(c.loan_to_deposit_pct AS DOUBLE) AS loan_to_deposit_pct,

        CAST(c.stage_1_share_pct AS DOUBLE) AS stage_1_share_pct,
        CAST(c.stage_2_share_pct AS DOUBLE) AS stage_2_share_pct,
        CAST(c.stage_3_share_pct AS DOUBLE) AS stage_3_share_pct,

        CAST(c.ecb_rate_pct AS DOUBLE) AS ecb_rate_pct,
        CAST(c.avg_loan_yield_pct AS DOUBLE) AS avg_loan_yield_pct,
        CAST(c.avg_deposit_cost_pct AS DOUBLE) AS avg_deposit_cost_pct,

        y.reporting_year,
        y.months_observed,
        y.ytd_nii_m,
        y.ytd_fee_income_m,
        y.ytd_operating_income_m,
        y.ytd_operating_costs_m,
        y.ytd_provision_charge_m,
        y.ytd_pre_tax_profit_m,
        y.ytd_net_profit_m,

        CASE
            WHEN y.ytd_operating_income_m <> 0
            THEN y.ytd_operating_costs_m / y.ytd_operating_income_m * 100
        END AS ytd_cost_income_ratio_pct,

        CASE
            WHEN y.avg_ytd_cet1_capital_m <> 0
                 AND y.months_observed > 0
            THEN (
                y.ytd_net_profit_m * (12.0 / y.months_observed)
            ) / y.avg_ytd_cet1_capital_m * 100
        END AS annualised_ytd_roe_proxy_pct

    FROM current_row c
    CROSS JOIN ytd y
    """

    statements["cfo_daily_bank"] = f"""
    CREATE OR REPLACE VIEW {q}.cfo_daily_bank AS
    SELECT
        CAST(date AS DATE) AS date,
        SUM(CAST(loan_balance_m AS DOUBLE)) AS interest_earning_assets_m,
        SUM(CAST(deposit_balance_m AS DOUBLE)) AS deposit_balance_m,
        SUM(CAST(daily_interest_income_m AS DOUBLE)) AS daily_interest_income_m,
        SUM(CAST(daily_interest_expense_m AS DOUBLE)) AS daily_interest_expense_m,
        SUM(CAST(daily_nii_m AS DOUBLE)) AS daily_nii_m,

        CASE
            WHEN SUM(CAST(loan_balance_m AS DOUBLE)) <> 0
            THEN SUM(
                CAST(interest_rate_pct AS DOUBLE)
                * CAST(loan_balance_m AS DOUBLE)
            ) / SUM(CAST(loan_balance_m AS DOUBLE))
        END AS weighted_loan_rate_pct,

        CASE
            WHEN SUM(CAST(deposit_balance_m AS DOUBLE)) <> 0
            THEN SUM(
                CAST(interest_rate_pct AS DOUBLE)
                * CAST(deposit_balance_m AS DOUBLE)
            ) / SUM(CAST(deposit_balance_m AS DOUBLE))
        END AS weighted_deposit_rate_pct,

        CASE
            WHEN SUM(CAST(loan_balance_m AS DOUBLE)) <> 0
            THEN (
                SUM(CAST(daily_nii_m AS DOUBLE)) * 365.0
                / SUM(CAST(loan_balance_m AS DOUBLE))
            ) * 100
        END AS annualised_daily_nim_pct,

        MAX(CAST(ecb_rate_pct AS DOUBLE)) AS ecb_rate_pct,
        SUM(CAST(rwa_m AS DOUBLE)) AS rwa_m,
        MAX(CASE WHEN CAST(anomaly_flag AS INT) = 1 THEN 1 ELSE 0 END) AS has_anomaly

    FROM {q}.raw_bank_daily_signals
    GROUP BY CAST(date AS DATE)
    """

    statements["cfo_daily_country"] = f"""
    CREATE OR REPLACE VIEW {q}.cfo_daily_country AS
    SELECT
        CAST(date AS DATE) AS date,
        country,
        SUM(CAST(loan_balance_m AS DOUBLE)) AS interest_earning_assets_m,
        SUM(CAST(deposit_balance_m AS DOUBLE)) AS deposit_balance_m,
        SUM(CAST(daily_interest_income_m AS DOUBLE)) AS daily_interest_income_m,
        SUM(CAST(daily_interest_expense_m AS DOUBLE)) AS daily_interest_expense_m,
        SUM(CAST(daily_nii_m AS DOUBLE)) AS daily_nii_m,

        CASE
            WHEN SUM(CAST(loan_balance_m AS DOUBLE)) <> 0
            THEN SUM(
                CAST(interest_rate_pct AS DOUBLE)
                * CAST(loan_balance_m AS DOUBLE)
            ) / SUM(CAST(loan_balance_m AS DOUBLE))
        END AS weighted_loan_rate_pct,

        CASE
            WHEN SUM(CAST(deposit_balance_m AS DOUBLE)) <> 0
            THEN SUM(
                CAST(interest_rate_pct AS DOUBLE)
                * CAST(deposit_balance_m AS DOUBLE)
            ) / SUM(CAST(deposit_balance_m AS DOUBLE))
        END AS weighted_deposit_rate_pct,

        CASE
            WHEN SUM(CAST(loan_balance_m AS DOUBLE)) <> 0
            THEN (
                SUM(CAST(daily_nii_m AS DOUBLE)) * 365.0
                / SUM(CAST(loan_balance_m AS DOUBLE))
            ) * 100
        END AS annualised_daily_nim_pct,

        SUM(CAST(rwa_m AS DOUBLE)) AS rwa_m,

        CASE
            WHEN SUM(CAST(loan_balance_m AS DOUBLE)) <> 0
            THEN SUM(
                CAST(stage_2_share_pct AS DOUBLE)
                * CAST(loan_balance_m AS DOUBLE)
            ) / SUM(CAST(loan_balance_m AS DOUBLE))
        END AS weighted_stage_2_share_pct,

        CASE
            WHEN SUM(CAST(loan_balance_m AS DOUBLE)) <> 0
            THEN SUM(
                CAST(stage_3_share_pct AS DOUBLE)
                * CAST(loan_balance_m AS DOUBLE)
            ) / SUM(CAST(loan_balance_m AS DOUBLE))
        END AS weighted_stage_3_share_pct,

        MAX(CASE WHEN CAST(anomaly_flag AS INT) = 1 THEN 1 ELSE 0 END) AS has_anomaly

    FROM {q}.raw_bank_daily_signals
    GROUP BY CAST(date AS DATE), country
    """

    statements["cfo_daily_business_country"] = f"""
    CREATE OR REPLACE VIEW {q}.cfo_daily_business_country AS
    SELECT
        CAST(date AS DATE) AS date,
        country,
        business_line,
        SUM(CAST(loan_balance_m AS DOUBLE)) AS interest_earning_assets_m,
        SUM(CAST(deposit_balance_m AS DOUBLE)) AS deposit_balance_m,
        SUM(CAST(daily_nii_m AS DOUBLE)) AS daily_nii_m,
        SUM(CAST(rwa_m AS DOUBLE)) AS rwa_m,

        CASE
            WHEN SUM(CAST(loan_balance_m AS DOUBLE)) <> 0
            THEN SUM(
                CAST(stage_2_share_pct AS DOUBLE)
                * CAST(loan_balance_m AS DOUBLE)
            ) / SUM(CAST(loan_balance_m AS DOUBLE))
        END AS weighted_stage_2_share_pct,

        CASE
            WHEN SUM(CAST(loan_balance_m AS DOUBLE)) <> 0
            THEN SUM(
                CAST(stage_3_share_pct AS DOUBLE)
                * CAST(loan_balance_m AS DOUBLE)
            ) / SUM(CAST(loan_balance_m AS DOUBLE))
        END AS weighted_stage_3_share_pct,

        MAX(CASE WHEN CAST(anomaly_flag AS INT) = 1 THEN 1 ELSE 0 END) AS has_anomaly

    FROM {q}.raw_bank_daily_signals
    GROUP BY CAST(date AS DATE), country, business_line
    """

    statements["cfo_monthly_nim"] = f"""
    CREATE OR REPLACE VIEW {q}.cfo_monthly_nim AS
    WITH monthly AS (
        SELECT
            DATE_TRUNC('month', date) AS month,
            SUM(daily_nii_m) AS monthly_nii_m,
            AVG(interest_earning_assets_m) AS avg_interest_earning_assets_m,
            COUNT(DISTINCT date) AS days_observed
        FROM {q}.cfo_daily_bank
        GROUP BY DATE_TRUNC('month', date)
    )
    SELECT
        CAST(month AS DATE) AS month,
        monthly_nii_m,
        avg_interest_earning_assets_m,
        days_observed,

        CASE
            WHEN avg_interest_earning_assets_m <> 0
                 AND days_observed > 0
            THEN (
                monthly_nii_m
                * (365.0 / days_observed)
                / avg_interest_earning_assets_m
            ) * 100
        END AS nim_pct

    FROM monthly
    """

    statements["cfo_deposit_signals"] = f"""
    CREATE OR REPLACE VIEW {q}.cfo_deposit_signals AS
    WITH daily AS (
        SELECT
            CAST(date AS DATE) AS date,
            country,
            business_line,
            SUM(CAST(deposit_balance_m AS DOUBLE)) AS deposit_balance_m
        FROM {q}.raw_bank_daily_signals
        GROUP BY CAST(date AS DATE), country, business_line
    ),
    lagged AS (
        SELECT
            *,
            LAG(deposit_balance_m, 1) OVER (
                PARTITION BY country, business_line ORDER BY date
            ) AS deposit_balance_1d_ago_m,
            LAG(deposit_balance_m, 7) OVER (
                PARTITION BY country, business_line ORDER BY date
            ) AS deposit_balance_7d_ago_m,
            LAG(deposit_balance_m, 30) OVER (
                PARTITION BY country, business_line ORDER BY date
            ) AS deposit_balance_30d_ago_m
        FROM daily
    )
    SELECT
        date,
        country,
        business_line,
        deposit_balance_m,

        deposit_balance_m - deposit_balance_1d_ago_m AS deposit_change_1d_m,
        CASE
            WHEN deposit_balance_1d_ago_m <> 0
            THEN (
                deposit_balance_m / deposit_balance_1d_ago_m - 1
            ) * 100
        END AS deposit_change_1d_pct,

        deposit_balance_m - deposit_balance_7d_ago_m AS deposit_change_7d_m,
        CASE
            WHEN deposit_balance_7d_ago_m <> 0
            THEN (
                deposit_balance_m / deposit_balance_7d_ago_m - 1
            ) * 100
        END AS deposit_change_7d_pct,

        deposit_balance_m - deposit_balance_30d_ago_m AS deposit_change_30d_m,
        CASE
            WHEN deposit_balance_30d_ago_m <> 0
            THEN (
                deposit_balance_m / deposit_balance_30d_ago_m - 1
            ) * 100
        END AS deposit_change_30d_pct

    FROM lagged
    """

    statements["cfo_credit_signals"] = f"""
    CREATE OR REPLACE VIEW {q}.cfo_credit_signals AS
    SELECT
        CAST(date AS DATE) AS date,
        country,
        business_line,
        SUM(CAST(loan_balance_m AS DOUBLE)) AS loan_balance_m,
        SUM(CAST(rwa_m AS DOUBLE)) AS rwa_m,

        CASE
            WHEN SUM(CAST(loan_balance_m AS DOUBLE)) <> 0
            THEN SUM(
                CAST(stage_1_share_pct AS DOUBLE)
                * CAST(loan_balance_m AS DOUBLE)
            ) / SUM(CAST(loan_balance_m AS DOUBLE))
        END AS weighted_stage_1_share_pct,

        CASE
            WHEN SUM(CAST(loan_balance_m AS DOUBLE)) <> 0
            THEN SUM(
                CAST(stage_2_share_pct AS DOUBLE)
                * CAST(loan_balance_m AS DOUBLE)
            ) / SUM(CAST(loan_balance_m AS DOUBLE))
        END AS weighted_stage_2_share_pct,

        CASE
            WHEN SUM(CAST(loan_balance_m AS DOUBLE)) <> 0
            THEN SUM(
                CAST(stage_3_share_pct AS DOUBLE)
                * CAST(loan_balance_m AS DOUBLE)
            ) / SUM(CAST(loan_balance_m AS DOUBLE))
        END AS weighted_stage_3_share_pct,

        MAX(CASE WHEN anomaly_type = 'CREDIT_WATCH' THEN 1 ELSE 0 END)
            AS credit_watch_flag

    FROM {q}.raw_bank_daily_signals
    WHERE CAST(loan_balance_m AS DOUBLE) > 0
    GROUP BY CAST(date AS DATE), country, business_line
    """

    statements["cfo_news_intelligence"] = f"""
    CREATE OR REPLACE VIEW {q}.cfo_news_intelligence AS
    SELECT
        n.news_id,
        CAST(n.published_date AS DATE) AS published_date,
        n.headline,
        n.source,
        n.source_url,
        n.category,
        n.geographic_scope,
        n.summary,
        n.primary_affected_metric,
        n.secondary_metrics,
        n.impact_direction,
        n.potential_impact_level,
        CAST(n.relevance_score AS DOUBLE) AS relevance_score,
        CAST(n.confidence_score AS DOUBLE) AS confidence_score,
        n.bank_impact_summary,
        n.suggested_action,
        n.linked_scenario,
        n.scenario_status,

        g.country,
        g.country_code,
        CAST(g.bank_exposure_share_pct AS DOUBLE) AS bank_exposure_share_pct,
        CAST(g.geographic_relevance_weight AS DOUBLE)
            AS geographic_relevance_weight,
        CAST(g.geo_impact_score AS DOUBLE) AS geo_impact_score,
        g.map_impact_level,
        CAST(g.signed_geo_score AS DOUBLE) AS signed_geo_score,
        g.exposure_reason,

        n.classification_method,
        n.is_public_source

    FROM {q}.raw_news_signals n
    INNER JOIN {q}.raw_news_geo_impact g
        ON n.news_id = g.news_id
    """

    statements["cfo_geo_news_summary"] = f"""
    CREATE OR REPLACE VIEW {q}.cfo_geo_news_summary AS
    WITH max_date AS (
        SELECT MAX(CAST(published_date AS DATE)) AS latest_news_date
        FROM {q}.raw_news_signals
    ),
    recent AS (
        SELECT i.*
        FROM {q}.cfo_news_intelligence i
        CROSS JOIN max_date m
        WHERE i.published_date >= DATE_SUB(m.latest_news_date, 29)
    )
    SELECT
        country,
        country_code,
        MAX(bank_exposure_share_pct) AS bank_exposure_share_pct,
        COUNT(DISTINCT news_id) AS relevant_news_count,
        SUM(CASE WHEN map_impact_level = 'HIGH' THEN 1 ELSE 0 END)
            AS high_impact_news_count,
        SUM(CASE WHEN map_impact_level = 'MEDIUM' THEN 1 ELSE 0 END)
            AS medium_impact_news_count,
        MAX(geo_impact_score) AS max_geo_impact_score,
        AVG(geo_impact_score) AS avg_geo_impact_score,

        ROUND(
            0.60 * MAX(geo_impact_score)
            + 0.40 * AVG(geo_impact_score),
            1
        ) AS geo_attention_score,

        MAX(published_date) AS latest_news_date

    FROM recent
    GROUP BY country, country_code
    """

    statements["cfo_treasury_summary"] = f"""
    CREATE OR REPLACE VIEW {q}.cfo_treasury_summary AS
    SELECT
        MAX(CAST(as_of_date AS DATE)) AS as_of_date,
        SUM(CAST(book_value_m AS DOUBLE)) AS book_value_m,
        SUM(CAST(market_value_m AS DOUBLE)) AS market_value_m,
        SUM(CAST(unrealized_pnl_m AS DOUBLE)) AS unrealized_pnl_m,

        CASE
            WHEN SUM(CAST(market_value_m AS DOUBLE)) <> 0
            THEN SUM(
                CAST(market_value_m AS DOUBLE)
                * CAST(modified_duration AS DOUBLE)
            ) / SUM(CAST(market_value_m AS DOUBLE))
        END AS weighted_modified_duration,

        SUM(CAST(dv01_m_per_bp AS DOUBLE)) AS portfolio_dv01_m_per_bp,

        SUM(
            CASE WHEN accounting_classification = 'FVOCI'
            THEN CAST(market_value_m AS DOUBLE) ELSE 0 END
        ) AS fvoci_market_value_m,

        SUM(
            CASE WHEN accounting_classification = 'Amortised Cost'
            THEN CAST(market_value_m AS DOUBLE) ELSE 0 END
        ) AS amortised_cost_market_value_m,

        SUM(
            CASE WHEN is_green_bond = 1
            THEN CAST(market_value_m AS DOUBLE) ELSE 0 END
        ) AS green_bond_market_value_m

    FROM {q}.raw_treasury_portfolio
    """

    statements["cfo_treasury_scenarios"] = f"""
    CREATE OR REPLACE VIEW {q}.cfo_treasury_scenarios AS
    SELECT
        scenario_name,
        MAX(scenario_description) AS scenario_description,
        MAX(CAST(rate_shock_bps AS DOUBLE)) AS rate_shock_bps,
        MAX(CAST(credit_spread_shock_bps AS DOUBLE))
            AS credit_spread_shock_bps,
        SUM(CAST(base_market_value_m AS DOUBLE)) AS base_market_value_m,
        SUM(CAST(stressed_market_value_m AS DOUBLE))
            AS stressed_market_value_m,
        SUM(CAST(economic_value_impact_m AS DOUBLE))
            AS economic_value_impact_m,

        CASE
            WHEN SUM(CAST(base_market_value_m AS DOUBLE)) <> 0
            THEN (
                SUM(CAST(economic_value_impact_m AS DOUBLE))
                / SUM(CAST(base_market_value_m AS DOUBLE))
            ) * 100
        END AS economic_value_impact_pct,

        SUM(CAST(estimated_oci_impact_m AS DOUBLE))
            AS estimated_oci_impact_m,
        SUM(CAST(estimated_immediate_pnl_impact_m AS DOUBLE))
            AS estimated_immediate_pnl_impact_m

    FROM {q}.raw_treasury_scenario_impacts
    GROUP BY scenario_name
    """

    statements["cfo_hedge_options"] = f"""
    CREATE OR REPLACE VIEW {q}.cfo_hedge_options AS
    SELECT
        hedge_id,
        hedge_name,
        hedge_instrument,
        CAST(assumed_swap_duration_years AS DOUBLE)
            AS assumed_swap_duration_years,
        CAST(hedge_notional_m AS DOUBLE) AS hedge_notional_m,
        CAST(target_dv01_reduction_m_per_bp AS DOUBLE)
            AS target_dv01_reduction_m_per_bp,
        CAST(portfolio_dv01_before_m_per_bp AS DOUBLE)
            AS portfolio_dv01_before_m_per_bp,
        CAST(portfolio_dv01_after_m_per_bp AS DOUBLE)
            AS portfolio_dv01_after_m_per_bp,
        CAST(dv01_reduction_pct AS DOUBLE) AS dv01_reduction_pct,
        CAST(rates_plus_50bp_pnl_before_m AS DOUBLE)
            AS rates_plus_50bp_pnl_before_m,
        CAST(estimated_hedge_gain_plus_50bp_m AS DOUBLE)
            AS estimated_hedge_gain_plus_50bp_m,
        CAST(rates_plus_50bp_pnl_after_m AS DOUBLE)
            AS rates_plus_50bp_pnl_after_m,
        CAST(estimated_annual_carry_m AS DOUBLE)
            AS estimated_annual_carry_m,
        methodology_note

    FROM {q}.raw_treasury_hedge_options
    """

    statements["cfo_peer_benchmark"] = f"""
    CREATE OR REPLACE VIEW {q}.cfo_peer_benchmark AS
    SELECT
        f.bank_id,
        f.bank_name,
        f.home_market,
        f.listed_status,
        f.period,

        CAST(f.total_assets_m AS DOUBLE) AS total_assets_m,
        CAST(f.customer_loans_m AS DOUBLE) AS customer_loans_m,
        CAST(f.customer_deposits_m AS DOUBLE) AS customer_deposits_m,
        CAST(f.total_income_m AS DOUBLE) AS total_income_m,
        CAST(f.nii_m AS DOUBLE) AS nii_m,
        CAST(f.net_profit_m AS DOUBLE) AS net_profit_m,

        CAST(f.reported_return_pct AS DOUBLE) AS reported_return_pct,
        f.return_metric_type,
        CAST(f.cet1_ratio_pct AS DOUBLE) AS cet1_ratio_pct,
        CAST(f.cost_income_ratio_pct AS DOUBLE) AS cost_income_ratio_pct,
        CAST(f.cost_of_risk_bps AS DOUBLE) AS cost_of_risk_bps,
        CAST(f.lcr_pct AS DOUBLE) AS lcr_pct,
        CAST(f.npe_ratio_pct AS DOUBLE) AS npe_ratio_pct,

        CAST(p.profitability_peer_median_pct AS DOUBLE)
            AS profitability_peer_median_pct,
        CAST(p.cet1_peer_median_pct AS DOUBLE)
            AS cet1_peer_median_pct,
        CAST(p.cost_income_peer_median_pct AS DOUBLE)
            AS cost_income_peer_median_pct,
        CAST(p.profitability_vs_peer_median_pp AS DOUBLE)
            AS profitability_vs_peer_median_pp,
        CAST(p.cet1_vs_peer_median_pp AS DOUBLE)
            AS cet1_vs_peer_median_pp,
        CAST(p.efficiency_vs_peer_median_pp AS DOUBLE)
            AS efficiency_vs_peer_median_pp,

        p.positioning_quadrant,
        p.comparison_caveat,

        f.source_name,
        f.source_url,
        f.data_quality,
        f.notes

    FROM {q}.raw_peer_financials f
    LEFT JOIN {q}.raw_peer_positioning p
        ON f.bank_id = p.bank_id
    """

    statements["cfo_peer_benchmarks"] = f"""
    CREATE OR REPLACE VIEW {q}.cfo_peer_benchmarks AS
    SELECT
        metric,
        metric_label,
        CAST(peer_count AS INT) AS peer_count,
        CAST(peer_min AS DOUBLE) AS peer_min,
        CAST(peer_q1 AS DOUBLE) AS peer_q1,
        CAST(peer_median AS DOUBLE) AS peer_median,
        CAST(peer_q3 AS DOUBLE) AS peer_q3,
        CAST(peer_max AS DOUBLE) AS peer_max,
        benchmark_note

    FROM {q}.raw_peer_benchmarks
    """

    statements["cfo_strategic_radar"] = f"""
    CREATE OR REPLACE VIEW {q}.cfo_strategic_radar AS
    SELECT
        CAST(opportunity_rank AS INT) AS opportunity_rank,
        company_id,
        company_name,
        headquarters_country,
        ownership_status,
        capability_domain,
        business_model_summary,
        public_scale_metric,
        public_metric_period,
        public_source_url,
        strategic_gap_addressed,
        preferred_route,

        CAST(strategic_fit_score AS DOUBLE) AS strategic_fit_score,
        CAST(financial_attractiveness_score AS DOUBLE)
            AS financial_attractiveness_score,
        CAST(integration_feasibility_score AS DOUBLE)
            AS integration_feasibility_score,
        CAST(affordability_score AS DOUBLE) AS affordability_score,
        CAST(regulatory_complexity_score AS DOUBLE)
            AS regulatory_complexity_score,
        CAST(innovation_score AS DOUBLE) AS innovation_score,
        CAST(time_to_value_score AS DOUBLE) AS time_to_value_score,
        CAST(size_score AS DOUBLE) AS size_score,
        CAST(overall_opportunity_score AS DOUBLE)
            AS overall_opportunity_score,

        radar_status,
        strategic_rationale,
        key_risk,
        scoring_method,
        scores_are_synthetic

    FROM {q}.raw_strategic_radar
    """

    statements["cfo_capability_gaps"] = f"""
    CREATE OR REPLACE VIEW {q}.cfo_capability_gaps AS
    SELECT
        capability,
        CAST(current_score AS DOUBLE) AS current_score,
        CAST(target_score AS DOUBLE) AS target_score,
        CAST(capability_gap AS DOUBLE) AS capability_gap,
        priority,
        benchmark_direction,
        linked_companies,
        strategic_objective,
        assessment_type,
        scores_are_synthetic

    FROM {q}.raw_strategic_capability_map
    """

    for name, sql in statements.items():
        print(f"Building {q}.{name} ...")
        spark.sql(sql)
        print("  OK")

    print()
    print("-" * 78)
    print("FINAL CERTIFIED VIEW CHECK")
    print("-" * 78)

    for name in statements:
        full_name = f"{q}.{name}"

        if not spark.catalog.tableExists(full_name):
            raise RuntimeError(
                f"Expected certified view was not created: {full_name}"
            )

        row_count = spark.table(full_name).count()
        print(f"OK   {full_name} ({row_count:,} rows)")

    print()
    print(
        f"Successfully built {len(statements)} certified CFO views "
        f"in {q}."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build certified CFO views from raw Delta tables."
    )
    parser.add_argument("--catalog", default=DEFAULT_CATALOG)
    parser.add_argument("--schema", default=DEFAULT_SCHEMA)
    # Databricks interactive Python-file sessions inject IPython/kernel arguments
    # (for example: -f <connection.json>). Ignore those platform arguments
    # while still honoring the CFO pipeline arguments defined above.
    args, _unknown = parser.parse_known_args()
    return args


if __name__ == "__main__":
    args = parse_args()
    build_certified_views(
        catalog=args.catalog,
        schema=args.schema,
    )
