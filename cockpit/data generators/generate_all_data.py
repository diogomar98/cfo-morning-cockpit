from __future__ import annotations

"""
Generate the complete CFO Morning Cockpit prototype dataset.

Put this file in the same folder as the six generator modules:

    generate_bank_history.py
    generate_bank_daily_signals.py
    generate_news_signals.py
    generate_treasury_portfolio.py
    generate_peer_financials.py
    generate_strategic_radar.py

Run:

    python generate_all_data.py

By default, all CSV outputs are written to ./data.

Generation order:
    bank_history
        ├──> bank_daily_signals
        │       └──> news_signals + news_geo_impact
        └──> treasury_portfolio + scenario impacts + hedge options

    peer datasets          independent
    strategic radar        independent
"""

from pathlib import Path
import argparse
import os
import sys

# Make sibling generator files importable without tying the code to one user/workspace.
# When imported/run as a normal Python file, __file__ resolves the repository folder.
# CFO_GENERATOR_DIR is only needed for unusual execution wrappers where __file__ is absent.
try:
    SCRIPT_DIR = Path(__file__).resolve().parent
except NameError:
    SCRIPT_DIR = Path(os.getenv("CFO_GENERATOR_DIR", Path.cwd())).resolve()

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

DEFAULT_OUTPUT_DIR = os.getenv("CFO_OUTPUT_DIR", "/Volumes/frbg3as_studio_a/cfo_cockpit/raw_files/generated")

from generate_bank_history import generate_bank_history
from generate_bank_daily_signals import (
    generate_bank_daily_signals,
    read_bank_history,
    validate as validate_daily_signals,
)
from generate_news_signals import generate_news_datasets
from generate_treasury_portfolio import generate_treasury_datasets
from generate_peer_financials import generate_peer_datasets
from generate_strategic_radar import generate_strategic_radar


EXPECTED_OUTPUTS = [
    "bank_history.csv",
    "bank_daily_signals.csv",
    "news_signals.csv",
    "news_geo_impact.csv",
    "treasury_portfolio.csv",
    "treasury_scenario_impacts.csv",
    "treasury_hedge_options.csv",
    "peer_financials.csv",
    "peer_positioning.csv",
    "peer_benchmarks.csv",
    "strategic_radar.csv",
    "strategic_capability_map.csv",
]


