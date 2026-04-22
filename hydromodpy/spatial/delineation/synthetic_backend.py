"""Synthetic delineation backend.

Wraps the procedural geographic generator already present in
``hydromodpy.spatial.geographic.synthetic`` so that it can be exposed
through the same registry as the whitebox-based backends. Useful for
tests and tutorials where no real DEM is available.

The backend does not perform numerical flow routing. Instead it uses
the analytical topography laws defined in
:mod:`hydromodpy.spatial.geographic.synthetic.topography` and exposes
the resulting surface + watershed polygon directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class SyntheticBackend:
    """Delineation backend backed by procedural topography laws."""

    name = "synthetic"

    def build(
        self,
        config: Any,
        *,
        output_dir: str | Path,
        workspace: Any | None = None,
    ) -> Any:
        """Materialise a synthetic geographic context on disk.

        ``config`` must be a
        :class:`hydromodpy.spatial.geographic.synthetic.config.SyntheticGeographicConfig`
        instance. Returns the resulting ``SyntheticGeographic`` object.
        """
        from hydromodpy.spatial.geographic.synthetic.synthetic_geographic import (
            SyntheticGeographic,
        )

        return SyntheticGeographic(
            config=config,
            output_dir=Path(output_dir),
            workspace=workspace,
        )

    def flow_accumulation(self, dem: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(
            "Synthetic backend does not compute flow accumulation; use a "
            "whitebox backend on the generated DEM instead."
        )

    def flow_direction(self, dem: Any, **kwargs: Any) -> Any:
        raise NotImplementedError(
            "Synthetic backend does not compute flow direction; use a "
            "whitebox backend on the generated DEM instead."
        )

    def stream_network(self, dem: Any, threshold: float, **kwargs: Any) -> Any:
        raise NotImplementedError(
            "Synthetic backend does not extract stream networks. "
            "Extract them from the generated DEM via a whitebox backend."
        )

    def catchment_from_outlet(
        self, dem: Any, x: float, y: float, **kwargs: Any
    ) -> Any:
        raise NotImplementedError(
            "Synthetic catchments are generated from the grid extent "
            "declared in SyntheticGeographicConfig, not from outlets."
        )
