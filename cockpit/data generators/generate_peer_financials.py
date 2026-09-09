from pathlib import Path
import argparse
import os
import numpy as np
import pandas as pd

# Allows the embedded public-data literal to represent missing values safely.
nan = np.nan

PEER_DATA = [{'bank_id': 'ABN', 'bank_name': 'ABN AMRO', 'home_market': 'Netherlands', 'listed_status': 'Listed', 'period': 'FY2025', 'total_assets_m': nan, 'customer_loans_m': nan, 'customer_deposits_m': nan, 'funding_base_m': nan, 'funding_base_definition': '', 'total_income_m': nan, 'nii_m': nan, 'net_profit_m': nan, 'reported_return_pct': 8.7, 'return_metric_type': 'ROE', 'cet1_ratio_pct': 15.4, 'cost_income_ratio_pct': nan, 'cost_income_definition': '', 'cost_of_risk_bps': 1.0, 'lcr_pct': nan, 'npe_ratio_pct': nan, 'source_name': 'ABN AMRO Q4/FY2025 results', 'source_url': 'https://www.abnamro.com/en/news/abn-amro-posts-net-profit-of-eur-410-million-in-q4-2025', 'data_quality': 'PUBLIC_REPORTED', 'notes': 'FY2025 ROE 8.7%, CET1 15.4%, cost of risk 1 bp. ABN AMRO stated FY2025 NII was in line with guidance above EUR 6.3bn; an exact NII figure is not inserted.'}, {'bank_id': 'ING', 'bank_name': 'ING', 'home_market': 'Netherlands / Europe', 'listed_status': 'Listed', 'period': 'FY2025', 'total_assets_m': 1060000.0, 'customer_loans_m': 727600.0, 'customer_deposits_m': nan, 'funding_base_m': nan, 'funding_base_definition': '', 'total_income_m': 23000.0, 'nii_m': 15300.0, 'net_profit_m': 6300.0, 'reported_return_pct': 13.2, 'return_metric_type': 'ROE', 'cet1_ratio_pct': 13.1, 'cost_income_ratio_pct': 54.6, 'cost_income_definition': 'ING reported cost/income ratio', 'cost_of_risk_bps': nan, 'lcr_pct': nan, 'npe_ratio_pct': nan, 'source_name': 'ING FY2025 results / Annual Report 2025', 'source_url': 'https://ing.com/news/press-releases/4qfy2025-ing-press-release.html', 'data_quality': 'PUBLIC_REPORTED', 'notes': "Total assets EUR 1,060bn shown in ING's 2025 annual-report taxonomy disclosure; customer lending EUR 727.6bn; commercial NII EUR 15.3bn."}, {'bank_id': 'RABO', 'bank_name': 'Rabobank', 'home_market': 'Netherlands', 'listed_status': 'Cooperative', 'period': 'FY2025', 'total_assets_m': nan, 'customer_loans_m': nan, 'customer_deposits_m': nan, 'funding_base_m': nan, 'funding_base_definition': '', 'total_income_m': nan, 'nii_m': nan, 'net_profit_m': 4957.0, 'reported_return_pct': 9.1, 'return_metric_type': 'ROE', 'cet1_ratio_pct': 20.3, 'cost_income_ratio_pct': 54.5, 'cost_income_definition': 'Rabobank reported cost/income ratio', 'cost_of_risk_bps': nan, 'lcr_pct': nan, 'npe_ratio_pct': nan, 'source_name': 'Rabobank FY2025 results', 'source_url': 'https://www.rabobank.com/about-us/press/articles/011514168/rabobank-posts-a-net-result-of-eur-4-957-million-in-2025', 'data_quality': 'PUBLIC_REPORTED', 'notes': 'Net result EUR 4,957m, ROE 9.1%, CET1 20.3% and cost/income 54.5%.'}, {'bank_id': 'DB', 'bank_name': 'Deutsche Bank', 'home_market': 'Germany / Global', 'listed_status': 'Listed', 'period': 'FY2025', 'total_assets_m': 1435067.0, 'customer_loans_m': 479000.0, 'customer_deposits_m': 692000.0, 'funding_base_m': 692000.0, 'funding_base_definition': 'Deposits', 'total_income_m': 32100.0, 'nii_m': 13700.0, 'net_profit_m': 7100.0, 'reported_return_pct': 10.3, 'return_metric_type': 'RoTE', 'cet1_ratio_pct': 14.2, 'cost_income_ratio_pct': 64.0, 'cost_income_definition': 'Deutsche Bank reported cost/income ratio', 'cost_of_risk_bps': nan, 'lcr_pct': 144.0, 'npe_ratio_pct': nan, 'source_name': 'Deutsche Bank FY2025 results / Annual Report', 'source_url': 'https://www.db.com/news/detail/20260129-full-year-results-2025?language_id=1', 'data_quality': 'PUBLIC_REPORTED', 'notes': 'Reported net revenues EUR 32.1bn, net profit EUR 7.1bn, RoTE 10.3%, CET1 14.2%, cost/income 64%, LCR 144%, deposits EUR 692bn.'}, {'bank_id': 'CBK', 'bank_name': 'Commerzbank', 'home_market': 'Germany', 'listed_status': 'Listed', 'period': 'FY2025', 'total_assets_m': 590000.0, 'customer_loans_m': nan, 'customer_deposits_m': nan, 'funding_base_m': nan, 'funding_base_definition': '', 'total_income_m': 12200.0, 'nii_m': 8226.0, 'net_profit_m': 2625.0, 'reported_return_pct': 8.7, 'return_metric_type': 'Net RoTE', 'cet1_ratio_pct': 14.7, 'cost_income_ratio_pct': 57.0, 'cost_income_definition': 'Commerzbank reported cost-income ratio', 'cost_of_risk_bps': nan, 'lcr_pct': nan, 'npe_ratio_pct': 1.1, 'source_name': 'Commerzbank FY2025 annual results', 'source_url': 'https://www.commerzbank.de/group/newsroom/press-releases/annual-press-conference.html', 'data_quality': 'PUBLIC_REPORTED', 'notes': 'Total assets EUR 590bn, revenues EUR 12.2bn, NII EUR 8.226bn, net result EUR 2.625bn, Net RoTE 8.7%, CET1 14.7%, cost-income 57%.'}, {'bank_id': 'BNP', 'bank_name': 'BNP Paribas', 'home_market': 'France / Belgium / Europe', 'listed_status': 'Listed', 'period': 'FY2025', 'total_assets_m': 2792981.0, 'customer_loans_m': 897358.0, 'customer_deposits_m': 1075564.0, 'funding_base_m': 1075564.0, 'funding_base_definition': 'Customer deposits', 'total_income_m': 51223.0, 'nii_m': nan, 'net_profit_m': 12225.0, 'reported_return_pct': 11.6, 'return_metric_type': 'RoTE', 'cet1_ratio_pct': 12.6, 'cost_income_ratio_pct': 61.2, 'cost_income_definition': 'Derived: reported operating expenses / revenues', 'cost_of_risk_bps': 36.0, 'lcr_pct': nan, 'npe_ratio_pct': nan, 'source_name': 'BNP Paribas FY2025 results', 'source_url': 'https://invest.bnpparibas/en/document/4q25-pr', 'data_quality': 'PUBLIC_REPORTED_DERIVED', 'notes': 'Assets, customer loans/deposits, revenue, net income and CET1 are public reported. Cost/income is derived from reported FY operating expenses and revenue.'}, {'bank_id': 'SG', 'bank_name': 'Société Générale', 'home_market': 'France / Europe', 'listed_status': 'Listed', 'period': 'FY2025', 'total_assets_m': nan, 'customer_loans_m': nan, 'customer_deposits_m': nan, 'funding_base_m': nan, 'funding_base_definition': '', 'total_income_m': 27300.0, 'nii_m': nan, 'net_profit_m': 6000.0, 'reported_return_pct': 10.2, 'return_metric_type': 'RoTE', 'cet1_ratio_pct': 13.5, 'cost_income_ratio_pct': 63.6, 'cost_income_definition': 'Société Générale reported cost/income ratio', 'cost_of_risk_bps': 26.0, 'lcr_pct': nan, 'npe_ratio_pct': nan, 'source_name': 'Société Générale FY2025 results', 'source_url': 'https://www.societegenerale.com/en/news/press-release/4th-quarter-and-full-year-2025-results', 'data_quality': 'PUBLIC_REPORTED', 'notes': 'Revenue EUR 27.3bn, group net income EUR 6.0bn, RoTE 10.2%, CET1 13.5%, cost/income 63.6%, cost of risk 26 bps.'}, {'bank_id': 'KBC', 'bank_name': 'KBC Group', 'home_market': 'Belgium / Central Europe', 'listed_status': 'Listed', 'period': 'FY2025', 'total_assets_m': 397372.0, 'customer_loans_m': 208612.0, 'customer_deposits_m': nan, 'funding_base_m': 288769.0, 'funding_base_definition': 'Customer deposits and debt securities (reported combined)', 'total_income_m': 12200.0, 'nii_m': nan, 'net_profit_m': 3568.0, 'reported_return_pct': 15.0, 'return_metric_type': 'ROE', 'cet1_ratio_pct': 14.9, 'cost_income_ratio_pct': 46.0, 'cost_income_definition': 'KBC reported FY cost/income; excludes certain non-operating items', 'cost_of_risk_bps': 13.0, 'lcr_pct': 159.0, 'npe_ratio_pct': nan, 'source_name': 'KBC FY2025 results / financial performance', 'source_url': 'https://newsroom.kbc.com/kbc-group-fourth-quarter-result-of-1-003-million-euros', 'data_quality': 'PUBLIC_REPORTED', 'notes': 'KBC is a bancassurance group, so some metrics are less directly comparable with pure banks. Reported ROE 15%, CET1 14.9%, LCR 159%, FY net profit EUR 3.568bn.'}]


