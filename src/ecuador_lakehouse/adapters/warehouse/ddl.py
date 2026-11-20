"""DuckDB DDL for the raw layer, batch ledger and run ledger (S6, S13).

The raw tables mirror the canonical CSV written by the parsers: every source
column is ``VARCHAR`` (typing happens in dbt, D4) plus the three provenance
columns ``_batch_id``, ``_source_file`` and ``_source_sha256``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ecuador_lakehouse.domain.sources import SourceId

RAW_SCHEMA = "raw"
META_SCHEMA = "meta"
PROVENANCE_COLUMNS = ("_batch_id", "_source_file", "_source_sha256")


@dataclass(frozen=True, slots=True)
class RawTable:
    """One table of the raw layer: its name and source columns in CSV order."""

    name: str
    columns: tuple[str, ...]

    @property
    def all_columns(self) -> tuple[str, ...]:
        """Source columns followed by the provenance columns."""
        return (*self.columns, *PROVENANCE_COLUMNS)

    def create_sql(self) -> str:
        """Return the ``CREATE TABLE IF NOT EXISTS`` statement for this table."""
        columns = ",\n  ".join(f'"{column}" VARCHAR' for column in self.all_columns)
        return f"CREATE TABLE IF NOT EXISTS {RAW_SCHEMA}.{self.name} (\n  {columns}\n)"


RAW_TABLES: dict[SourceId, RawTable] = {
    SourceId.SRI_TAX: RawTable(
        name="sri_tax_collection",
        columns=(
            "anio",
            "mes_label",
            "grupo",
            "subgrupo",
            "impuesto",
            "tipo_contribuyente",
            "provincia",
            "canton",
            "valor_raw",
        ),
    ),
    SourceId.BCE_CNT: RawTable(
        name="bce_cnt_quarterly",
        columns=(
            "tipo_variable",
            "variable",
            "codigo",
            "descripcion",
            "unidades",
            "anio",
            "trimestre",
            "valor_raw",
        ),
    ),
    SourceId.INEC_CPI: RawTable(
        name="inec_cpi_index",
        columns=(
            "price_area",
            "nivel",
            "ponderacion_raw",
            "codigo_ccif",
            "descripcion",
            "month_label",
            "value_raw",
        ),
    ),
}

META_DDL = (
    f"""CREATE TABLE IF NOT EXISTS {META_SCHEMA}.batches (
  batch_id VARCHAR PRIMARY KEY,
  source_id VARCHAR NOT NULL,
  partition_key VARCHAR NOT NULL,
  source_sha256 VARCHAR NOT NULL,
  row_count BIGINT NOT NULL,
  status VARCHAR NOT NULL,
  mode VARCHAR NOT NULL,
  loaded_at TIMESTAMP NOT NULL,
  is_current BOOLEAN NOT NULL
)""",
    f"""CREATE TABLE IF NOT EXISTS {META_SCHEMA}.runs (
  run_id VARCHAR PRIMARY KEY,
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  status VARCHAR,
  mode VARCHAR,
  steps_json VARCHAR
)""",
    "CREATE INDEX IF NOT EXISTS idx_batches_partition "
    f"ON {META_SCHEMA}.batches (source_id, partition_key)",
    "CREATE INDEX IF NOT EXISTS idx_batches_current "
    f"ON {META_SCHEMA}.batches (source_id, partition_key, is_current)",
)


def schema_ddl() -> tuple[str, ...]:
    """Return every DDL statement needed to open a warehouse, in order."""
    return (
        f"CREATE SCHEMA IF NOT EXISTS {RAW_SCHEMA}",
        f"CREATE SCHEMA IF NOT EXISTS {META_SCHEMA}",
        *(table.create_sql() for table in RAW_TABLES.values()),
        *META_DDL,
    )
