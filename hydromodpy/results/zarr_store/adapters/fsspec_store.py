"""fsspec-backed Zarr store stub. Real cloud support ships in v2.x."""

from __future__ import annotations

from typing import Any


class FsspecZarrStore:
    """Cloud Zarr store ready-to-go. Not implemented in v2.0.

    Instantiation succeeds so type-checkers and IDE completion can resolve the
    symbol, but :meth:`open` raises :class:`NotImplementedError` with a
    pointer to the optional ``[cloud]`` extra. Use :class:`SimulationZarr` for
    local file:// stores.
    """

    def __init__(self, uri: str, **storage_options: Any) -> None:
        self._uri = uri
        self._storage_options = storage_options

    @property
    def uri(self) -> str:
        return self._uri

    @property
    def storage_options(self) -> dict[str, Any]:
        return dict(self._storage_options)

    def open(self) -> None:
        raise NotImplementedError(
            "Cloud store ready-to-go; install hydromodpy[cloud] in v2.x to enable."
        )

    def close(self) -> None:
        """No-op close so this stub is safe inside ``with`` statements."""
        return None


__all__ = ["FsspecZarrStore"]
