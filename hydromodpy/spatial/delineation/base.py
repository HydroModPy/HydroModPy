"""Protocol for catchment delineation backends.

This module defines the abstract contract used by `hydromodpy` to perform
delineation on top of a digital elevation model. Concrete implementations
live in `whitebox_workflows_backend.py` and `synthetic_backend.py`.

The low-level Whitebox surface is no longer expressed as a Protocol since
:class:`hydromodpy.spatial.delineation.whitebox_workflows_backend.WhiteboxWorkflowsBackend`
splits its API across three thematic sub-backends (raster IO, flow analysis,
delineation) and is the only concrete implementation. Callers that need a
typed handle reference :class:`WhiteboxWorkflowsBackend` directly.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DelineationBackend(Protocol):
    """Minimal high-level contract for a catchment delineation backend.

    All methods accept filesystem paths or arrays depending on the backend.
    Return types are intentionally left as ``Any`` so that backends can
    pick the representation best suited for their pipeline (numpy arrays,
    rasterio datasets, geopandas frames, ...). Runtime code should rely
    on the documented semantics rather than the concrete type.
    """

    name: str

    def flow_accumulation(self, dem: Any, **kwargs: Any) -> Any:
        """Compute a flow-accumulation raster from a DEM."""
        ...

    def flow_direction(self, dem: Any, **kwargs: Any) -> Any:
        """Compute a flow-direction (pointer) raster from a DEM."""
        ...

    def stream_network(self, dem: Any, threshold: float, **kwargs: Any) -> Any:
        """Extract the stream network from a DEM given an accumulation threshold."""
        ...

    def catchment_from_outlet(
        self,
        dem: Any,
        x: float,
        y: float,
        **kwargs: Any,
    ) -> Any:
        """Delineate the catchment polygon upstream of the outlet at (x, y)."""
        ...
