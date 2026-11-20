"""CKAN catalogue adapter used to record dataset license metadata (S4)."""

from __future__ import annotations

import re
from typing import Any

import httpx

from ecuador_lakehouse import __version__
from ecuador_lakehouse.domain.errors import ConfigError, SourceSchemaError, SourceUnavailableError
from ecuador_lakehouse.domain.sources import LicenseInfo

_DATASET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_HTTP_OK = 200
_USER_AGENT = f"ecuador-open-data-lakehouse/{__version__}"


class CkanCatalog:
    """Read ``package_show`` metadata from the Ecuadorian open-data CKAN API."""

    def __init__(
        self,
        base_url: str = "https://www.datosabiertos.gob.ec/api/3/action",
        *,
        timeout_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            transport=transport,
            timeout=httpx.Timeout(timeout_s),
            follow_redirects=False,
            headers={"User-Agent": _USER_AGENT},
        )
        self._base_url = base_url.rstrip("/")

    def package_show(self, dataset_id: str) -> LicenseInfo:
        """Return the license metadata CKAN records for ``dataset_id``."""
        if not _DATASET_ID.fullmatch(dataset_id):
            raise ConfigError(f"invalid CKAN dataset id: {dataset_id!r}")
        url = f"{self._base_url}/package_show"
        try:
            response = self._client.get(url, params={"id": dataset_id})
        except httpx.TransportError as exc:
            raise SourceUnavailableError(f"CKAN request failed for {dataset_id!r}: {exc}") from exc
        if response.status_code != _HTTP_OK:
            raise SourceUnavailableError(
                f"CKAN package_show returned HTTP {response.status_code} for {dataset_id!r}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SourceSchemaError("CKAN response is not valid JSON") from exc
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise SourceSchemaError("CKAN response did not report success: true")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise SourceSchemaError("CKAN response has no result object")

        license_id = _string_field(result, "license_id")
        if not license_id:
            raise SourceSchemaError(f"CKAN dataset {dataset_id!r} has no license_id")
        return LicenseInfo(
            license_id=license_id,
            title=_string_field(result, "license_title"),
            url=_string_field(result, "license_url"),
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()


def _string_field(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    return value.strip() if isinstance(value, str) else ""
