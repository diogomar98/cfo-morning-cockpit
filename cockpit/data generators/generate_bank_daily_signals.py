from __future__ import annotations

import argparse
import os
import calendar
import csv
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np


COUNTRIES = ["Netherlands", "Germany", "France", "Belgium"]

# Shares are intentionally synthetic, but stable and transparent.
LOAN_COUNTRY_SHARES = {
    "Netherlands": 0.45,
    "Germany": 0.23,
    "France": 0.19,
    "Belgium": 0.13,
}
DEPOSIT_COUNTRY_SHARES = {
    "Netherlands": 0.46,
    "Germany": 0.22,
    "France": 0.18,
    "Belgium": 0.14,
}

LOAN_BUSINESS_SHARES = {
    "Retail": 0.50,
    "Corporate": 0.40,
    "Private Banking": 0.10,
}
DEPOSIT_BUSINESS_SHARES = {
    "Retail": 0.52,
    "Corporate": 0.34,
    "Private Banking": 0.14,
}

LOAN_PRODUCTS = {
    "Retail": {"Mortgage": 0.82, "Consumer Loan": 0.18},
    "Corporate": {"Corporate Loan": 1.00},
    "Private Banking": {"Lombard Loan": 1.00},
}
DEPOSIT_PRODUCTS = {
    "Retail": {
        "Savings Deposit": 0.48,
        "Current Account": 0.34,
        "Term Deposit": 0.18,
    },
    "Corporate": {
        "Corporate Current Account": 0.58,
        "Corporate Term Deposit": 0.42,
    },
    "Private Banking": {"Private Banking Cash": 1.00},
}

LOAN_RATE_SPREADS = {
    "Mortgage": -0.40,
    "Consumer Loan": 1.80,
    "Corporate Loan": 0.35,
    "Lombard Loan": 0.60,
}
DEPOSIT_RATE_SPREADS = {
    "Savings Deposit": 0.15,
    "Current Account": -0.75,
    "Term Deposit": 0.65,
    "Corporate Current Account": -0.45,
    "Corporate Term Deposit": 0.55,
    "Private Banking Cash": -0.15,
}
COUNTRY_RATE_SPREADS = {
    "Netherlands": -0.03,
    "Germany": 0.02,
    "France": 0.05,
    "Belgium": 0.01,
}

CREDIT_RISK_FACTORS = {
    "Mortgage": 0.70,
    "Consumer Loan": 1.25,
    "Corporate Loan": 1.30,
    "Lombard Loan": 0.80,
}
COUNTRY_CREDIT_FACTORS = {
    "Netherlands": 0.90,
    "Germany": 1.00,
    "France": 1.10,
    "Belgium": 1.05,
}

OUTPUT_FIELDS = [
    "date",
    "country",
    "business_line",
    "product",
    "balance_type",
    "loan_balance_m",
    "deposit_balance_m",
    "interest_rate_pct",
    "ecb_rate_pct",
    "daily_interest_income_m",
    "daily_interest_expense_m",
    "daily_nii_m",
    "stage_1_share_pct",
    "stage_2_share_pct",
    "stage_3_share_pct",
    "rwa_m",
    "deposit_change_1d_m",
    "deposit_change_1d_pct",
    "deposit_change_7d_m",
    "deposit_change_7d_pct",
    "deposit_change_30d_m",
    "deposit_change_30d_pct",
    "anomaly_flag",
    "anomaly_type",
    "source_month_end_date",
]


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def previous_month_end(d: date) -> date:
    first = d.replace(day=1)
    return first - timedelta(days=1)


