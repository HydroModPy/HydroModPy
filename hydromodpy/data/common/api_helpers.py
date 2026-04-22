"""HTTP helpers for API adapters (retry, pagination, status check).

Thin wrappers over :class:`hydromodpy.core.io.http_client.HTTPClient` so
legacy callers that import ``check_status`` / ``get_json`` /
``paginate_json`` keep working through the unified client.
"""

from __future__ import annotations

from typing import Any

from hydromodpy.core.exceptions import NetworkError
from hydromodpy.core.io.http_client import get_default_client
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 60
MAX_RETRIES = 3

STATUS_MESSAGES: dict[int, str] = {
    200: "Success",
    206: "Partial content",
    400: "Bad request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not found",
    500: "Internal server error",
}


def check_status(status_code: int) -> bool:
    """True for 200/206, logs diagnostic otherwise."""
    if status_code in (200, 206):
        return True
    msg = STATUS_MESSAGES.get(status_code, f"Unknown HTTP {status_code}")
    logger.warning("HTTP %d: %s", status_code, msg)
    return False


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = MAX_RETRIES,
) -> dict | None:
    """GET with retry + backoff via the unified HTTPClient.

    Returns the parsed JSON payload, or ``None`` if the server responded
    with a non-recoverable error (e.g. 404) or the client exhausted its
    retries.
    """
    client = get_default_client()
    try:
        return client.get_json(url, params=params, timeout=timeout)
    except NetworkError as exc:
        logger.error("get_json failed for %s: %s", url, exc)
        return None


def paginate_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    page_size: int = 1000,
    data_key: str = "data",
    count_key: str = "count",
    timeout: int = DEFAULT_TIMEOUT,
) -> list[dict]:
    """Iterate paginated JSON API and collect all records."""
    params = dict(params or {})
    params["size"] = page_size
    params["page"] = 1

    all_records: list[dict] = []
    max_pages = 1

    while params["page"] <= max_pages:
        payload = get_json(url, params=params, timeout=timeout, retries=MAX_RETRIES)
        if payload is None:
            break

        records = payload.get(data_key, [])
        all_records.extend(records)

        if params["page"] == 1:
            total = payload.get(count_key, len(records))
            max_pages = max(1, -(-total // page_size))

        params["page"] += 1

    return all_records
