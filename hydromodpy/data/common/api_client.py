"""HTTP helpers for API adapters (JSON GET, pagination).

Exposes JSON request idioms with a caller-provided HTTPClient.
Only HTTP 404 returns None; all other HTTP >= 400 errors and network failures
raise DataSourceError so errors are never mistaken for empty observations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hydromodpy.core.exceptions import DataSourceError, NetworkError
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.core.io.fetch import HTTPClient

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 60
MAX_RETRIES = 3


def get_json(
    client: HTTPClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: int | float = DEFAULT_TIMEOUT,
    retries: int = MAX_RETRIES,
) -> dict | None:
    """GET a JSON payload using the given client.

    Returns the parsed JSON dict, or ``None`` on HTTP 404 only. Any other
    failure (HTTP >= 400 or network failure) raises :class:`DataSourceError`.
    """
    try:
        return client.get_json(url, params=params, timeout=timeout)
    except NetworkError as exc:
        # NetworkError keeps its context in exc.context; the status is there,
        # not on the attribute.
        if exc.context.get("status_code") == 404:
            return None
        raise DataSourceError(f"HTTP GET {url} failed: {exc}", url=url) from exc
    except DataSourceError as exc:
        if exc.context.get("status_code") == 404:
            return None
        raise
    except Exception as exc:
        exc_context = getattr(exc, "context", None)
        status = None
        if isinstance(exc_context, dict):
            status = exc_context.get("status_code")
        if status is None:
            status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 404:
            return None
        raise DataSourceError(f"HTTP GET {url} failed: {exc}", url=url) from exc


def paginate_json(
    client: HTTPClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    page_size: int = 1000,
    data_key: str = "data",
    count_key: str = "count",
    timeout: int | float = DEFAULT_TIMEOUT,
) -> list[dict]:
    """Iterate a paginated JSON API endpoint and collect all records."""
    params = dict(params or {})
    params["size"] = page_size
    params["page"] = 1

    all_records: list[dict] = []
    max_pages = 1

    while params["page"] <= max_pages:
        payload = get_json(client, url, params=params, timeout=timeout, retries=MAX_RETRIES)
        if payload is None:
            break

        records = payload.get(data_key, [])
        all_records.extend(records)

        if params["page"] == 1:
            total = payload.get(count_key, len(records))
            max_pages = max(1, -(-total // page_size))

        params["page"] += 1

    return all_records


__all__ = [
    "DEFAULT_TIMEOUT",
    "MAX_RETRIES",
    "get_json",
    "paginate_json",
]
