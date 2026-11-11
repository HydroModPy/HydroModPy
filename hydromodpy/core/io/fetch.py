"""Unified HTTP download client, URL safety guard and pinned download.

Every remote asset and user URL downloaded by HydroModPy passes through this
module. The client is created per call with its own bounds (allowed hosts,
download size ceiling, timeout) and session lifecycle.

The client caps a download at 2 GiB unless the bounds say otherwise, refuses a private
address unless the bounds allow the host by name, resolves the final target of a
redirect itself and checks a pinned sha256 digest. ``vsicurl_path`` gives the GDAL path
of a remote file.
"""

from __future__ import annotations

import contextlib
import hashlib
import ipaddress
import os
import random
import socket
import threading
import time
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import parse_qsl, urljoin, urlsplit

import requests

from hydromodpy.core.exceptions import (
    BoundsError,
    CacheCorruptionError,
    DataSourceError,
    NetworkError,
)
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.bounds import Bounds, _host_key

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 4
DEFAULT_BACKOFF_BASE = 0.5
DEFAULT_BACKOFF_CAP = 30.0
DEFAULT_CHUNK = 64 * 1024
DEFAULT_RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
SIGNATURE_QUERY_KEYS = frozenset({"x-amz-signature", "signature", "token", "sig"})
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
DEFAULT_MAX_REDIRECT_HOPS = 5


@dataclass
class StreamResult:
    """Result of HTTPClient.stream: final path and digest metadata."""

    sha256: str
    size: int
    status_code: int
    url: str
    headers: dict[str, str] = field(default_factory=dict)


class ResolvedUrl(NamedTuple):
    """Result of resolve_final_url: final URL after following redirects manually."""

    url: str
    etag: str | None = None
    last_modified: str | None = None
    content_length: int | None = None


@dataclass(frozen=True, slots=True)
class Fetched:
    """Result of download: verified file path and response metadata."""

    path: Path
    sha256: str
    size: int
    final_url: str
    etag: str | None = None
    last_modified: str | None = None
    content_type: str | None = None


class _TokenBucket:
    """Simple per-host semaphore used to cap concurrent in-flight requests."""

    def __init__(self, capacity: int) -> None:
        self._sem = threading.BoundedSemaphore(capacity)

    @contextlib.contextmanager
    def slot(self) -> Iterator[None]:
        self._sem.acquire()
        try:
            yield
        finally:
            self._sem.release()


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
    delta = dt.timestamp() - now
    return max(0.0, delta)


def guard_url(
    url: str,
    bounds: Bounds | None = None,
    *,
    pinned: bool = False,
    resolve_dns: bool = True,
    check_signatures: bool = True,
) -> None:
    """Check a URL against scheme, credential, signature, and host constraints.

    Refuses schemes other than https, or http without a pinned sha256 digest.
    Refuses embedded credentials and signature query parameters. A redirect a
    server chose is checked with ``check_signatures=False``: release assets
    (GitHub, S3) carry a signed query string on their target and stay public,
    so the scheme, host and address guards still apply at every hop.
    Refuses hosts outside bounds.allowed_hosts when specified.
    Refuses private, loopback, multicast, or non-global IP addresses unless
    the host is explicitly named in bounds.allowed_hosts.
    """
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("https", "http"):
        raise BoundsError(
            f"URL {url!r} scheme {scheme!r} is not supported. Use https, or http with a pinned sha256."
        )
    if scheme == "http" and not pinned:
        raise BoundsError(
            f"URL {url!r} uses http without a pinned sha256. Use https or pin the sha256."
        )
    if parsed.username is not None or parsed.password is not None:
        raise BoundsError(
            f"URL {url!r} carries embedded credentials. Remove user:password from the URL."
        )

    if check_signatures:
        query_params = parse_qsl(parsed.query, keep_blank_values=True)
        for key, _ in query_params:
            if key.lower() in SIGNATURE_QUERY_KEYS:
                raise BoundsError(f"URL {url!r} carries forbidden signature parameter {key!r}.")

    guard_host(
        parsed.hostname or "",
        bounds,
        what=f"fetch guard for {url}",
        resolve_dns=resolve_dns,
    )


