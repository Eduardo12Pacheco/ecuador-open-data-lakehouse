"""Optional reachability probe used by ``lakehouse doctor --network`` (S1, S4)."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from ecuador_lakehouse import __version__

DEFAULT_HOSTS = (
    "descargas.sri.gob.ec",
    "www.ecuadorencifras.gob.ec",
    "www.datosabiertos.gob.ec",
)
_MAX_TIMEOUT_S = 60.0


@dataclass(frozen=True, slots=True)
class HostProbe:
    """Reachability outcome for one allow-listed host."""

    host: str
    ok: bool
    detail: str


def user_agent() -> str:
    """Return the honest User-Agent shared by the HTTP adapters (D21)."""
    return f"ecuador-open-data-lakehouse/{__version__}"


def probe_hosts(
    hosts: tuple[str, ...] = DEFAULT_HOSTS,
    *,
    timeout_s: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> tuple[HostProbe, ...]:
    """Send one HEAD request per host and report whether it answered."""
    if timeout_s <= 0 or timeout_s > _MAX_TIMEOUT_S:
        raise ValueError(f"timeout_s must be in (0, {_MAX_TIMEOUT_S}]: {timeout_s!r}")
    probes: list[HostProbe] = []
    headers = {"User-Agent": user_agent()}
    with httpx.Client(
        timeout=timeout_s,
        follow_redirects=False,
        headers=headers,
        transport=transport,
    ) as client:
        for host in hosts:
            try:
                response = client.head(f"https://{host}/")
            except httpx.HTTPError as error:
                probes.append(HostProbe(host=host, ok=False, detail=type(error).__name__))
                continue
            ok = response.status_code < httpx.codes.INTERNAL_SERVER_ERROR
            detail = f"HTTP {response.status_code}"
            probes.append(
                HostProbe(
                    host=host,
                    ok=ok,
                    detail=detail if ok else f"{detail} (server error)",
                )
            )
    return tuple(probes)
