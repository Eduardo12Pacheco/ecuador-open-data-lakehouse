"""Security tests for the safe ZIP reader (S21).

Archives are untrusted input: names may escape the destination (zip-slip),
declare absolute paths, or hide decompression bombs behind small compressed
sizes. Every case must be rejected before any bytes reach the filesystem.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from ecuador_lakehouse.adapters.sources.safe_zip import (
    ZipLimits,
    safe_extract,
    safe_extract_path,
    safe_read_member,
    validate_member,
)
from ecuador_lakehouse.domain.errors import SourceSchemaError, UnsafeArchiveError


def write_zip(path: Path, entries: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


def test_valid_archive_is_extracted_inside_the_destination(tmp_path: Path) -> None:
    archive_path = write_zip(
        tmp_path / "valid.zip",
        {"inner/data.csv": b"a,b\n1,2\n", "README.txt": b"hello\n"},
    )
    destination = tmp_path / "out"

    extracted = safe_extract_path(archive_path, destination)

    assert sorted(path.relative_to(destination).as_posix() for path in extracted) == [
        "README.txt",
        "inner/data.csv",
    ]
    assert (destination / "inner" / "data.csv").read_bytes() == b"a,b\n1,2\n"


@pytest.mark.parametrize(
    "member_name",
    ["../evil.txt", "../../evil.txt", "inner/../../evil.txt", "/absolute/evil.txt", "..\\evil.txt"],
)
def test_zip_slip_and_absolute_paths_are_rejected(tmp_path: Path, member_name: str) -> None:
    archive_path = write_zip(tmp_path / "slip.zip", {member_name: b"owned"})
    destination = tmp_path / "out"

    with pytest.raises(UnsafeArchiveError, match="unsafe archive member"):
        safe_extract_path(archive_path, destination)

    assert not (tmp_path / "evil.txt").exists()
    assert not (destination / "evil.txt").exists()


def test_directories_are_created_without_returning_them(tmp_path: Path) -> None:
    archive_path = tmp_path / "dirs.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("nested/", b"")
        archive.writestr("nested/file.txt", b"ok")

    extracted = safe_extract_path(archive_path, tmp_path / "out")

    assert [path.name for path in extracted] == ["file.txt"]


def test_member_larger_than_the_per_file_cap_is_rejected(tmp_path: Path) -> None:
    archive_path = write_zip(tmp_path / "big.zip", {"big.bin": b"x" * 2000})
    limits = ZipLimits(max_member_bytes=1000, max_total_bytes=10_000)

    with pytest.raises(UnsafeArchiveError, match="per-member"):
        safe_extract_path(archive_path, tmp_path / "out", limits=limits)


def test_total_uncompressed_size_cap_is_rejected(tmp_path: Path) -> None:
    archive_path = write_zip(
        tmp_path / "total.zip",
        {"one.bin": b"x" * 800, "two.bin": b"y" * 800},
    )
    limits = ZipLimits(max_member_bytes=10_000, max_total_bytes=1000)

    with pytest.raises(UnsafeArchiveError, match="total uncompressed"):
        safe_extract_path(archive_path, tmp_path / "out", limits=limits)


def test_compression_ratio_cap_rejects_a_bomb(tmp_path: Path) -> None:
    archive_path = write_zip(tmp_path / "bomb.zip", {"bomb.bin": b"\0" * 200_000})
    limits = ZipLimits(
        max_member_bytes=10_000_000,
        max_total_bytes=10_000_000,
        max_compression_ratio=50.0,
    )

    with pytest.raises(UnsafeArchiveError, match="compression ratio"):
        safe_extract_path(archive_path, tmp_path / "out", limits=limits)


def test_symlink_members_are_rejected(tmp_path: Path) -> None:
    archive_path = tmp_path / "symlink.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        info = zipfile.ZipInfo("link")
        info.external_attr = (0o120777 & 0xFFFF) << 16
        archive.writestr(info, "/etc/passwd")

    with pytest.raises(UnsafeArchiveError, match="symlink"):
        safe_extract_path(archive_path, tmp_path / "out")


def test_safe_read_member_checks_the_limits(tmp_path: Path) -> None:
    archive_path = write_zip(tmp_path / "read.zip", {"data.csv": b"a,b\n1,2\n"})
    limits = ZipLimits(max_member_bytes=1000, max_total_bytes=1000)

    with zipfile.ZipFile(archive_path) as archive:
        info = archive.getinfo("data.csv")
        assert safe_read_member(archive, info, limits=limits) == b"a,b\n1,2\n"

        with pytest.raises(UnsafeArchiveError, match="per-member"):
            safe_read_member(archive, info, limits=ZipLimits(max_member_bytes=2))


def test_validate_member_accepts_a_regular_relative_entry(tmp_path: Path) -> None:
    archive_path = write_zip(tmp_path / "ok.zip", {"a/b.txt": b"ok"})

    with zipfile.ZipFile(archive_path) as archive:
        validate_member(archive.getinfo("a/b.txt"))


def test_safe_extract_accepts_an_open_archive(tmp_path: Path) -> None:
    archive_path = write_zip(tmp_path / "open.zip", {"a.txt": b"ok"})

    with zipfile.ZipFile(archive_path) as archive:
        extracted = safe_extract(archive, tmp_path / "out")

    assert [path.name for path in extracted] == ["a.txt"]


def test_unsafe_archive_error_keeps_the_source_schema_exit_code() -> None:
    error = UnsafeArchiveError("unsafe")

    assert isinstance(error, SourceSchemaError)
    assert error.exit_code == 4