def guard_host(
    host: str,
    bounds: Bounds | None = None,
    *,
    what: str,
    resolve_dns: bool = True,
) -> None:
    """Check one host name against the host list and the addresses it resolves to.

    *what* names the caller and opens the sentence of a refusal, so a fetch
    and a delivery say which one is speaking. Refuses a host outside
    ``bounds.allowed_hosts`` when specified, and a private, loopback,
    multicast or non-global address unless the host is explicitly named
    there. ``resolve_dns=False`` keeps only the host-list check.
    """
    if not host:
        raise BoundsError(f"{what} names no host.")
    if bounds is not None and bounds.allowed_hosts is not None:
        bounds.require_hosts([host], why=what)

    if not resolve_dns:
        return

    host_key = _host_key(host)
    is_allowed_host = (
        bounds is not None and bounds.allowed_hosts is not None and host_key in bounds.allowed_hosts
    )

    try:
        addrinfo = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise NetworkError(f"Could not resolve host {host!r}: {exc}", url=what) from exc

    for entry in addrinfo:
        ip_str = entry[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        mapped = getattr(ip, "ipv4_mapped", None)
        target = mapped if mapped is not None else ip
        if (not target.is_global) or target.is_multicast:
            if not is_allowed_host:
                raise BoundsError(
                    f"Host {host!r} resolved to non-public IP address {ip_str!r}, which is forbidden "
                    "unless the host is explicitly named in allowed_hosts."
                )


class HTTPClient:
    """HTTP client with backoff retries and streaming support.

    Created per call with caller-provided bounds; does not rely on global singletons.
    """

    def __init__(
        self,
        *,
        timeout: float | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        backoff_cap: float = DEFAULT_BACKOFF_CAP,
        max_redirect_hops: int = DEFAULT_MAX_REDIRECT_HOPS,
        per_host_concurrency: int = 4,
        retry_statuses: frozenset[int] = DEFAULT_RETRY_STATUSES,
        user_agent: str | None = None,
        bounds: Bounds | None = None,
    ) -> None:
        self.bounds = bounds
        # An explicit timeout wins over the timeout of the bounds.
        self.timeout = (
            timeout
            if timeout is not None
            else (bounds.timeout_s if bounds is not None else DEFAULT_TIMEOUT)
        )
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.max_redirect_hops = max_redirect_hops
        self.retry_statuses = retry_statuses
        self._session = requests.Session()
        # Proxies, netrc credentials and CA overrides of the environment are
        # never trusted; the caller passes a Bounds, never the environment.
        self._session.trust_env = False
        if user_agent:
            self._session.headers["User-Agent"] = user_agent
        self._per_host_capacity = per_host_concurrency
        self._host_buckets: dict[str, _TokenBucket] = defaultdict(
            lambda: _TokenBucket(per_host_concurrency)
        )
        self._buckets_lock = threading.Lock()

    def _bucket_for(self, url: str) -> _TokenBucket:
        host = urlsplit(url).netloc
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

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

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
        allow_redirects: bool = True,
    ) -> requests.Response:
        """Issue an HTTP request with retries, backoff, and a guarded redirect chain.

        Redirections are followed by hand, one hop at a time, so every hop
        passes :func:`guard_url` with this client's bounds. Signature query
        keys are refused on the URL the caller wrote only: a target URL a
        server chose stays public by the scheme, host and address guards.
        """
        current_url = url
        for hop in range(self.max_redirect_hops + 1):
            resp = self._request_once(
                method,
                current_url,
                params=params,
                headers=headers,
                data=data,
                json=json,
                timeout=timeout,
                stream=stream,
            )
            if not (allow_redirects and resp.status_code in REDIRECT_STATUSES):
                return resp
            location = resp.headers.get("Location")
            if not location:
                return resp
            if hop >= self.max_redirect_hops:
                raise NetworkError(
                    f"HTTP {method} {url} exceeded {self.max_redirect_hops} redirects",
                    url=url,
                    method=method,
                    last_exception=None,
                )
            resp.close()
            next_url = urljoin(current_url, location)
            # A hop is a URL the server chose: scheme, host and address
            # guards hold at every hop, the signature keys do not apply to it.
            guard_url(next_url, self.bounds, check_signatures=False)
            logger.info("HTTP %s %s -> %d, following %s", method, url, resp.status_code, next_url)
            current_url = next_url
        raise NetworkError(
            f"HTTP {method} {url} did not settle within {self.max_redirect_hops} redirects",
            url=url,
            method=method,
        )

    def _request_once(
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
        """Send one request with the retries and backoff of this client."""
        effective_timeout = timeout if timeout is not None else self.timeout

        with self._bucket_for(url).slot():
            for attempt in range(self.max_retries + 1):
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
                        allow_redirects=False,
                    )
                except requests.RequestException as exc:
                    if attempt >= self.max_retries:
                        raise NetworkError(
                            f"HTTP {method} {url} failed after "
                            f"{self.max_retries + 1} attempts: {exc}",
                            url=url,
                            method=method,
                            last_exception=str(exc),
                        ) from exc
                    delay = self._compute_backoff(attempt, None)
                    logger.warning(
                        "HTTP %s %s failed (%s) - retry %d/%d in %.2fs",
                        method,
                        url,
                        exc,
                        attempt + 1,
                        self.max_retries,
                        delay,
                    )
                    time.sleep(delay)
                    continue

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
            f"HTTP {method} {url} failed after {self.max_retries + 1} attempts",
            url=url,
            method=method,
        )

    def get(self, url: str, **kw: Any) -> requests.Response:
        return self.request("GET", url, **kw)

    def head(self, url: str, **kw: Any) -> requests.Response:
        return self.request("HEAD", url, **kw)

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        model: Any | None = None,
    ) -> Any:
        """GET a JSON document, optionally validating with a model."""
        resp = self.request("GET", url, params=params, headers=headers, timeout=timeout)
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

    def _raise_outside_2xx(self, status_code: int, url: str) -> None:
        """Refuse any status outside 2xx with a NetworkError carrying the code."""
        if status_code < 200 or status_code >= 300:
            raise NetworkError(
                f"HTTP GET {url} -> {status_code}",
                url=url,
                status_code=status_code,
            )

    def stream(
        self,
        url: str,
        dest: Any,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        chunk_size: int = DEFAULT_CHUNK,
        timeout: float | None = None,
    ) -> StreamResult:
        """Stream a URL to dest (path or writable sink), hashed and bounded.

        Any status outside 2xx is refused before a byte is written, the byte
        ceiling of the bounds applies, and a connection lost in the body
        raises NetworkError.
        """
        resp = self.request(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=timeout,
            stream=True,
        )
        try:
            self._raise_outside_2xx(resp.status_code, url)
            hasher = hashlib.sha256()
            total = 0
            ceiling = self.bounds.max_download_bytes if self.bounds is not None else None
            close_sink = False
            if hasattr(dest, "write"):
                sink = dest
            else:
                sink = open(dest, "wb")  # noqa: SIM115 - closed in the finally below
                close_sink = True
            try:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if ceiling is not None and total > ceiling:
                        raise BoundsError(
                            f"Download of {url} exceeded the byte ceiling "
                            f"({ceiling} bytes) of the bounds of this client."
                        )
                    sink.write(chunk)
                    hasher.update(chunk)
            except requests.RequestException as exc:
                raise NetworkError(
                    f"Connection lost while reading {url}: {exc}",
                    url=url,
                    last_exception=str(exc),
                ) from exc
            finally:
                if close_sink:
                    sink.close()
        finally:
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
        """Yield response chunks without hashing or saving.

        Any status outside 2xx is refused, and a connection lost in the body
        raises NetworkError instead of a bare requests exception.
        """
        resp = self.request(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=timeout,
            stream=True,
        )
        try:
            self._raise_outside_2xx(resp.status_code, url)
            try:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if chunk:
                        yield chunk
            except requests.RequestException as exc:
                raise NetworkError(
                    f"Connection lost while reading {url}: {exc}",
                    url=url,
                    last_exception=str(exc),
                ) from exc
        finally:
            resp.close()


