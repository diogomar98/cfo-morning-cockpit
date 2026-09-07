from __future__ import annotations

"""
Validate the certified CFO Morning Cockpit data layer.

This script is intended to run as the final task in the Databricks Job:

    generate_all_data
        -> load_raw_data
        -> build_certified_views
        -> validate_certified_data

It performs deterministic data-quality and financial-sanity checks.
Hard failures raise RuntimeError and fail the Databricks task.
Warnings are printed but do not fail the pipeline.

Target schema:
    workspace.cfo_cockpit
"""

import argparse
from dataclasses import dataclass
from typing import List

from pyspark.sql import SparkSession


DEFAULT_CATALOG = "workspace"
DEFAULT_SCHEMA = "cfo_cockpit"


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


def validate_certified_data(
    catalog: str = DEFAULT_CATALOG,
    schema: str = DEFAULT_SCHEMA,
) -> None:
    spark = SparkSession.builder.getOrCreate()
    q = f"{catalog}.{schema}"

    failures: List[CheckResult] = []
    warnings: List[CheckResult] = []
    passed: List[CheckResult] = []

    def scalar(sql: str):
        row = spark.sql(sql).first()
        return None if row is None else row[0]

    def pass_check(name: str, detail: str) -> None:
        passed.append(CheckResult(name, "PASS", detail))
        print(f"PASS  {name}: {detail}")

    def fail_check(name: str, detail: str) -> None:
        failures.append(CheckResult(name, "FAIL", detail))
        print(f"FAIL  {name}: {detail}")

    def warn_check(name: str, detail: str) -> None:
        warnings.append(CheckResult(name, "WARN", detail))
        print(f"WARN  {name}: {detail}")

    def expect_true(name: str, condition: bool, detail: str) -> None:
        if condition:
            pass_check(name, detail)
        else:
            fail_check(name, detail)

    def expect_range(
        name: str,
        value,
        low: float,
        high: float,
        unit: str = "",
    ) -> None:
        if value is None:
            fail_check(name, "value is NULL")
            return

        value = float(value)
        if low <= value <= high:
            pass_check(
                name,
                f"{value:,.4f}{unit} within [{low}, {high}]{unit}",
            )
        else:
            fail_check(
                name,
                f"{value:,.4f}{unit} outside [{low}, {high}]{unit}",
            )

    print("=" * 82)
    print("CFO MORNING COCKPIT — CERTIFIED DATA VALIDATION")
    print("=" * 82)
    print(f"Schema: {q}")
    print()

    # ------------------------------------------------------------------
    # 1. Required certified views exist
    # ------------------------------------------------------------------
    required_views = [
        "cfo_financial_history",
        "cfo_current_position",
        "cfo_daily_bank",
        "cfo_daily_country",
        "cfo_daily_business_country",
        "cfo_monthly_nim",
        "cfo_deposit_signals",
        "cfo_credit_signals",
        "cfo_news_intelligence",
        "cfo_geo_news_summary",
        "cfo_treasury_summary",
        "cfo_treasury_scenarios",
        "cfo_hedge_options",
        "cfo_peer_benchmark",
        "cfo_peer_benchmarks",
        "cfo_strategic_radar",
        "cfo_capability_gaps",
    ]

    for view_name in required_views:
        full_name = f"{q}.{view_name}"
        exists = spark.catalog.tableExists(full_name)
        expect_true(
            f"view_exists::{view_name}",
            exists,
            f"{full_name} exists",
        )

    if failures:
        raise RuntimeError(
            "Certified view existence checks failed. "
            "Fix build_certified_views before running deeper validation."
        )

    print()
    print("-" * 82)
    print("CURRENT POSITION")
    print("-" * 82)

    # ------------------------------------------------------------------
    # 2. Current position integrity
    # ------------------------------------------------------------------
    current_count = int(
        scalar(f"SELECT COUNT(*) FROM {q}.cfo_current_position")
    )
    expect_true(
        "current_position_single_row",
        current_count == 1,
        f"row count = {current_count}, expected 1",
    )

    certified_date = scalar(
        f"SELECT as_of_date FROM {q}.cfo_current_position"
    )
    raw_latest_date = scalar(
        f"SELECT MAX(CAST(date AS DATE)) FROM {q}.raw_bank_history"
    )
    expect_true(
        "current_position_latest_date",
        certified_date == raw_latest_date,
        f"certified={certified_date}, raw_latest={raw_latest_date}",
    )

    cet1 = scalar(
        f"SELECT cet1_ratio_pct FROM {q}.cfo_current_position"
    )
    lcr = scalar(
        f"SELECT lcr_pct FROM {q}.cfo_current_position"
    )
    ltd = scalar(
        f"SELECT loan_to_deposit_pct FROM {q}.cfo_current_position"
    )
    ytd_cir = scalar(
        f"SELECT ytd_cost_income_ratio_pct FROM {q}.cfo_current_position"
    )
    ytd_roe = scalar(
        f"SELECT annualised_ytd_roe_proxy_pct FROM {q}.cfo_current_position"
    )

    # Broad prototype sanity bands, not regulatory thresholds.
    expect_range("current_cet1_ratio", cet1, 5.0, 30.0, "%")
    expect_range("current_lcr", lcr, 80.0, 300.0, "%")
    expect_range("current_loan_to_deposit", ltd, 50.0, 150.0, "%")
    expect_range("ytd_cost_income", ytd_cir, 20.0, 100.0, "%")
    expect_range("annualised_ytd_roe_proxy", ytd_roe, -20.0, 40.0, "%")

    latest_raw_loans = scalar(
        f"""
        SELECT CAST(loans AS DOUBLE)
        FROM {q}.raw_bank_history
        WHERE CAST(date AS DATE) = (
            SELECT MAX(CAST(date AS DATE))
            FROM {q}.raw_bank_history
        )
        """
    )
    certified_loans = scalar(
        f"SELECT loans_m FROM {q}.cfo_current_position"
    )
    loans_diff = abs(float(certified_loans) - float(latest_raw_loans))
    expect_true(
        "current_loans_reconcile",
        loans_diff < 0.01,
        f"difference = EUR {loans_diff:,.6f}m",
    )

    latest_raw_deposits = scalar(
        f"""
        SELECT CAST(deposits AS DOUBLE)
        FROM {q}.raw_bank_history
        WHERE CAST(date AS DATE) = (
            SELECT MAX(CAST(date AS DATE))
            FROM {q}.raw_bank_history
        )
        """
    )
    certified_deposits = scalar(
        f"SELECT deposits_m FROM {q}.cfo_current_position"
    )
    deposits_diff = abs(
        float(certified_deposits) - float(latest_raw_deposits)
    )
    expect_true(
        "current_deposits_reconcile",
        deposits_diff < 0.01,
        f"difference = EUR {deposits_diff:,.6f}m",
    )

    print()
    print("-" * 82)
    print("DAILY / MONTHLY FINANCIAL ENGINE")
    print("-" * 82)

    # ------------------------------------------------------------------
    # 3. Daily engine completeness
    # ------------------------------------------------------------------
    daily_rows = int(
        scalar(f"SELECT COUNT(*) FROM {q}.cfo_daily_bank")
    )
    distinct_daily_dates = int(
        scalar(
            f"SELECT COUNT(DISTINCT date) FROM {q}.cfo_daily_bank"
        )
    )
    expect_true(
        "daily_bank_unique_dates",
        daily_rows == distinct_daily_dates,
        f"rows={daily_rows}, distinct_dates={distinct_daily_dates}",
    )

    daily_min = scalar(
        f"SELECT MIN(date) FROM {q}.cfo_daily_bank"
    )
    daily_max = scalar(
        f"SELECT MAX(date) FROM {q}.cfo_daily_bank"
    )

    expect_true(
        "daily_bank_start_date",
        str(daily_min) == "2026-01-01",
        f"start={daily_min}, expected 2026-01-01",
    )
    expect_true(
        "daily_bank_end_date",
        str(daily_max) == "2026-08-31",
        f"end={daily_max}, expected 2026-08-31",
    )

    nonpositive_assets = int(
        scalar(
            f"""
            SELECT COUNT(*)
            FROM {q}.cfo_daily_bank
            WHERE interest_earning_assets_m <= 0
            """
        )
    )
    expect_true(
        "daily_assets_positive",
        nonpositive_assets == 0,
        f"non-positive daily asset rows = {nonpositive_assets}",
    )

    nonpositive_deposits = int(
        scalar(
            f"""
            SELECT COUNT(*)
            FROM {q}.cfo_daily_bank
            WHERE deposit_balance_m <= 0
            """
        )
    )
    expect_true(
        "daily_deposits_positive",
        nonpositive_deposits == 0,
        f"non-positive daily deposit rows = {nonpositive_deposits}",
    )

    nim_outliers = int(
        scalar(
            f"""
            SELECT COUNT(*)
            FROM {q}.cfo_monthly_nim
            WHERE nim_pct IS NULL
               OR nim_pct < -2
               OR nim_pct > 10
            """
        )
    )
    expect_true(
        "monthly_nim_plausibility",
        nim_outliers == 0,
        f"outlier/null months = {nim_outliers}",
    )

    monthly_rows = int(
        scalar(f"SELECT COUNT(*) FROM {q}.cfo_monthly_nim")
    )
    expect_true(
        "monthly_nim_month_count",
        monthly_rows == 8,
        f"months={monthly_rows}, expected 8 for Jan-Aug 2026",
    )

    # Monthly daily-NII should reconcile to monthly bank_history NII.
    max_monthly_nii_diff = scalar(
        f"""
        WITH certified AS (
            SELECT
                month,
                monthly_nii_m
            FROM {q}.cfo_monthly_nim
        ),
        history AS (
            SELECT
                DATE_TRUNC('month', CAST(date AS DATE)) AS month,
                CAST(nii AS DOUBLE) AS history_nii_m
            FROM {q}.raw_bank_history
            WHERE CAST(date AS DATE)
                BETWEEN DATE('2026-01-01') AND DATE('2026-08-31')
        )
        SELECT MAX(ABS(c.monthly_nii_m - h.history_nii_m))
        FROM certified c
        INNER JOIN history h
            ON c.month = h.month
        """
    )
    expect_true(
        "monthly_nii_reconciliation",
        float(max_monthly_nii_diff) < 0.05,
        f"max difference = EUR {float(max_monthly_nii_diff):,.6f}m",
    )

    print()
    print("-" * 82)
    print("CREDIT / DEPOSIT SIGNALS")
    print("-" * 82)

    # ------------------------------------------------------------------
    # 4. Deposit / credit signal quality
    # ------------------------------------------------------------------
    deposit_rows = int(
        scalar(f"SELECT COUNT(*) FROM {q}.cfo_deposit_signals")
    )
    expect_true(
        "deposit_signals_nonempty",
        deposit_rows > 0,
        f"rows={deposit_rows}",
    )

    bad_stage_rows = int(
        scalar(
            f"""
            SELECT COUNT(*)
            FROM {q}.cfo_credit_signals
            WHERE weighted_stage_1_share_pct < 0
               OR weighted_stage_2_share_pct < 0
               OR weighted_stage_3_share_pct < 0
               OR weighted_stage_1_share_pct > 100
               OR weighted_stage_2_share_pct > 100
               OR weighted_stage_3_share_pct > 100
               OR ABS(
                    weighted_stage_1_share_pct
                    + weighted_stage_2_share_pct
                    + weighted_stage_3_share_pct
                    - 100
               ) > 0.05
            """
        )
    )
    expect_true(
        "credit_stage_shares_valid",
        bad_stage_rows == 0,
        f"invalid weighted stage rows={bad_stage_rows}",
    )

    credit_watch_rows = int(
        scalar(
            f"""
            SELECT COUNT(*)
            FROM {q}.cfo_credit_signals
            WHERE credit_watch_flag = 1
            """
        )
    )
    if credit_watch_rows > 0:
        pass_check(
            "controlled_credit_watch_present",
            f"{credit_watch_rows} certified rows flagged",
        )
    else:
        warn_check(
            "controlled_credit_watch_present",
            "no credit-watch rows found; expected synthetic June event",
        )

    print()
    print("-" * 82)
    print("NEWS / GEOGRAPHY")
    print("-" * 82)

    # ------------------------------------------------------------------
    # 5. News / map quality
    # ------------------------------------------------------------------
    news_count = int(
        scalar(
            f"""
            SELECT COUNT(DISTINCT news_id)
            FROM {q}.cfo_news_intelligence
            """
        )
    )
    expect_true(
        "news_articles_present",
        news_count >= 50,
        f"distinct news items={news_count}",
    )

    geo_country_count = int(
        scalar(
            f"""
            SELECT COUNT(DISTINCT country_code)
            FROM {q}.cfo_news_intelligence
            WHERE country_code IN ('NL', 'DE', 'FR', 'BE')
            """
        )
    )
    expect_true(
        "news_four_core_countries",
        geo_country_count == 4,
        f"core countries present={geo_country_count}/4",
    )

    invalid_geo_scores = int(
        scalar(
            f"""
            SELECT COUNT(*)
            FROM {q}.cfo_news_intelligence
            WHERE geo_impact_score < 0
               OR geo_impact_score > 100
               OR relevance_score < 0
               OR relevance_score > 100
               OR confidence_score < 0
               OR confidence_score > 1
            """
        )
    )
    expect_true(
        "news_scores_valid",
        invalid_geo_scores == 0,
        f"invalid score rows={invalid_geo_scores}",
    )

    map_rows = int(
        scalar(f"SELECT COUNT(*) FROM {q}.cfo_geo_news_summary")
    )
    expect_true(
        "geo_news_summary_four_rows",
        map_rows == 4,
        f"rows={map_rows}, expected 4 countries",
    )

    print()
    print("-" * 82)
    print("TREASURY / SCENARIOS")
    print("-" * 82)

    # ------------------------------------------------------------------
    # 6. Treasury reconciliation and scenario completeness
    # ------------------------------------------------------------------
    treasury_summary_count = int(
        scalar(f"SELECT COUNT(*) FROM {q}.cfo_treasury_summary")
    )
    expect_true(
        "treasury_summary_single_row",
        treasury_summary_count == 1,
        f"rows={treasury_summary_count}",
    )

    raw_treasury_book = scalar(
        f"""
        SELECT SUM(CAST(book_value_m AS DOUBLE))
        FROM {q}.raw_treasury_portfolio
        """
    )
    cert_treasury_book = scalar(
        f"SELECT book_value_m FROM {q}.cfo_treasury_summary"
    )
    treasury_book_diff = abs(
        float(raw_treasury_book) - float(cert_treasury_book)
    )
    expect_true(
        "treasury_book_reconciliation",
        treasury_book_diff < 0.01,
        f"difference = EUR {treasury_book_diff:,.6f}m",
    )

    scenario_count = int(
        scalar(
            f"""
            SELECT COUNT(DISTINCT scenario_name)
            FROM {q}.cfo_treasury_scenarios
            """
        )
    )
    expect_true(
        "treasury_scenario_count",
        scenario_count == 5,
        f"scenarios={scenario_count}, expected 5",
    )

    hedge_count = int(
        scalar(f"SELECT COUNT(*) FROM {q}.cfo_hedge_options")
    )
    expect_true(
        "hedge_option_count",
        hedge_count == 4,
        f"hedge options={hedge_count}, expected 4",
    )

    rate_up_impact = scalar(
        f"""
        SELECT economic_value_impact_m
        FROM {q}.cfo_treasury_scenarios
        WHERE scenario_name = 'Rates +50bps'
        """
    )
    if rate_up_impact is None:
        fail_check(
            "rates_plus_50_scenario_present",
            "Rates +50bps scenario not found",
        )
    else:
        expect_true(
            "rates_plus_50_direction",
            float(rate_up_impact) < 0,
            f"economic value impact = EUR {float(rate_up_impact):,.1f}m; expected negative",
        )

    print()
    print("-" * 82)
    print("PEERS / STRATEGIC RADAR")
    print("-" * 82)

    # ------------------------------------------------------------------
    # 7. Peer completeness
    # ------------------------------------------------------------------
    peer_count = int(
        scalar(f"SELECT COUNT(*) FROM {q}.cfo_peer_benchmark")
    )
    expect_true(
        "peer_count",
        peer_count == 8,
        f"real peers={peer_count}, expected 8",
    )

    benchmark_count = int(
        scalar(f"SELECT COUNT(*) FROM {q}.cfo_peer_benchmarks")
    )
    expect_true(
        "peer_benchmark_metric_count",
        benchmark_count == 5,
        f"benchmark metrics={benchmark_count}, expected 5",
    )

    bad_peer_medians = int(
        scalar(
            f"""
            SELECT COUNT(*)
            FROM {q}.cfo_peer_benchmarks
            WHERE peer_median IS NULL
            """
        )
    )
    expect_true(
        "peer_medians_nonnull",
        bad_peer_medians == 0,
        f"null median metrics={bad_peer_medians}",
    )

    # ------------------------------------------------------------------
    # 8. Strategic radar consistency
    # ------------------------------------------------------------------
    radar_count = int(
        scalar(f"SELECT COUNT(*) FROM {q}.cfo_strategic_radar")
    )
    expect_true(
        "strategic_radar_count",
        radar_count == 10,
        f"companies={radar_count}, expected 10",
    )

    invalid_radar_scores = int(
        scalar(
            f"""
            SELECT COUNT(*)
            FROM {q}.cfo_strategic_radar
            WHERE strategic_fit_score NOT BETWEEN 0 AND 100
               OR financial_attractiveness_score NOT BETWEEN 0 AND 100
               OR integration_feasibility_score NOT BETWEEN 0 AND 100
               OR affordability_score NOT BETWEEN 0 AND 100
               OR regulatory_complexity_score NOT BETWEEN 0 AND 100
               OR innovation_score NOT BETWEEN 0 AND 100
               OR time_to_value_score NOT BETWEEN 0 AND 100
               OR overall_opportunity_score NOT BETWEEN 0 AND 100
            """
        )
    )
    expect_true(
        "strategic_scores_valid",
        invalid_radar_scores == 0,
        f"invalid score rows={invalid_radar_scores}",
    )

    distinct_ranks = int(
        scalar(
            f"""
            SELECT COUNT(DISTINCT opportunity_rank)
            FROM {q}.cfo_strategic_radar
            """
        )
    )
    expect_true(
        "strategic_ranks_unique",
        distinct_ranks == radar_count,
        f"distinct ranks={distinct_ranks}, companies={radar_count}",
    )

    capability_count = int(
        scalar(f"SELECT COUNT(*) FROM {q}.cfo_capability_gaps")
    )
    expect_true(
        "capability_gap_count",
        capability_count == 8,
        f"capabilities={capability_count}, expected 8",
    )

    inconsistent_gaps = int(
        scalar(
            f"""
            SELECT COUNT(*)
            FROM {q}.cfo_capability_gaps
            WHERE ABS(
                capability_gap - (target_score - current_score)
            ) > 0.0001
            """
        )
    )
    expect_true(
        "capability_gap_arithmetic",
        inconsistent_gaps == 0,
        f"inconsistent rows={inconsistent_gaps}",
    )

    # Keep synthetic-management scoring visibly labelled.
    unlabelled_synthetic_scores = int(
        scalar(
            f"""
            SELECT COUNT(*)
            FROM {q}.cfo_strategic_radar
            WHERE scores_are_synthetic <> TRUE
            """
        )
    )
    if unlabelled_synthetic_scores == 0:
        pass_check(
            "strategic_scores_labelled_synthetic",
            "all strategic score rows are explicitly labelled synthetic",
        )
    else:
        fail_check(
            "strategic_scores_labelled_synthetic",
            f"{unlabelled_synthetic_scores} rows are not labelled synthetic",
        )

    print()
    print("=" * 82)
    print("VALIDATION SUMMARY")
    print("=" * 82)
    print(f"Passed:   {len(passed)}")
    print(f"Warnings: {len(warnings)}")
    print(f"Failed:   {len(failures)}")

    if warnings:
        print()
        print("Warnings:")
        for item in warnings:
            print(f"  - {item.name}: {item.detail}")

    if failures:
        print()
        print("Failures:")
        for item in failures:
            print(f"  - {item.name}: {item.detail}")

        raise RuntimeError(
            f"Certified data validation failed with "
            f"{len(failures)} failing check(s)."
        )

    print()
    print("All hard data-quality checks passed successfully.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate certified CFO Morning Cockpit data."
    )
    parser.add_argument("--catalog", default=DEFAULT_CATALOG)
    parser.add_argument("--schema", default=DEFAULT_SCHEMA)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    validate_certified_data(
        catalog=args.catalog,
        schema=args.schema,
    )
