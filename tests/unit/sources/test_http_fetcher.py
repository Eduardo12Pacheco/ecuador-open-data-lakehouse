"""Checksum, cache and lifecycle tests for the HTTP source fetcher (S4)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from ecuador_lakehouse.adapters.sources.http_fetcher import (
    DEFAULT_ALLOWED_HOSTS,
    HttpSourceFetcher,
)
from ecuador_lakehouse.domain.errors import ChecksumMismatchError, ConfigError
from ecuador_lakehouse.domain.sources import SourceFile, SourceId

BODY = b"ANIO|MES|VALOR\n2024|01 Enero|83,31\n"
SHA = hashlib.sha256(BODY).hexdigest()
URL = "https://descargas.sri.gob.ec/download/datosAbiertos/sri_recaudacion_2024.csv"


def make_source_file(**overrides: object) -> SourceFile:
    values: dict[str, object] = {
        "source_id": SourceId.SRI_TAX,
        "partition": "2024",
        "url": URL,
        "filename": "sri_recaudacion_2024.csv",
        "size_bytes": len(BODY),
        "sha256": SHA,
        "mutable": False,
        "encoding_hint": "utf-8",
    }
    values.update(overrides)
    return SourceFile(**values)  # type: ignore[arg-type]


def make_fetcher(
    tmp_path: Path,
    handler: Callable[[httpx.Request], httpx.Response],
    **kwargs: object,
) -> HttpSourceFetcher:
    return HttpSourceFetcher(
        tmp_path / "home",
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
        **kwargs,  # type: ignore[arg-type]
    )


def test_fetch_downloads_verifies_and_reuses_the_cache(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=BODY, headers={"Content-Length": str(len(BODY))})

    fetcher = make_fetcher(tmp_path, handler)
    source_file = make_source_file()

    first = fetcher.fetch(source_file)
    second = fetcher.fetch(source_file)

    assert first.path.read_bytes() == BODY
    assert first.sha256 == SHA
    assert first.size_bytes == len(BODY)
    assert first.from_cache is False
    assert first.checksum_verified is True
    assert second.from_cache is True
    assert len(requests) == 1
    assert requests[0].headers["User-Agent"].startswith("ecuador-open-data-lakehouse/")


def test_an_immutable_checksum_mismatch_raises_exit_code_three(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"different bytes")

    with pytest.raises(ChecksumMismatchError, match="checksum") as excinfo:
        make_fetcher(tmp_path, handler).fetch(make_source_file())

    assert excinfo.value.exit_code == 3


def test_a_cached_file_with_a_stale_immutable_checksum_is_downloaded_again(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "home" / "cache" / "sri_tax"
    cache_dir.mkdir(parents=True)
    (cache_dir / "sri_recaudacion_2024.csv").write_bytes(b"stale")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=BODY)

    result = make_fetcher(tmp_path, handler).fetch(make_source_file())

    assert result.path.read_bytes() == BODY
    assert result.from_cache is False


def test_mutable_new_vintage_warns_without_recording_it(tmp_path: Path, capsys) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=BODY)

    source_file = make_source_file(mutable=True, sha256="0" * 64)
    fetcher = make_fetcher(tmp_path, handler)

    result = fetcher.fetch(source_file, accept_new_vintage=False)

    captured = capsys.readouterr()
    assert "mutable" in (captured.out + captured.err)
    assert result.checksum_verified is False
    assert result.new_vintage is False
    assert not (tmp_path / "home" / "cache" / "sri_tax" / "vintages.json").exists()


def test_accept_new_vintage_records_the_new_checksum(tmp_path: Path) -> None:
    fetcher = make_fetcher(tmp_path, lambda _request: httpx.Response(200, content=BODY))
    source_file = make_source_file(
        partition="2026",
        filename="sri_recaudacion_2026.csv",
        mutable=True,
        sha256="0" * 64,
    )

    result = fetcher.fetch(source_file, accept_new_vintage=True)

    assert result.checksum_verified is True
    assert result.new_vintage is True
    payload = json.loads(
        (tmp_path / "home" / "cache" / "sri_tax" / "vintages.json").read_text(encoding="utf-8")
    )
    assert payload["2026"]["sha256"] == SHA


def test_an_accepted_mutable_vintage_is_verified_on_the_next_fetch(tmp_path: Path) -> None:
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(len(calls) + 1)
        return httpx.Response(200, content=BODY)

    fetcher = make_fetcher(tmp_path, handler)
    source_file = make_source_file(
        partition="2026",
        filename="sri_recaudacion_2026.csv",
        mutable=True,
        sha256="0" * 64,
    )
    fetcher.fetch(source_file, accept_new_vintage=True)

    cached = fetcher.fetch(source_file)

    assert cached.from_cache is True
    assert cached.checksum_verified is True
    assert len(calls) == 1


def test_an_invalid_ledger_blocks_a_mutable_fetch(tmp_path: Path) -> None:
    cache_dir = tmp_path / "home" / "cache" / "sri_tax"
    cache_dir.mkdir(parents=True)
    (cache_dir / "vintages.json").write_text("{not json", encoding="utf-8")
    (cache_dir / "sri_recaudacion_2026.csv").write_bytes(BODY)

    with pytest.raises(ConfigError, match="vintage"):
        make_fetcher(tmp_path, lambda _request: httpx.Response(200, content=BODY)).fetch(
            make_source_file(
                partition="2026",
                filename="sri_recaudacion_2026.csv",
                mutable=True,
                sha256="0" * 64,
            )
        )


def test_close_releases_the_http_client(tmp_path: Path) -> None:
    fetcher = make_fetcher(tmp_path, lambda _request: httpx.Response(200, content=BODY))

    fetcher.close()

    assert fetcher._client.is_closed


def test_default_allow_list_contains_the_documented_hosts() -> None:
    assert (
        frozenset(
            {
                "descargas.sri.gob.ec",
                "www.ecuadorencifras.gob.ec",
                "www.datosabiertos.gob.ec",
                "datosabiertos.gob.ec",
            }
        )
        == DEFAULT_ALLOWED_HOSTS
    )
