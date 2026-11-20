"""``lakehouse contract`` commands: compare the committed contract (S14)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ecuador_lakehouse.cli.guard import run_guarded
from ecuador_lakehouse.config import get_settings
from ecuador_lakehouse.container import build_contract_checker
from ecuador_lakehouse.domain.errors import ArtifactVerificationError, ConfigError

contract_app = typer.Typer(
    name="contract",
    help="Inspect and compare the published artifact contract.",
    no_args_is_help=True,
)


@contract_app.command("check")
def check(
    contract: Annotated[
        Path | None,
        typer.Option(
            "--contract", help="Contract file (default: packaged artifact_contract.json)."
        ),
    ] = None,
    warehouse: Annotated[
        Path | None,
        typer.Option(
            "--warehouse", help="Warehouse file (default: $LAKEHOUSE_HOME/warehouse.duckdb)."
        ),
    ] = None,
) -> None:
    """Compare the committed contract with the current warehouse schema."""

    def command() -> None:
        settings = get_settings()
        warehouse_path = warehouse if warehouse is not None else settings.home / "warehouse.duckdb"
        if not warehouse_path.is_file():
            raise ConfigError("no warehouse yet - run: lakehouse build")
        result = build_contract_checker(contract).execute(warehouse_path)
        if result.ok:
            typer.echo(
                f"contract {result.committed_version} matches "
                f"{len(result.current_table_names)} warehouse tables"
            )
            return
        for change in result.diff.breaking:
            typer.echo(f"breaking: {change}", err=True)
        for change in result.diff.additive:
            typer.echo(f"additive: {change}", err=True)
        required = result.diff.required_bump.upper()
        raise ArtifactVerificationError(f"contract drift requires a {required} version bump")

    run_guarded(command)


def register(app: typer.Typer) -> None:
    """Attach the ``contract`` group to the root Typer application."""
    app.add_typer(contract_app, name="contract")
