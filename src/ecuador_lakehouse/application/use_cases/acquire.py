"""Acquire use case: resolve pinned partitions and delegate to a fetcher."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ecuador_lakehouse.application.ports import FetchResult, SourceFetcher
from ecuador_lakehouse.domain.errors import ConfigError
from ecuador_lakehouse.domain.sources import Lockfile, SourceFile, SourceId


@dataclass(frozen=True, slots=True)
class AcquireSources:
    """Fetch every requested partition of one source through the fetcher port."""

    fetcher: SourceFetcher
    lockfile: Lockfile

    def execute(
        self,
        source_id: SourceId,
        partitions: Sequence[str] | None = None,
        *,
        accept_new_vintage: bool = False,
    ) -> list[FetchResult]:
        """Fetch ``source_id`` partitions, verifying each file's pinned checksum."""
        selected = self._resolve(source_id, partitions)
        return [
            self.fetcher.fetch(source_file, accept_new_vintage=accept_new_vintage)
            for source_file in selected
        ]

    def _resolve(self, source_id: SourceId, partitions: Sequence[str] | None) -> list[SourceFile]:
        available = [file for file in self.lockfile.files if file.source_id is source_id]
        if not available:
            raise ConfigError(
                f"no pinned files for source {source_id.value!r} in sources.lock.json"
            )
        if partitions is None:
            return available
        requested = list(partitions)
        if not requested:
            raise ConfigError("at least one partition must be selected")
        by_partition = {file.partition: file for file in available}
        selected: list[SourceFile] = []
        for partition in requested:
            source_file = by_partition.get(partition)
            if source_file is None:
                known = ", ".join(sorted(by_partition))
                raise ConfigError(
                    f"unknown partition {partition!r} for source {source_id.value!r}; "
                    f"pinned partitions: {known}"
                )
            selected.append(source_file)
        return selected
