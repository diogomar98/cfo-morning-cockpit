from pathlib import Path

import pandas as pd
import streamlit as st

DATA_DIR = Path("data")


def _read_csv_safe(filename, parse_dates=None):
    path = DATA_DIR / filename
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, parse_dates=parse_dates)
    except Exception:
        return pd.read_csv(path)


@st.cache_data
def load_bank_daily_signals():
    return _read_csv_safe("bank_daily_signals.csv", parse_dates=["date"])


@st.cache_data
def load_news_signals():
    return _read_csv_safe("news_signals.csv", parse_dates=["published_date"])


@st.cache_data
def load_news_geo_impact():
    return _read_csv_safe("news_geo_impact.csv", parse_dates=["published_date"])


@st.cache_data
def load_treasury_portfolio():
    return _read_csv_safe("treasury_portfolio.csv", parse_dates=["as_of_date", "maturity_date"])


@st.cache_data
def load_treasury_scenario_impacts():
    return _read_csv_safe("treasury_scenario_impacts.csv")


@st.cache_data
def load_treasury_hedge_options():
    return _read_csv_safe("treasury_hedge_options.csv")


@st.cache_data
def load_peer_financials():
    return _read_csv_safe("peer_financials.csv")


@st.cache_data
def load_peer_positioning():
    return _read_csv_safe("peer_positioning.csv")


@st.cache_data
def load_peer_benchmarks():
    return _read_csv_safe("peer_benchmarks.csv")


@st.cache_data
def load_strategic_radar():
    return _read_csv_safe("strategic_radar.csv")


@st.cache_data
def load_strategic_capability_map():
    return _read_csv_safe("strategic_capability_map.csv")


def datasets_available():
    filenames = [
        "bank_daily_signals.csv", "news_signals.csv", "news_geo_impact.csv",
        "treasury_portfolio.csv", "treasury_scenario_impacts.csv",
        "treasury_hedge_options.csv", "peer_financials.csv",
        "peer_positioning.csv", "peer_benchmarks.csv",
        "strategic_radar.csv", "strategic_capability_map.csv",
    ]
    return {name: (DATA_DIR / name).exists() for name in filenames}
