"""HTTP client scaffold.

This module reserves the import path for the unified HTTP client with
retry, backoff, and timeout logic. The real implementation lands in phase
G04, where it replaces the dispersed ``urllib.request.urlretrieve`` calls
across the data providers (Hub'Eau, BRGM, IGN, Meteo-France).

Until then, nothing is exported: importing :mod:`hydromodpy.core.io.http_client`
simply confirms that the path resolves.
"""

from __future__ import annotations

__all__: list[str] = []