@contextlib.contextmanager
def open_client(
    bounds: Bounds | None = None,
    *,
    timeout: float | None = None,
    user_agent: str | None = None,
) -> Iterator[HTTPClient]:
    """Context manager yielding an HTTPClient configured with bounds and closing it on exit."""
    effective_timeout = (
        timeout if timeout is not None else (bounds.timeout_s if bounds else DEFAULT_TIMEOUT)
    )
    client = HTTPClient(timeout=effective_timeout, user_agent=user_agent, bounds=bounds)
    try:
        yield client
    finally:
        client.close()


def resolve_final_url(
    url: str,
    bounds: Bounds | None = None,
    client: HTTPClient | None = None,
    *,
    pinned: bool = False,
    max_hops: int = 5,
) -> ResolvedUrl:
    """Follow HTTP redirects manually with guard_url checked at every hop."""
    guard_url(url, bounds=bounds, pinned=pinned)
    current_url = url

    def _do_head(cl: HTTPClient) -> ResolvedUrl:
        nonlocal current_url
        hops = 0
        etag: str | None = None
        last_modified: str | None = None
        content_length: int | None = None

        while True:
            resp = cl.request("HEAD", current_url, allow_redirects=False)
            etag = resp.headers.get("ETag") or etag
            last_modified = resp.headers.get("Last-Modified") or last_modified
            length_hdr = resp.headers.get("Content-Length")
            if length_hdr and length_hdr.isdigit():
                content_length = int(length_hdr)

            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location")
                if not location:
                    break
                hops += 1
                if hops > max_hops:
                    raise NetworkError(
                        f"Too many redirects for {url} (exceeded {max_hops} hops)",
                        url=url,
                    )
                next_url = urljoin(current_url, location)
                # A hop is a URL the server chose: scheme, host and address
                # guards hold, the signature keys do not apply to it.
                guard_url(next_url, bounds=bounds, pinned=pinned, check_signatures=False)
                current_url = next_url
                resp.close()
                continue

            resp.close()
            break

        return ResolvedUrl(
            url=current_url,
            etag=etag,
            last_modified=last_modified,
            content_length=content_length,
        )

    if client is not None:
        return _do_head(client)
    with open_client(bounds=bounds) as cl:
        return _do_head(cl)


