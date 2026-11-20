"""Tests for the mutable-vintage ledger (S4).

The current-year SRI checksum changes upstream every month. The ledger records
an explicitly accepted checksum locally so later fetches can verify against it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ecuador_lakehouse.adapters.sources.vintage import VintageLedger
from ecuador_lakehouse.domain.errors import ConfigError
from ecuador_lakehouse.domain.sources import SourceFile, SourceId

BODY = b"ANIO|MES|VALOR\n2026|01 Enero|83,31\n"
SHA = hashlib.sha256(BODY).hexdigest()


def make_source_file(**overrides: object) -> SourceFile:
    values: dict[str, object] = {
        "source_id": SourceId.SRI_TAX,
        "partition": "2026",
        "url": "https://descargas.sri.gob.ec/download/datosAbiertos/sri_recaudacion_2026.csv",
        "filename": "sri_recaudacion_2026.csv",
        "size_bytes": len(BODY),
        "sha256": "0" * 64,
        "mutable": True,
        "encoding_hint": "cp1252",
    }
    values.update(overrides)
    return SourceFile(**values)  # type: ignore[arg-type]


def ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "home" / "cache" / "sri_tax" / "vintages.json"


def test_the_ledger_records_and_reads_an_accepted_checksum(tmp_path: Path) -> None:
    ledger = VintageLedger(tmp_path / "home" / "cache")
    source_file = make_source_file()

    ledger.record(source_file, SHA, len(BODY))

    assert ledger.accepted_sha(source_file) == SHA
    payload = json.loads(ledger_path(tmp_path).read_text(encoding="utf-8"))
    assert payload["2026"] == {
        "accepted": True,
        "pinned_sha256": "0" * 64,
        "sha256": SHA,
        "size_bytes": len(BODY),
    }


def test_the_ledger_returns_none_for_an_unknown_partition(tmp_path: Path) -> None:
    ledger = VintageLedger(tmp_path / "home" / "cache")

    assert ledger.accepted_sha(make_source_file()) is None


def test_an_invalid_ledger_is_reported(tmp_path: Path) -> None:
    path = ledger_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    ledger = VintageLedger(tmp_path / "home" / "cache")

    with pytest.raises(ConfigError, match="vintage"):
        ledger.accepted_sha(make_source_file())
