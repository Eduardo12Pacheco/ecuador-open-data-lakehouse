"""Tests for the acquire use case (partition selection + port delegation)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ecuador_lakehouse.application.ports import FetchResult
from ecuador_lakehouse.application.use_cases.acquire import AcquireSources
from ecuador_lakehouse.domain.errors import ConfigError
from ecuador_lakehouse.domain.sources import Lockfile, SourceFile, SourceId

SHA = "a" * 64


def make_source_file(partition: str, **overrides: object) -> SourceFile:
    values: dict[str, object] = {
        "source_id": SourceId.SRI_TAX,
        "partition": partition,
        "url": f"https://descargas.sri.gob.ec/download/datosAbiertos/sri_{partition}.csv",
        "filename": f"sri_{partition}.csv",
        "size_bytes": 10,
        "sha256": SHA,
    }
    values.update(overrides)
    return SourceFile(**values)  # type: ignore[arg-type]


class RecordingFetcher:
    def __init__(self) -> None:
        self.calls: list[tuple[SourceFile, bool]] = []

    def fetch(self, source_file: SourceFile, *, accept_new_vintage: bool = False) -> FetchResult:
        self.calls.append((source_file, accept_new_vintage))
        return FetchResult(
            source_file=source_file,
            path=Path("cache") / source_file.filename,
            sha256=source_file.sha256,
            size_bytes=source_file.size_bytes,
            from_cache=False,
            checksum_verified=True,
        )

    def close(self) -> None:
        pass


def make_lockfile() -> Lockfile:
    return Lockfile(
        checked_at="2026-11-19",
        files=(
            make_source_file("2024"),
            make_source_file("2025"),
            make_source_file("2026", mutable=True),
            make_source_file(
                "2024-12",
                source_id=SourceId.INEC_CPI,
                url="https://www.ecuadorencifras.gob.ec/ipc.zip",
                filename="ipc.zip",
            ),
        ),
    )


def test_acquire_fetches_every_partition_of_a_source_by_default() -> None:
    fetcher = RecordingFetcher()
    use_case = AcquireSources(fetcher=fetcher, lockfile=make_lockfile())

    results = use_case.execute(SourceId.SRI_TAX)

    assert [result.source_file.partition for result in results] == ["2024", "2025", "2026"]
    assert [call[0].partition for call in fetcher.calls] == ["2024", "2025", "2026"]


def test_acquire_honours_the_requested_partitions_in_order() -> None:
    fetcher = RecordingFetcher()
    use_case = AcquireSources(fetcher=fetcher, lockfile=make_lockfile())

    results = use_case.execute(SourceId.SRI_TAX, partitions=("2026", "2024"))

    assert [result.source_file.partition for result in results] == ["2026", "2024"]


def test_acquire_forwards_the_new_vintage_flag() -> None:
    fetcher = RecordingFetcher()
    use_case = AcquireSources(fetcher=fetcher, lockfile=make_lockfile())

    use_case.execute(SourceId.SRI_TAX, partitions=("2026",), accept_new_vintage=True)

    assert fetcher.calls == [(make_source_file("2026", mutable=True), True)]


def test_an_unknown_partition_is_a_config_error() -> None:
    use_case = AcquireSources(fetcher=RecordingFetcher(), lockfile=make_lockfile())

    with pytest.raises(ConfigError, match="1999"):
        use_case.execute(SourceId.SRI_TAX, partitions=("1999",))


def test_a_source_without_pinned_files_is_a_config_error() -> None:
    use_case = AcquireSources(
        fetcher=RecordingFetcher(),
        lockfile=Lockfile(files=(make_source_file("2024"),)),
    )

    with pytest.raises(ConfigError, match="inec_cpi"):
        use_case.execute(SourceId.INEC_CPI)


def test_empty_partition_selection_is_a_config_error() -> None:
    use_case = AcquireSources(fetcher=RecordingFetcher(), lockfile=make_lockfile())

    with pytest.raises(ConfigError, match="partition"):
        use_case.execute(SourceId.SRI_TAX, partitions=())


def test_fetcher_errors_propagate_unchanged() -> None:
    class FailingFetcher(RecordingFetcher):
        def fetch(
            self, source_file: SourceFile, *, accept_new_vintage: bool = False
        ) -> FetchResult:
            raise RuntimeError("boom")

    use_case = AcquireSources(fetcher=FailingFetcher(), lockfile=make_lockfile())

    with pytest.raises(RuntimeError, match="boom"):
        use_case.execute(SourceId.SRI_TAX)