def vsicurl_path(
    url: str,
    bounds: Bounds | None = None,
    client: HTTPClient | None = None,
    *,
    pinned: bool = False,
) -> str:
    """Return /vsicurl/ prefixed to the resolved final URL."""
    resolved = resolve_final_url(url, bounds=bounds, client=client, pinned=pinned)
    return f"/vsicurl/{resolved.url}"


def download(
    url: str,
    dest: Path | str,
    *,
    bounds: Bounds | None = None,
    sha256: str | None = None,
    client: HTTPClient | None = None,
) -> Fetched:
    """Download a URL to dest with atomic write, size limit, and sha256 verification."""
    # An explicit bounds wins; a client carries its own bounds, so a call that
    # hands a client in is guarded by what that client was built with.
    client_bounds = getattr(client, "bounds", None) if client is not None else None
    if bounds is not None:
        effective_bounds = bounds
    elif client_bounds is not None:
        effective_bounds = client_bounds
    else:
        effective_bounds = Bounds()
    final_info = resolve_final_url(url, bounds=effective_bounds, client=client, pinned=bool(sha256))

    target = Path(dest)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.{os.getpid()}.part")

    def _stream_body(cl: HTTPClient) -> Fetched:
        resp = cl.request("GET", final_info.url, stream=True, allow_redirects=False)
        try:
            try:
                if resp.status_code < 200 or resp.status_code >= 300:
                    raise NetworkError(
                        f"HTTP GET {final_info.url} -> {resp.status_code}",
                        url=final_info.url,
                        status_code=resp.status_code,
                    )

                etag = resp.headers.get("ETag") or final_info.etag
                last_modified = resp.headers.get("Last-Modified") or final_info.last_modified
                content_type = resp.headers.get("Content-Type")

                hasher = hashlib.sha256()
                total_size = 0
                with open(partial, "wb") as sink:
                    for chunk in resp.iter_content(chunk_size=DEFAULT_CHUNK):
                        if not chunk:
                            continue
                        total_size += len(chunk)
                        if total_size > effective_bounds.max_download_bytes:
                            raise BoundsError(
                                f"Download of {url} exceeded the byte ceiling "
                                f"({effective_bounds.max_download_bytes} bytes) of the call."
                            )
                        sink.write(chunk)
                        hasher.update(chunk)
            except requests.RequestException as exc:
                partial.unlink(missing_ok=True)
                raise NetworkError(
                    f"Connection lost while reading {url}: {exc}",
                    url=url,
                    last_exception=str(exc),
                ) from exc
            except BaseException:
                partial.unlink(missing_ok=True)
                raise
        finally:
            resp.close()
        found_digest = hasher.hexdigest()
        if sha256 is not None and found_digest != sha256:
            partial.unlink(missing_ok=True)
            raise CacheCorruptionError(
                f"{target.name} downloaded from {url} hashes to {found_digest}, and HydroModPy pins sha256 {sha256} for it. Nothing was kept.",
                source=url,
                expected=sha256,
                found=found_digest,
            )
        partial.replace(target)
        return Fetched(
            path=target,
            sha256=found_digest,
            size=total_size,
            final_url=final_info.url,
            etag=etag,
            last_modified=last_modified,
            content_type=content_type,
        )

    if client is not None:
        return _stream_body(client)
    with open_client(bounds=effective_bounds) as cl:
        return _stream_body(cl)


