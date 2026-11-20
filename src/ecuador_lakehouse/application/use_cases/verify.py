"""Verify-artifact use case (S14).

Verification is pure policy delegation: the ``ArtifactStore`` adapter knows the
file formats, this use case exposes the operation to the CLI and pipeline.
"""

from __future__ import annotations

from pathlib import Path

from ecuador_lakehouse.application.ports import ArtifactStore, VerifyResult


class VerifyArtifact:
    """Re-check every integrity guarantee of a published artifact."""

    def __init__(self, *, store: ArtifactStore) -> None:
        self._store = store

    def execute(self, artifact_dir: Path) -> VerifyResult:
        """Verify ``artifact_dir`` and return its version and table count."""
        return self._store.verify(Path(artifact_dir))
