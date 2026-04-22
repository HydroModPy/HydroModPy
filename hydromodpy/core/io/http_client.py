"""Unified HTTP client for HydroModPy data sources.

Single entry point used by every remote data provider (Hub'Eau, BRGM,
IGN, Meteo-France / GeoSAS). Features:

- persistent :class:`requests.Session`
- exponential backoff with jitter
- honors ``Retry-After`` header (seconds or HTTP-date)
- configurable default timeout
- simple per-host token bucket to cap concurrent requests
- :meth:`stream` yields chunks while computing a SHA-256 digest
- :meth:`get_json` optionally validates the payload against a Pydantic model
- pre/post request hooks for instrumentation

The client raises :class:`hydromodpy.core.exceptions.NetworkError` when the
server returns a non-recoverable status after all retry attempts, and
:class:`hydromodpy.core.exceptions.DataSourceError` for payload validation
failures.
"""

from __future__ import annotations

import contextlib
import hashlib
import random
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Iterator
from urllib.parse import urlparse

import requests

from hydromodpy.core.exceptions import DataSourceError, NetworkError
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 4
DEFAULT_BACKOFF_BASE = 0.5
DEFAULT_BACKOFF_CAP = 30.0
DEFAULT_CHUNK = 64 * 1024
DEFAULT_RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass
class StreamResult:
    """Result of :meth:`HTTPClient.stream`: final path + digest metadata."""

    sha256: str
    size: int
    status_code: int
    url: str
    headers: dict[str, str] = field(default_factory=dict)


class _TokenBucket:
    """Simple per-host semaphore used to cap concurrent in-flight requests."""

    def __init__(self, capacity: int):
        self._sem = threading.BoundedSemaphore(capacity)

    @contextlib.contextmanager
    def slot(self):
        self._sem.acquire()
        try:
            yield
        finally:
            self._sem.release()