def fetch_pinned(
    url: str,
    dest: Path,
    *,
    sha256: str,
    remedy: str,
    force: bool = False,
    bounds: Bounds | None = None,
) -> Path:
    """Return dest holding the bytes sha256 names, fetching url when absent."""
    if dest.is_file() and not force:
        cached = sha256_of(dest)
        if cached != sha256:
            dest.unlink(missing_ok=True)
            raise CacheCorruptionError(
                f"{dest} hashes to {cached}, and HydroModPy pins sha256 {sha256} for it. It was "
                f"removed: run the same command again to fetch a clean copy. {remedy}",
                source=str(dest),
                expected=sha256,
                found=cached,
            )
        return dest

    try:
        download(url, dest, bounds=bounds, sha256=sha256)
    except CacheCorruptionError as exc:
        raise CacheCorruptionError(
            f"{exc.args[0]} {remedy}",
            source=url,
            expected=sha256,
            found=exc.context.get("found", ""),
        ) from exc
    return dest


__all__ = [
    "DEFAULT_BACKOFF_BASE",
    "DEFAULT_BACKOFF_CAP",
    "DEFAULT_CHUNK",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RETRY_STATUSES",
    "DEFAULT_TIMEOUT",
    "Fetched",
    "HTTPClient",
    "ResolvedUrl",
    "StreamResult",
    "download",
    "fetch_pinned",
    "guard_url",
    "open_client",
    "resolve_final_url",
    "vsicurl_path",
]
