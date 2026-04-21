"""HTTP helpers for API adapters (retry, pagination, status check)."""

from __future__ import annotations

import time
from typing import Any

import requests

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 60
MAX_RETRIES = 3
BACKOFF_FACTOR = 2.0

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
    """GET with retry + backoff. Returns parsed JSON or None."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if check_status(resp.status_code):
                return resp.json()
            return None
        except requests.exceptions.RequestException as exc:
            if attempt < retries:
                wait = BACKOFF_FACTOR ** attempt
                logger.warning("Attempt %d/%d failed (%s), retry in %.0fs", attempt, retries, exc, wait)
                time.sleep(wait)
            else:
                logger.error("All %d attempts failed for %s: %s", retries, url, exc)
                return None
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
