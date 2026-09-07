from __future__ import annotations

"""
Load the generated CFO Morning Cockpit CSV files from a Unity Catalog Volume
into managed Delta tables.

Expected source folder:
    /Volumes/workspace/cfo_cockpit/raw_files/generated

Target catalog/schema:
    workspace.cfo_cockpit

The script creates/overwrites tables with a `raw_` prefix so the generated
source layer stays separate from future certified `cfo_*` views.

Run as a Databricks Python script / Workflow task.
"""

from pyspark.sql import SparkSession


SOURCE_DIR = "/Volumes/workspace/cfo_cockpit/raw_files/generated"
CATALOG = "workspace"
SCHEMA = "cfo_cockpit"

FILE_TO_TABLE = {
    "bank_history.csv": "raw_bank_history",
    "bank_daily_signals.csv": "raw_bank_daily_signals",
    "news_signals.csv": "raw_news_signals",
    "news_geo_impact.csv": "raw_news_geo_impact",
    "treasury_portfolio.csv": "raw_treasury_portfolio",
    "treasury_scenario_impacts.csv": "raw_treasury_scenario_impacts",
    "treasury_hedge_options.csv": "raw_treasury_hedge_options",
    "peer_financials.csv": "raw_peer_financials",
    "peer_positioning.csv": "raw_peer_positioning",
    "peer_benchmarks.csv": "raw_peer_benchmarks",
    "strategic_radar.csv": "raw_strategic_radar",
    "strategic_capability_map.csv": "raw_strategic_capability_map",
}


def load_raw_data(
    source_dir: str = SOURCE_DIR,
    catalog: str = CATALOG,
    schema: str = SCHEMA,
) -> None:
    spark = SparkSession.builder.getOrCreate()

    # Ensure the target schema exists.
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")

    print("=" * 72)
    print("CFO MORNING COCKPIT — LOAD RAW DATA")
    print("=" * 72)
    print(f"Source: {source_dir}")
    print(f"Target: {catalog}.{schema}")
    print()

    loaded_tables = []

    for filename, table_name in FILE_TO_TABLE.items():
        file_path = f"{source_dir}/{filename}"
        full_table_name = f"{catalog}.{schema}.{table_name}"

        print(f"Loading {filename} -> {full_table_name}")

        df = (
            spark.read
            .option("header", True)
            .option("inferSchema", True)
            .option("mode", "FAILFAST")
            .csv(file_path)
        )

        row_count = df.count()

        if row_count == 0:
            raise ValueError(f"{filename} contains zero rows.")

        (
            df.write
            .format("delta")
            .mode("overwrite")
            .option("overwriteSchema", "true")
            .saveAsTable(full_table_name)
        )

        loaded_tables.append(
            {
                "file": filename,
                "table": full_table_name,
                "rows": row_count,
                "columns": len(df.columns),
            }
        )

        print(
            f"  OK — {row_count:,} rows, "
            f"{len(df.columns)} columns"
        )

    print()
    print("-" * 72)
    print("FINAL TABLE CHECK")
    print("-" * 72)

    for item in loaded_tables:
        exists = spark.catalog.tableExists(item["table"])

        if not exists:
            raise RuntimeError(
                f"Expected Delta table was not created: {item['table']}"
            )

        print(
            f"OK   {item['table']} "
            f"({item['rows']:,} rows)"
        )

    print()
    print(
        f"Successfully loaded {len(loaded_tables)} raw Delta tables "
        f"into {catalog}.{schema}."
    )


if __name__ == "__main__":
    load_raw_data()
