"""Tests for the CKAN catalogue adapter (license metadata, no API key)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from ecuador_lakehouse.adapters.sources.ckan_catalog import CkanCatalog
from ecuador_lakehouse.domain.errors import ConfigError, SourceSchemaError, SourceUnavailableError
from ecuador_lakehouse.domain.sources import LicenseInfo

FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures" / "ckan" / "package_show_recaudacion_2025.json"
)


def payload() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_package_show_returns_license_metadata() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload())

    catalog = CkanCatalog(transport=httpx.MockTransport(handler))

    info = catalog.package_show("recaudacion-de-impuestos-2025")

    assert info == LicenseInfo(
        license_id="cc-by",
        title="Creative Commons Attribution",
        url="http://www.opendefinition.org/licenses/cc-by",
    )
    assert requests[0].url.params["id"] == "recaudacion-de-impuestos-2025"
    assert requests[0].headers["User-Agent"].startswith("ecuador-open-data-lakehouse/")


def test_package_show_rejects_an_empty_dataset_id() -> None:
    catalog = CkanCatalog(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))

    with pytest.raises(ConfigError, match="dataset"):
        catalog.package_show(" ")


@pytest.mark.parametrize("dataset_id", ["../etc/passwd", "a b", "x?y=1", "a/b"])
def test_package_show_rejects_unsafe_dataset_ids(dataset_id: str) -> None:
    catalog = CkanCatalog(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))

    with pytest.raises(ConfigError, match="dataset"):
        catalog.package_show(dataset_id)


def test_a_not_found_response_raises_source_unavailable() -> None:
    catalog = CkanCatalog(
        transport=httpx.MockTransport(lambda _r: httpx.Response(404, text="missing"))
    )

    with pytest.raises(SourceUnavailableError, match="404"):
        catalog.package_show("recaudacion-de-impuestos-2025")


def test_a_transport_error_raises_source_unavailable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    catalog = CkanCatalog(transport=httpx.MockTransport(handler))

    with pytest.raises(SourceUnavailableError, match="CKAN"):
        catalog.package_show("recaudacion-de-impuestos-2025")


def test_an_unsuccessful_envelope_raises_source_schema_error() -> None:
    catalog = CkanCatalog(
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(200, json={"success": False, "error": {"message": "nope"}})
        )
    )

    with pytest.raises(SourceSchemaError, match="success"):
        catalog.package_show("recaudacion-de-impuestos-2025")


def test_a_missing_result_object_raises_source_schema_error() -> None:
    catalog = CkanCatalog(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={"success": True}))
    )

    with pytest.raises(SourceSchemaError, match="result"):
        catalog.package_show("recaudacion-de-impuestos-2025")


def test_a_result_without_a_license_raises_source_schema_error() -> None:
    body = payload()
    result = body["result"]
    assert isinstance(result, dict)
    result["license_id"] = ""

    catalog = CkanCatalog(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=body)))

    with pytest.raises(SourceSchemaError, match="license"):
        catalog.package_show("recaudacion-de-impuestos-2025")


def test_invalid_json_raises_source_schema_error() -> None:
    catalog = CkanCatalog(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, text="<html>"))
    )

    with pytest.raises(SourceSchemaError, match="JSON"):
        catalog.package_show("recaudacion-de-impuestos-2025")