def generate_all(
    output_dir: str = "data",
    history_months: int = 48,
    history_seed: int = 42,
    daily_start: str = "2026-01-01",
    daily_end: str = "2026-08-31",
    daily_seed: int = 43,
    treasury_seed: int = 73,
    treasury_positions: int = 52,
    run_validation: bool = True,
) -> dict:
    """
    Generate every CSV required by the CFO Morning Cockpit prototype.

    Returns a dictionary containing the generated in-memory datasets.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("CFO MORNING COCKPIT — GENERATE ALL DATA")
    print("=" * 72)

    # ------------------------------------------------------------------
    # 1. Core monthly bank history
    # ------------------------------------------------------------------
    print("\n[1/6] Generating bank_history.csv ...")
    bank_history = generate_bank_history(
        months=history_months,
        seed=history_seed,
    )
    bank_history_path = out / "bank_history.csv"
    bank_history.to_csv(bank_history_path)
    print(f"      Created {bank_history_path} ({len(bank_history):,} rows)")

    # ------------------------------------------------------------------
    # 2. Daily granular bank signals
    # ------------------------------------------------------------------
    print("\n[2/6] Generating bank_daily_signals.csv ...")
    daily_path = out / "bank_daily_signals.csv"

    daily_rows = generate_bank_daily_signals(
        bank_history_path=bank_history_path,
        output_path=daily_path,
        start=daily_start,
        end=daily_end,
        seed=daily_seed,
    )

    if run_validation:
        print("      Validating daily/month-end reconciliation ...")
        validate_daily_signals(
            daily_rows,
            read_bank_history(bank_history_path),
        )

    print(f"      Created {daily_path} ({len(daily_rows):,} rows)")

    # ------------------------------------------------------------------
    # 3. External news + geographic impact
    # ------------------------------------------------------------------
    print("\n[3/6] Generating news intelligence datasets ...")
    news, news_geo = generate_news_datasets(
        bank_daily_path=str(daily_path),
        output_dir=str(out),
    )
    print(f"      Created {out / 'news_signals.csv'} ({len(news):,} rows)")
    print(f"      Created {out / 'news_geo_impact.csv'} ({len(news_geo):,} rows)")

    # ------------------------------------------------------------------
    # 4. Treasury portfolio, scenarios and hedge options
    # ------------------------------------------------------------------
    print("\n[4/6] Generating treasury datasets ...")
    treasury, treasury_scenarios, treasury_hedges = generate_treasury_datasets(
        bank_history_path=str(bank_history_path),
        output_dir=str(out),
        seed=treasury_seed,
        n_positions=treasury_positions,
    )
    print(f"      Created {out / 'treasury_portfolio.csv'} ({len(treasury):,} rows)")
    print(
        f"      Created {out / 'treasury_scenario_impacts.csv'} "
        f"({len(treasury_scenarios):,} rows)"
    )
    print(
        f"      Created {out / 'treasury_hedge_options.csv'} "
        f"({len(treasury_hedges):,} rows)"
    )

    # ------------------------------------------------------------------
    # 5. Real public peer benchmarking
    # ------------------------------------------------------------------
    print("\n[5/6] Generating peer benchmarking datasets ...")
    peers, peer_positioning, peer_benchmarks = generate_peer_datasets(
        output_dir=str(out)
    )
    print(f"      Created {out / 'peer_financials.csv'} ({len(peers):,} rows)")
    print(
        f"      Created {out / 'peer_positioning.csv'} "
        f"({len(peer_positioning):,} rows)"
    )
    print(
        f"      Created {out / 'peer_benchmarks.csv'} "
        f"({len(peer_benchmarks):,} rows)"
    )

    # ------------------------------------------------------------------
    # 6. Strategic / M&A radar
    # ------------------------------------------------------------------
    print("\n[6/6] Generating strategic radar datasets ...")
    strategic_radar, capability_map = generate_strategic_radar(
        output_dir=str(out)
    )
    print(
        f"      Created {out / 'strategic_radar.csv'} "
        f"({len(strategic_radar):,} rows)"
    )
    print(
        f"      Created {out / 'strategic_capability_map.csv'} "
        f"({len(capability_map):,} rows)"
    )

    # ------------------------------------------------------------------
    # Final integrity check
    # ------------------------------------------------------------------
    print("\n" + "-" * 72)
    print("FINAL FILE CHECK")
    print("-" * 72)

    missing = []
    for filename in EXPECTED_OUTPUTS:
        path = out / filename
        if path.exists():
            print(f"OK   {filename}")
        else:
            print(f"MISS {filename}")
            missing.append(filename)

    if missing:
        raise RuntimeError(
            "Generation finished but expected files are missing: "
            + ", ".join(missing)
        )

    print("\nAll CFO Morning Cockpit datasets generated successfully.")
    print(f"Output folder: {out.resolve()}")

    return {
        "bank_history": bank_history,
        "bank_daily_signals": daily_rows,
        "news_signals": news,
        "news_geo_impact": news_geo,
        "treasury_portfolio": treasury,
        "treasury_scenario_impacts": treasury_scenarios,
        "treasury_hedge_options": treasury_hedges,
        "peer_financials": peers,
        "peer_positioning": peer_positioning,
        "peer_benchmarks": peer_benchmarks,
        "strategic_radar": strategic_radar,
        "strategic_capability_map": capability_map,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate all CFO Morning Cockpit prototype datasets."
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=(
            "Folder in which all CSV files will be written. "
            "Defaults to CFO_OUTPUT_DIR when set, otherwise ./data."
        ),
    )
    parser.add_argument("--history-months", type=int, default=48)
    parser.add_argument("--history-seed", type=int, default=42)
    parser.add_argument("--daily-start", default="2026-01-01")
    parser.add_argument("--daily-end", default="2026-08-31")
    parser.add_argument("--daily-seed", type=int, default=43)
    parser.add_argument("--treasury-seed", type=int, default=73)
    parser.add_argument("--treasury-positions", type=int, default=52)
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip the detailed bank_daily_signals reconciliation validation.",
    )
    # Databricks interactive Python-file sessions inject IPython/kernel arguments
    # (for example: -f <connection.json>). Ignore those platform arguments
    # while still honoring the CFO pipeline arguments defined above.
    args, _unknown = parser.parse_known_args()
    return args


if __name__ == "__main__":
    args = parse_args()

    generate_all(
        output_dir=args.output_dir,
        history_months=args.history_months,
        history_seed=args.history_seed,
        daily_start=args.daily_start,
        daily_end=args.daily_end,
        daily_seed=args.daily_seed,
        treasury_seed=args.treasury_seed,
        treasury_positions=args.treasury_positions,
        run_validation=not args.skip_validation,
    )
