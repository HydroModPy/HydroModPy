"""Pysheds-based delineation backend (stub).

Pysheds (https://github.com/mdbartos/pysheds) is a pure-Python flow
routing library. It is an attractive alternative for environments where
WhiteboxTools cannot be installed. This backend is reserved in the
registry but not yet implemented.
"""

from __future__ import annotations

from typing import Any


class PyshedsBackend:
    """Placeholder for a future pysheds-backed delineation backend."""

    name = "pysheds"

    def __init__(self) -> None:
        raise NotImplementedError(
            "The pysheds delineation backend is not implemented yet."
        )

    def flow_accumulation(self, dem: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def flow_direction(self, dem: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def stream_network(self, dem: Any, threshold: float, **kwargs: Any) -> Any:
        raise NotImplementedError

    def catchment_from_outlet(
        self, dem: Any, x: float, y: float, **kwargs: Any
    ) -> Any:
        raise NotImplementedError
