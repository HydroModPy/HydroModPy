"""Terrain products built from bare paths, for tests that never touch a DEM.

A :class:`~hydromodpy.spatial.geographic.core.flow_products.FlowProducts` is the
engine's own product, so a test that stubs the builder still has to hand its
caller one. These helpers describe files that may not exist: they are doubles,
and nothing here reads a raster.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.spatial.geographic.core.flow_products import FlowProducts
from hydromodpy.spatial.terrain import (
    ConditionedDem,
    ConditioningExtent,
    ConditioningMethod,
    DrainageDirections,
    FlowAccumulation,
)


def fake_accumulation(
    *,
    correc: str | Path = "fill.tif",
    direc: str | Path = "direc.tif",
    acc: str | Path = "acc.tif",
    method: ConditioningMethod = "fill",
    crs: str = "EPSG:2154",
    transform: str = "ln",
    nodata: float = -32768.0,
) -> FlowAccumulation:
    """Return an accumulation product naming paths, without reading any."""
    conditioned = ConditionedDem(
        path=Path(correc),
        method=method,
        extent=ConditioningExtent.regional(),
        crs=crs,
    )
    return FlowAccumulation(
        path=Path(acc),
        units="cells",
        transform=transform,  # type: ignore[arg-type]
        directions=DrainageDirections(
            path=Path(direc),
            pointer_convention="d8_wbt",
            conditioned_dem=conditioned,
        ),
        nodata=nodata,
    )


def fake_flow_products(
    *,
    correc: str | Path = "fill.tif",
    direc: str | Path = "direc.tif",
    acc: str | Path = "acc.tif",
    method: ConditioningMethod = "fill",
    crs: str = "EPSG:2154",
    transform: str = "ln",
) -> FlowProducts:
    """Return a flow-product bundle naming paths, without reading any."""
    return FlowProducts(
        accumulation=fake_accumulation(
            correc=correc,
            direc=direc,
            acc=acc,
            method=method,
            crs=crs,
            transform=transform,
        )
    )


__all__ = ["fake_accumulation", "fake_flow_products"]
