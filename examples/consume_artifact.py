"""Consume a published Ecuador lakehouse artifact with only DuckDB.

Usage:
    python examples/consume_artifact.py <artifact-dir>

The script deliberately imports nothing from ``ecuador_lakehouse``: a sibling
project only needs the DuckDB file (or the per-table Parquet files) and the
manifest. It prints the top five tax groups of the latest published year (with the
number of months loaded, since the current year is partial) and the latest complete
SRI/GDP ratio.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

_DATABASE_NAME = "ecuador_lakehouse.duckdb"
_EXPECTED_ARGS = 2


def main(argv: list[str]) -> int:
    if len(argv) != _EXPECTED_ARGS:
        sys.stdout.write("usage: consume_artifact.py <artifact-dir>\n")
        return 2
    artifact_dir = Path(argv[1])
    database = artifact_dir / _DATABASE_NAME
    if not database.is_file():
        sys.stderr.write(f"artifact database not found: {database}\n")
        return 2
    with duckdb.connect(str(database), read_only=True) as connection:
        latest_year = connection.execute(
            "SELECT max(period_year) FROM marts.mart_tax_collection_monthly"
        ).fetchone()
        if latest_year is None or latest_year[0] is None:
            sys.stdout.write("artifact contains no tax collection rows\n")
            return 0
        year = int(latest_year[0])
        groups = connection.execute(
            "SELECT tax_group_name, sum(nominal_usd) AS total "
            "FROM marts.mart_tax_collection_monthly WHERE period_year = ? "
            "GROUP BY tax_group_name ORDER BY total DESC LIMIT 5",
            [year],
        ).fetchall()
        months = connection.execute(
            "SELECT count(DISTINCT period_date) FROM marts.mart_tax_collection_monthly "
            "WHERE period_year = ?",
            [year],
        ).fetchone()
        ratio = connection.execute(
            "SELECT period_year, ratio FROM marts.mart_tax_to_gdp_annual "
            "WHERE is_complete ORDER BY period_year DESC LIMIT 1"
        ).fetchone()

    months_loaded = int(months[0]) if months is not None else 0
    sys.stdout.write(f"Latest tax year: {year} ({months_loaded} of 12 months loaded)\n")
    for rank, (name, total) in enumerate(groups, start=1):
        sys.stdout.write(f"  {rank}. {name}: USD {float(total):,.2f}\n")
    if ratio is not None:
        sys.stdout.write(f"SRI/GDP {int(ratio[0])}: {float(ratio[1]):.4f}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