class HTTPClient:
    """Unified HTTP client with backoff + streaming SHA-256.

    Instances are thread-safe for simple use cases (concurrent ``get_json``
    on different URLs) thanks to the shared :class:`requests.Session`
    and per-host semaphores.
    """

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        backoff_cap: float = DEFAULT_BACKOFF_CAP,
        per_host_concurrency: int = 4,
        retry_statuses: frozenset[int] = DEFAULT_RETRY_STATUSES,
        user_agent: str | None = None,
        pre_request: Callable[[str, dict[str, Any]], None] | None = None,
        post_response: Callable[[str, requests.Response | None, Exception | None], None]
        | None = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.retry_statuses = retry_statuses
        self._session = requests.Session()
        if user_agent:
            self._session.headers["User-Agent"] = user_agent
        self._per_host_capacity = per_host_concurrency
        self._host_buckets: dict[str, _TokenBucket] = defaultdict(
            lambda: _TokenBucket(per_host_concurrency)
        )
        self._buckets_lock = threading.Lock()
        self._pre_request = pre_request
        self._post_response = post_response

    # ------------------------------------------------------------------ utils
    def _bucket_for(self, url: str) -> _TokenBucket:
        host = urlparse(url).netloc
        with self._buckets_lock:
            return self._host_buckets[host]

    def _compute_backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after is not None:
            parsed = _parse_retry_after(retry_after)
            if parsed is not None:
                return min(parsed, self.backoff_cap)
        delay = min(self.backoff_cap, self.backoff_base * (2**attempt))
        return delay + random.uniform(0, delay * 0.25)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> HTTPClient:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    # ----------------------------------------------------------------- request
    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        data: Any = None,
        json: Any = None,
        timeout: float | None = None,
        stream: bool = False,
    ) -> requests.Response:
        """Issue a request with retries.

        Raises :class:`NetworkError` after the configured number of retries.
        """
        effective_timeout = timeout if timeout is not None else self.timeout
        last_exc: Exception | None = None

        with self._bucket_for(url).slot():
            for attempt in range(self.max_retries + 1):
                if self._pre_request is not None:
                    try:
                        self._pre_request(url, {"method": method, "attempt": attempt})
                    except Exception:
                        pass

                try:
                    resp = self._session.request(
                        method,
                        url,
                        params=params,
                        headers=headers,
                        data=data,
                        json=json,
                        timeout=effective_timeout,
                        stream=stream,
                    )
                except requests.RequestException as exc:
                    last_exc = exc
                    if self._post_response is not None:
                        self._post_response(url, None, exc)
                    if attempt >= self.max_retries:
                        break
                    delay = self._compute_backoff(attempt, None)
                    logger.warning(
                        "HTTP %s %s failed (%s) — retry %d/%d in %.2fs",
                        method,
                        url,
                        exc,
                        attempt + 1,
                        self.max_retries,
                        delay,
                    )
                    time.sleep(delay)
                    continue

                if self._post_response is not None:
                    self._post_response(url, resp, None)

                if resp.status_code in self.retry_statuses and attempt < self.max_retries:
                    delay = self._compute_backoff(attempt, resp.headers.get("Retry-After"))
                    logger.warning(
                        "HTTP %s %s -> %d, retry %d/%d in %.2fs",
                        method,
                        url,
                        resp.status_code,
                        attempt + 1,
                        self.max_retries,
                        delay,
                    )
                    resp.close()
                    time.sleep(delay)
                    continue

                return resp

        raise NetworkError(
            f"HTTP {method} {url} failed after {self.max_retries} retries",
            url=url,
            method=method,
            last_exception=str(last_exc) if last_exc else None,
        )

    # ---------------------------------------------------------------- helpers
    def get(self, url: str, **kw: Any) -> requests.Response:
        return self.request("GET", url, **kw)

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        model: Any | None = None,
    ) -> Any:
        """GET a JSON document; optionally validate with a Pydantic model.

        ``model`` is any callable that turns a dict into an instance (e.g. a
        ``pydantic.BaseModel`` subclass or ``TypeAdapter``).
        """
        resp = self.request(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=timeout,
        )
        if resp.status_code >= 400:
            raise NetworkError(
                f"HTTP GET {url} -> {resp.status_code}",
                url=url,
                status_code=resp.status_code,
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise DataSourceError(
                f"Response from {url} is not valid JSON: {exc}",
                url=url,
            ) from exc
        if model is None:
            return payload
        try:
            if hasattr(model, "model_validate"):
                return model.model_validate(payload)
            return model(payload)
        except Exception as exc:
            raise DataSourceError(
                f"Payload from {url} failed validation: {exc}",
                url=url,
            ) from exc

    def stream(
        self,
        url: str,
        dest,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        chunk_size: int = DEFAULT_CHUNK,
        timeout: float | None = None,
    ) -> StreamResult:
        """Stream a URL to ``dest`` (path or writable binary object).

        Returns :class:`StreamResult` with the SHA-256 digest and total
        size in bytes. The hash is computed on the raw response bytes
        (after decompression if the server applied transfer encoding).
        """
        resp = self.request(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=timeout,
            stream=True,
        )
        if resp.status_code >= 400:
            resp.close()
            raise NetworkError(
                f"HTTP GET {url} -> {resp.status_code}",
                url=url,
                status_code=resp.status_code,
            )

        hasher = hashlib.sha256()
        total = 0

        close_sink = False
        if hasattr(dest, "write"):
            sink = dest
        else:
            sink = open(dest, "wb")
            close_sink = True
        try:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                sink.write(chunk)
                hasher.update(chunk)
                total += len(chunk)
        finally:
            if close_sink:
                sink.close()
            resp.close()

        return StreamResult(
            sha256=hasher.hexdigest(),
            size=total,
            status_code=resp.status_code,
            url=url,
            headers=dict(resp.headers),
        )

    def iter_bytes(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        chunk_size: int = DEFAULT_CHUNK,
        timeout: float | None = None,
    ) -> Iterator[bytes]:
        """Yield response chunks (no hashing, no sink)."""
        resp = self.request(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=timeout,
            stream=True,
        )
        try:
            if resp.status_code >= 400:
                raise NetworkError(
                    f"HTTP GET {url} -> {resp.status_code}",
                    url=url,
                    status_code=resp.status_code,
                )
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if chunk:
                    yield chunk
        finally:
            resp.close()


def _parse_retry_after(value: str) -> float | None:
    """Parse an HTTP Retry-After header into seconds."""
    value = value.strip()
    if not value:
        return None
    try:
        seconds = float(value)
        if seconds >= 0:
            return seconds
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    now = time.time()
    target = dt.timestamp()
    delta = target - now
    return max(0.0, delta)


_DEFAULT_CLIENT: HTTPClient | None = None
_DEFAULT_LOCK = threading.Lock()


def get_default_client() -> HTTPClient:
    """Module-level singleton used by data providers that do not own a client."""
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        with _DEFAULT_LOCK:
            if _DEFAULT_CLIENT is None:
                _DEFAULT_CLIENT = HTTPClient(user_agent="HydroModPy/0.5")
    return _DEFAULT_CLIENT


__all__ = [
    "HTTPClient",
    "StreamResult",
    "get_default_client",
]