def generate_peer_datasets(output_dir: str = "data"):
    peers = pd.DataFrame(PEER_DATA)

    profit_median = float(peers["reported_return_pct"].median(skipna=True))
    cet1_median = float(peers["cet1_ratio_pct"].median(skipna=True))
    cir_median = float(peers["cost_income_ratio_pct"].median(skipna=True))

    position_rows = []
    for r in peers.itertuples(index=False):
        p = r.reported_return_pct
        c = r.cet1_ratio_pct
        cir = r.cost_income_ratio_pct

        high_profit = p >= profit_median
        high_capital = c >= cet1_median

        if high_profit and high_capital:
            quadrant = "Strong profitability & capital"
        elif high_profit and not high_capital:
            quadrant = "High return / lower capital"
        elif (not high_profit) and high_capital:
            quadrant = "Capital strength / return gap"
        else:
            quadrant = "Return & capital improvement zone"

        position_rows.append(
            {
                "bank_id": r.bank_id,
                "bank_name": r.bank_name,
                "home_market": r.home_market,
                "reported_return_pct": p,
                "return_metric_type": r.return_metric_type,
                "cet1_ratio_pct": c,
                "cost_income_ratio_pct": cir,
                "profitability_peer_median_pct": round(profit_median, 2),
                "cet1_peer_median_pct": round(cet1_median, 2),
                "cost_income_peer_median_pct": round(cir_median, 2),
                "profitability_vs_peer_median_pp": round(p - profit_median, 2),
                "cet1_vs_peer_median_pp": round(c - cet1_median, 2),
                "efficiency_vs_peer_median_pp": (
                    round(cir_median - cir, 2) if pd.notna(cir) else np.nan
                ),
                "positioning_quadrant": quadrant,
                "comparison_caveat": (
                    "Directional peer benchmark only. Reported return metrics mix ROE and RoTE/Net RoTE; "
                    "cost/income definitions can differ by bank."
                ),
            }
        )

    positioning = pd.DataFrame(position_rows)

    benchmark_rows = []
    for metric, label in [
        ("reported_return_pct", "Reported return"),
        ("cet1_ratio_pct", "CET1 ratio"),
        ("cost_income_ratio_pct", "Cost/income ratio"),
        ("cost_of_risk_bps", "Cost of risk"),
        ("lcr_pct", "LCR"),
    ]:
        s = pd.to_numeric(peers[metric], errors="coerce").dropna()
        benchmark_rows.append(
            {
                "metric": metric,
                "metric_label": label,
                "peer_count": len(s),
                "peer_min": round(float(s.min()), 2),
                "peer_q1": round(float(s.quantile(0.25)), 2),
                "peer_median": round(float(s.median()), 2),
                "peer_q3": round(float(s.quantile(0.75)), 2),
                "peer_max": round(float(s.max()), 2),
                "benchmark_note": (
                    "Based on collected FY2025 public peer disclosures. "
                    "Check metric definitions before using as a regulatory-grade benchmark."
                ),
            }
        )

    benchmarks = pd.DataFrame(benchmark_rows)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    peers.to_csv(out / "peer_financials.csv", index=False)
    positioning.to_csv(out / "peer_positioning.csv", index=False)
    benchmarks.to_csv(out / "peer_benchmarks.csv", index=False)

    return peers, positioning, benchmarks


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate peer benchmarking datasets.")
    parser.add_argument("--output-dir", default=os.getenv("CFO_OUTPUT_DIR", "data"))
    args = parser.parse_args()

    peers, positioning, benchmarks = generate_peer_datasets(output_dir=args.output_dir)
    print(f"Created peer_financials.csv with {len(peers)} real peers.")
    print(f"Created peer_positioning.csv with {len(positioning)} peers.")
    print(f"Created peer_benchmarks.csv with {len(benchmarks)} benchmark metrics.")