def daterange(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def read_bank_history(path: Path) -> Dict[date, Dict[str, float]]:
    history: Dict[date, Dict[str, float]] = {}
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = parse_date(row["date"])
            parsed = {"date": d}
            for key, value in row.items():
                if key == "date":
                    continue
                parsed[key] = float(value)
            history[d] = parsed
    return history


def bridge_profile(d: date, center_day: int, sigma: float) -> float:
    """Gaussian-shaped intramonth profile forced to zero at both month endpoints."""
    days = calendar.monthrange(d.year, d.month)[1]
    x = d.day
    raw = np.exp(-0.5 * ((x - center_day) / sigma) ** 2)
    start_raw = np.exp(-0.5 * ((1 - center_day) / sigma) ** 2)
    end_raw = np.exp(-0.5 * ((days - center_day) / sigma) ** 2)
    linear_endpoint = start_raw + (end_raw - start_raw) * ((x - 1) / max(days - 1, 1))
    return float(raw - linear_endpoint)


def daily_bank_targets(
    history: Dict[date, Dict[str, float]],
    start: date,
    end: date,
    seed: int,
) -> Dict[date, Dict[str, float]]:
    rng = np.random.default_rng(seed)

    monthly_params: Dict[Tuple[int, int], Dict[str, float]] = {}
    for d in daterange(start, end):
        key = (d.year, d.month)
        if key not in monthly_params:
            monthly_params[key] = {
                "loan_phase": float(rng.uniform(0, 2 * np.pi)),
                "deposit_phase": float(rng.uniform(0, 2 * np.pi)),
                "rate_phase": float(rng.uniform(0, 2 * np.pi)),
            }

    result: Dict[date, Dict[str, float]] = {}

    for d in daterange(start, end):
        curr_me = month_end(d)
        prev_me = previous_month_end(d)
        if curr_me not in history or prev_me not in history:
            raise ValueError(
                f"bank_history.csv needs both {prev_me} and {curr_me} to generate {d}."
            )

        prev = history[prev_me]
        curr = history[curr_me]
        days = calendar.monthrange(d.year, d.month)[1]
        t = d.day / days
        p = monthly_params[(d.year, d.month)]

        def linear(field: str) -> float:
            return float(prev[field] + t * (curr[field] - prev[field]))

        # Small bridge noise is exactly zero at month-end and therefore never breaks reconciliation.
        loan_noise = 0.0008 * linear("loans") * np.sin(np.pi * t) * np.sin(2 * np.pi * t + p["loan_phase"])
        dep_noise = 0.0010 * linear("deposits") * np.sin(np.pi * t) * np.sin(2 * np.pi * t + p["deposit_phase"])

        loans = linear("loans") + float(loan_noise)
        deposits = linear("deposits") + float(dep_noise)

        # February's source data already contains a large monthly deposit stress.
        # The bridge makes the stress look event-driven rather than perfectly linear.
        if d.year == 2026 and d.month == 2:
            deposits += -2_200.0 * bridge_profile(d, center_day=17, sigma=3.0)

        # Temporary August outflow that recovers before month-end; useful for anomaly detection.
        if d.year == 2026 and d.month == 8:
            deposits += -2_800.0 * bridge_profile(d, center_day=20, sigma=1.6)

        rate_bridge = np.sin(np.pi * t) * np.sin(2 * np.pi * t + p["rate_phase"])

        result[d] = {
            "loans": float(loans),
            "deposits": float(deposits),
            "ecb_rate_pct": linear("ecb_rate_pct") + float(0.015 * rate_bridge),
            "avg_loan_yield_pct": linear("avg_loan_yield_pct") + float(0.010 * rate_bridge),
            "avg_deposit_cost_pct": linear("avg_deposit_cost_pct") + float(0.008 * rate_bridge),
            "stage_2_share_pct": linear("stage_2_share_pct"),
            "stage_3_share_pct": linear("stage_3_share_pct"),
            "rwa": linear("rwa"),
            "source_month_end_date": curr_me,
        }

    calibrate_monthly_rate_paths(result, history)
    return result



def calibrate_monthly_rate_paths(
    targets: Dict[date, Dict[str, float]],
    history: Dict[date, Dict[str, float]],
) -> None:
    """
    Adjust intramonth bank-average rate paths so monthly interest income/expense
    reconcile exactly to bank_history while month-end rates remain unchanged.
    The correction uses sin(pi*t), which is zero at month-end.
    """
    months: Dict[Tuple[int, int], List[date]] = defaultdict(list)
    for d in targets:
        months[(d.year, d.month)].append(d)

    for year_month, dates in months.items():
        dates = sorted(dates)
        me = month_end(dates[0])
        source = history[me]
        days_in_month = calendar.monthrange(me.year, me.month)[1]

        source_interest_income = source["loans"] * (source["avg_loan_yield_pct"] / 100.0) / 12.0
        source_interest_expense = source["deposits"] * (source["avg_deposit_cost_pct"] / 100.0) / 12.0

        raw_income = sum(
            targets[d]["loans"] * (targets[d]["avg_loan_yield_pct"] / 100.0) / 365.0
            for d in dates
        )
        raw_expense = sum(
            targets[d]["deposits"] * (targets[d]["avg_deposit_cost_pct"] / 100.0) / 365.0
            for d in dates
        )

        income_denom = sum(
            targets[d]["loans"] * np.sin(np.pi * (d.day / days_in_month)) / 100.0 / 365.0
            for d in dates
        )
        expense_denom = sum(
            targets[d]["deposits"] * np.sin(np.pi * (d.day / days_in_month)) / 100.0 / 365.0
            for d in dates
        )

        loan_rate_adjustment_pp = (source_interest_income - raw_income) / income_denom
        deposit_rate_adjustment_pp = (source_interest_expense - raw_expense) / expense_denom

        for d in dates:
            shape = float(np.sin(np.pi * (d.day / days_in_month)))
            targets[d]["avg_loan_yield_pct"] += loan_rate_adjustment_pp * shape
            targets[d]["avg_deposit_cost_pct"] += deposit_rate_adjustment_pp * shape


def normalized_weights(raw: Dict[Tuple[str, str, str], float]) -> Dict[Tuple[str, str, str], float]:
    total = sum(raw.values())
    if total <= 0:
        raise ValueError("Allocation weights must sum to a positive number.")
    return {key: value / total for key, value in raw.items()}


def allocation_weights(
    d: date,
    balance_type: str,
) -> Dict[Tuple[str, str, str], float]:
    if balance_type == "Asset":
        country_shares = LOAN_COUNTRY_SHARES
        business_shares = LOAN_BUSINESS_SHARES
        products = LOAN_PRODUCTS
    else:
        country_shares = DEPOSIT_COUNTRY_SHARES
        business_shares = DEPOSIT_BUSINESS_SHARES
        products = DEPOSIT_PRODUCTS

    raw: Dict[Tuple[str, str, str], float] = {}

    for c_idx, country in enumerate(COUNTRIES):
        for b_idx, (business, product_map) in enumerate(products.items()):
            for p_idx, (product, product_share) in enumerate(product_map.items()):
                base = country_shares[country] * business_shares[business] * product_share
                wave = 1.0 + 0.008 * np.sin(
                    2 * np.pi * d.timetuple().tm_yday / 365.0
                    + c_idx * 0.7
                    + b_idx * 0.4
                    + p_idx * 0.3
                )
                multiplier = float(wave)

                if balance_type == "Liability":
                    # Concentrate the February and August deposit events in Corporate DE/NL.
                    if business == "Corporate" and country in {"Germany", "Netherlands"}:
                        if d.year == 2026 and d.month == 2:
                            multiplier *= 1.0 - 0.10 * max(0.0, bridge_profile(d, 17, 3.0))
                        if d.year == 2026 and d.month == 8:
                            multiplier *= 1.0 - 0.15 * max(0.0, bridge_profile(d, 20, 1.6))

                raw[(country, business, product)] = base * multiplier

    return normalized_weights(raw)


def add_credit_metrics(
    rows: List[Dict[str, object]],
    bank_stage2_pct: float,
    bank_stage3_pct: float,
    bank_rwa_m: float,
    d: date,
) -> None:
    loan_rows = [row for row in rows if row["balance_type"] == "Asset"]
    total_loans = sum(float(row["loan_balance_m"]) for row in loan_rows)

    raw_s2 = []
    raw_s3 = []
    for row in loan_rows:
        product = str(row["product"])
        country = str(row["country"])
        risk_factor = CREDIT_RISK_FACTORS[product] * COUNTRY_CREDIT_FACTORS[country]

        # Temporary credit-watch event in corporate lending during June.
        event_factor = 1.0
        if (
            d.year == 2026
            and d.month == 6
            and 12 <= d.day <= 26
            and product == "Corporate Loan"
            and country in {"France", "Germany"}
        ):
            event_factor = 1.16

        raw_s2.append(bank_stage2_pct * risk_factor * event_factor)
        raw_s3.append(bank_stage3_pct * (0.85 + 0.15 * risk_factor) * event_factor)

    weighted_s2 = sum(
        float(row["loan_balance_m"]) * value for row, value in zip(loan_rows, raw_s2)
    ) / total_loans
    weighted_s3 = sum(
        float(row["loan_balance_m"]) * value for row, value in zip(loan_rows, raw_s3)
    ) / total_loans

    s2_scale = bank_stage2_pct / weighted_s2 if weighted_s2 else 1.0
    s3_scale = bank_stage3_pct / weighted_s3 if weighted_s3 else 1.0

    raw_rwa = []
    for row, s2_raw, s3_raw in zip(loan_rows, raw_s2, raw_s3):
        s2 = s2_raw * s2_scale
        s3 = s3_raw * s3_scale
        s1 = max(0.0, 100.0 - s2 - s3)
        row["stage_1_share_pct"] = s1
        row["stage_2_share_pct"] = s2
        row["stage_3_share_pct"] = s3

        exposure = float(row["loan_balance_m"]) * 1.08
        avg_rw = 0.42 + 0.30 * (s2 / 100.0) + 0.70 * (s3 / 100.0)
        product_factor = 0.85 + 0.20 * CREDIT_RISK_FACTORS[str(row["product"])]
        raw_rwa.append(exposure * avg_rw * product_factor)

    rwa_scale = bank_rwa_m / sum(raw_rwa)
    for row, rwa_value in zip(loan_rows, raw_rwa):
        row["rwa_m"] = rwa_value * rwa_scale

    for row in rows:
        if row["balance_type"] == "Liability":
            row["stage_1_share_pct"] = None
            row["stage_2_share_pct"] = None
            row["stage_3_share_pct"] = None
            row["rwa_m"] = 0.0


def normalize_product_rates(rows: List[Dict[str, object]], target_rate: float, balance_type: str) -> None:
    relevant = [r for r in rows if r["balance_type"] == balance_type]
    balance_field = "loan_balance_m" if balance_type == "Asset" else "deposit_balance_m"
    spread_map = LOAN_RATE_SPREADS if balance_type == "Asset" else DEPOSIT_RATE_SPREADS

    raw_rates = []
    total_balance = sum(float(r[balance_field]) for r in relevant)
    for row in relevant:
        raw = (
            target_rate
            + spread_map[str(row["product"])]
            + COUNTRY_RATE_SPREADS[str(row["country"])]
        )
        raw_rates.append(raw)

    weighted = sum(
        float(row[balance_field]) * rate for row, rate in zip(relevant, raw_rates)
    ) / total_balance
    adjustment = target_rate - weighted

    for row, raw_rate in zip(relevant, raw_rates):
        row["interest_rate_pct"] = max(0.0, raw_rate + adjustment)


def anomaly_for_row(d: date, country: str, business: str, product: str) -> Tuple[int, str]:
    anomalies = []
    if (
        d.year == 2026
        and d.month == 2
        and 14 <= d.day <= 22
        and country in {"Germany", "Netherlands"}
        and business == "Corporate"
        and product in {"Corporate Current Account", "Corporate Term Deposit"}
    ):
        anomalies.append("DEPOSIT_STRESS")

    if (
        d.year == 2026
        and d.month == 8
        and 18 <= d.day <= 22
        and country in {"Germany", "Netherlands"}
        and business == "Corporate"
        and product in {"Corporate Current Account", "Corporate Term Deposit"}
    ):
        anomalies.append("TEMP_DEPOSIT_OUTFLOW")

    if (
        d.year == 2026
        and d.month == 6
        and 12 <= d.day <= 26
        and country in {"France", "Germany"}
        and product == "Corporate Loan"
    ):
        anomalies.append("CREDIT_WATCH")

    return (1 if anomalies else 0, "|".join(anomalies))


def generate_bank_daily_signals(
    bank_history_path: Path,
    output_path: Path,
    start: str = "2026-01-01",
    end: str = "2026-08-31",
    seed: int = 43,
) -> List[Dict[str, object]]:
    history = read_bank_history(bank_history_path)
    start_date = parse_date(start)
    end_date = parse_date(end)
    bank_targets = daily_bank_targets(history, start_date, end_date, seed)

    all_rows: List[Dict[str, object]] = []

    for d in daterange(start_date, end_date):
        target = bank_targets[d]
        loan_weights = allocation_weights(d, "Asset")
        deposit_weights = allocation_weights(d, "Liability")
        day_rows: List[Dict[str, object]] = []

        for (country, business, product), weight in loan_weights.items():
            loan_balance = target["loans"] * weight
            flag, anomaly = anomaly_for_row(d, country, business, product)
            day_rows.append(
                {
                    "date": d,
                    "country": country,
                    "business_line": business,
                    "product": product,
                    "balance_type": "Asset",
                    "loan_balance_m": loan_balance,
                    "deposit_balance_m": 0.0,
                    "interest_rate_pct": 0.0,
                    "ecb_rate_pct": target["ecb_rate_pct"],
                    "daily_interest_income_m": 0.0,
                    "daily_interest_expense_m": 0.0,
                    "daily_nii_m": 0.0,
                    "stage_1_share_pct": None,
                    "stage_2_share_pct": None,
                    "stage_3_share_pct": None,
                    "rwa_m": 0.0,
                    "deposit_change_1d_m": None,
                    "deposit_change_1d_pct": None,
                    "deposit_change_7d_m": None,
                    "deposit_change_7d_pct": None,
                    "deposit_change_30d_m": None,
                    "deposit_change_30d_pct": None,
                    "anomaly_flag": flag,
                    "anomaly_type": anomaly,
                    "source_month_end_date": target["source_month_end_date"],
                }
            )

        for (country, business, product), weight in deposit_weights.items():
            deposit_balance = target["deposits"] * weight
            flag, anomaly = anomaly_for_row(d, country, business, product)
            day_rows.append(
                {
                    "date": d,
                    "country": country,
                    "business_line": business,
                    "product": product,
                    "balance_type": "Liability",
                    "loan_balance_m": 0.0,
                    "deposit_balance_m": deposit_balance,
                    "interest_rate_pct": 0.0,
                    "ecb_rate_pct": target["ecb_rate_pct"],
                    "daily_interest_income_m": 0.0,
                    "daily_interest_expense_m": 0.0,
                    "daily_nii_m": 0.0,
                    "stage_1_share_pct": None,
                    "stage_2_share_pct": None,
                    "stage_3_share_pct": None,
                    "rwa_m": 0.0,
                    "deposit_change_1d_m": None,
                    "deposit_change_1d_pct": None,
                    "deposit_change_7d_m": None,
                    "deposit_change_7d_pct": None,
                    "deposit_change_30d_m": None,
                    "deposit_change_30d_pct": None,
                    "anomaly_flag": flag,
                    "anomaly_type": anomaly,
                    "source_month_end_date": target["source_month_end_date"],
                }
            )

        normalize_product_rates(day_rows, target["avg_loan_yield_pct"], "Asset")
        normalize_product_rates(day_rows, target["avg_deposit_cost_pct"], "Liability")
        add_credit_metrics(
            day_rows,
            target["stage_2_share_pct"],
            target["stage_3_share_pct"],
            target["rwa"],
            d,
        )

        for row in day_rows:
            rate = float(row["interest_rate_pct"]) / 100.0
            income = float(row["loan_balance_m"]) * rate / 365.0
            expense = float(row["deposit_balance_m"]) * rate / 365.0
            row["daily_interest_income_m"] = income
            row["daily_interest_expense_m"] = expense
            row["daily_nii_m"] = income - expense

        all_rows.extend(day_rows)

    # Deposit movements are calculated at the exact country/business/product grain.
    deposit_history: Dict[Tuple[str, str, str], Dict[date, float]] = defaultdict(dict)
    for row in all_rows:
        if row["balance_type"] == "Liability":
            key = (str(row["country"]), str(row["business_line"]), str(row["product"]))
            deposit_history[key][row["date"]] = float(row["deposit_balance_m"])

    for row in all_rows:
        if row["balance_type"] != "Liability":
            continue
        key = (str(row["country"]), str(row["business_line"]), str(row["product"]))
        d = row["date"]
        current = float(row["deposit_balance_m"])
        for lag, amount_col, pct_col in [
            (1, "deposit_change_1d_m", "deposit_change_1d_pct"),
            (7, "deposit_change_7d_m", "deposit_change_7d_pct"),
            (30, "deposit_change_30d_m", "deposit_change_30d_pct"),
        ]:
            prior = deposit_history[key].get(d - timedelta(days=lag))
            if prior is None or prior == 0:
                row[amount_col] = None
                row[pct_col] = None
            else:
                row[amount_col] = current - prior
                row[pct_col] = (current / prior - 1.0) * 100.0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for row in all_rows:
            out = {}
            for field in OUTPUT_FIELDS:
                value = row[field]
                if isinstance(value, date):
                    out[field] = value.isoformat()
                elif isinstance(value, float):
                    out[field] = f"{value:.6f}"
                elif value is None:
                    out[field] = ""
                else:
                    out[field] = value
            writer.writerow(out)

    return all_rows


def validate(
    rows: List[Dict[str, object]],
    history: Dict[date, Dict[str, float]],
) -> None:
    by_date: Dict[date, List[Dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_date[row["date"]].append(row)

    max_loan_recon = 0.0
    max_dep_recon = 0.0
    max_rwa_recon = 0.0
    max_loan_rate_error = 0.0
    max_dep_rate_error = 0.0

    for d, day_rows in by_date.items():
        loan_rows = [r for r in day_rows if r["balance_type"] == "Asset"]
        dep_rows = [r for r in day_rows if r["balance_type"] == "Liability"]
        total_loans = sum(float(r["loan_balance_m"]) for r in loan_rows)
        total_deps = sum(float(r["deposit_balance_m"]) for r in dep_rows)
        total_rwa = sum(float(r["rwa_m"]) for r in loan_rows)

        weighted_loan_rate = sum(
            float(r["loan_balance_m"]) * float(r["interest_rate_pct"]) for r in loan_rows
        ) / total_loans
        weighted_dep_rate = sum(
            float(r["deposit_balance_m"]) * float(r["interest_rate_pct"]) for r in dep_rows
        ) / total_deps

        # At month-end, exact reconciliation to bank_history is required.
        if d == month_end(d):
            source = history[d]
            max_loan_recon = max(max_loan_recon, abs(total_loans - source["loans"]))
            max_dep_recon = max(max_dep_recon, abs(total_deps - source["deposits"]))
            max_rwa_recon = max(max_rwa_recon, abs(total_rwa - source["rwa"]))
            max_loan_rate_error = max(
                max_loan_rate_error, abs(weighted_loan_rate - source["avg_loan_yield_pct"])
            )
            max_dep_rate_error = max(
                max_dep_rate_error, abs(weighted_dep_rate - source["avg_deposit_cost_pct"])
            )

    assert max_loan_recon < 1e-5, max_loan_recon
    assert max_dep_recon < 1e-5, max_dep_recon
    assert max_rwa_recon < 1e-5, max_rwa_recon
    assert max_loan_rate_error < 1e-8, max_loan_rate_error
    assert max_dep_rate_error < 1e-8, max_dep_rate_error

    negative_balances = [
        r for r in rows if float(r["loan_balance_m"]) < 0 or float(r["deposit_balance_m"]) < 0
    ]
    assert not negative_balances

    print(f"Rows: {len(rows):,}")
    print(f"Dates: {min(by_date)} to {max(by_date)} ({len(by_date)} calendar days)")
    print(f"Rows per day: {len(next(iter(by_date.values())))}")
    print(f"Max month-end loan reconciliation error: {max_loan_recon:.10f} EURm")
    print(f"Max month-end deposit reconciliation error: {max_dep_recon:.10f} EURm")
    print(f"Max month-end RWA reconciliation error: {max_rwa_recon:.10f} EURm")
    print(f"Max month-end weighted loan-rate error: {max_loan_rate_error:.12f} pp")
    print(f"Max month-end weighted deposit-rate error: {max_dep_rate_error:.12f} pp")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic daily bank signals from bank_history.csv")
    default_dir = Path(os.getenv("CFO_OUTPUT_DIR", "data"))
    parser.add_argument("--input", default=str(default_dir / "bank_history.csv"), help="Path to bank_history.csv")
    parser.add_argument("--output", default=str(default_dir / "bank_daily_signals.csv"), help="Output CSV path")
    parser.add_argument("--start", default="2026-01-01")
    parser.add_argument("--end", default="2026-08-31")
    parser.add_argument("--seed", type=int, default=43)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    rows = generate_bank_daily_signals(
        bank_history_path=input_path,
        output_path=output_path,
        start=args.start,
        end=args.end,
        seed=args.seed,
    )
    validate(rows, read_bank_history(input_path))
    print(f"Created {output_path}")
