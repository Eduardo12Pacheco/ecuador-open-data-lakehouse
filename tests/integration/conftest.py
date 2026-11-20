"""Session fixtures for the dbt integration suite.

Building the staging layer is the slowest part of T7's tests, so one sample
warehouse is loaded and transformed once per test session. The dbt project is
copied into the temporary home by ``DbtTransformer`` exactly as it happens in
production, which also proves that no run artefact is written to the repo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from ecuador_lakehouse.adapters.transform.dbt_runner import DbtTransformer
from ecuador_lakehouse.adapters.warehouse.duckdb_warehouse import DuckDbWarehouse
from tests.conftest import CanonicalSample


@dataclass(frozen=True, slots=True)
class StagingBuild:
    """A sample warehouse with the seed + staging layer already materialized."""

    home: Path
    warehouse_path: Path
    transformer: DbtTransformer


@pytest.fixture(scope="session")
def staging_build(
    tmp_path_factory: pytest.TempPathFactory,
    canonical_sample: tuple[CanonicalSample, ...],
) -> StagingBuild:
    """Load the full bundled sample, then run dbt seed + staging once."""
    home = tmp_path_factory.mktemp("dbt-staging-home")
    warehouse_path = home / "warehouse.duckdb"
    warehouse = DuckDbWarehouse(warehouse_path)
    try:
        for sample in canonical_sample:
            warehouse.load_partition(
                sample.source_id,
                sample.partition,
                sample.path,
                sample.sha256,
                sample.source_file,
            )
    finally:
        warehouse.close()

    transformer = DbtTransformer(
        warehouse_path=warehouse_path,
        home=home,
        threads=4,
    )
    transformer.seed_and_run(select="staging")
    return StagingBuild(home=home, warehouse_path=warehouse_path, transformer=transformer)
