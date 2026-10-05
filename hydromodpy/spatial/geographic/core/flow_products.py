"""Generate core hydrologic rasters from a source DEM.

Purpose
-------
Produce the minimum raster stack required by outlet-based delineation:
1. hydrologically corrected DEM,
2. D8 flow-direction raster,
3. D8 flow-accumulation raster.

Pipeline position
-----------------
This is one of the first compute-heavy steps in geographic preprocessing.
All downstream catchment and river-network products depend on these rasters.

Why this file computes nothing
------------------------------
Every step here goes through :class:`~hydromodpy.spatial.terrain.TerrainEngine`.
The three rasters are the engine's own products, so what used to be three
opaque Whitebox objects carried alongside three path strings is now one
:class:`~hydromodpy.spatial.terrain.FlowAccumulation`, which says in its own
fields what the strings never did: the accumulation is a cell count under a
**natural** logarithm, the pointer descends a DEM conditioned by a named
method, and the nodata is the one the file on disk declares.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hydromodpy.core import progress
from hydromodpy.core.io.crs import ensure_crs
from hydromodpy.spatial.terrain import (
    CappedBreach,
    CappedBreachReport,
    ConditionedDem,
    ConditioningExtent,
    ConditioningMethod,
    DrainageDirections,
    FlowAccumulation,
)
from hydromodpy.spatial.terrain import registry as terrain_registry
from hydromodpy.spatial.terrain.artifacts import raster_crs, raster_nodata

CORRECTED_DEM_NAMES: dict[str, str] = {
    "fill": "dem_fill.tif",
    "breach": "dem_breach.tif",
    "capped_breach": "dem_capped_breach.tif",
}
DIRECTION_NAME = "dem_direc.tif"
ACCUMULATION_NAME = "dem_acc.tif"

ACCUMULATION_UNITS = "cells"
ACCUMULATION_TRANSFORM = "ln"
"""What this pipeline has always written, now said out loud.

``log=True`` on the Whitebox chain is the natural logarithm, so a caller that
thresholds ``dem_acc.tif`` with a cell count selects nothing. The product
declares the transform so the refusal happens at the boundary instead.
"""


@dataclass(frozen=True)
class FlowProducts:
    """The regional flow stack, as the one product that describes it.

    ``correc``, ``direc`` and ``acc`` stay as strings because thirty call sites
    read them, but they are views on the accumulation and not a second copy of
    the truth.
    """

    accumulation: FlowAccumulation

    @property
    def correc(self) -> str:
        """Hydrologically corrected DEM."""
        return str(self.accumulation.directions.conditioned_dem.path)

    @property
    def direc(self) -> str:
        """D8 direction raster (encoded neighbor direction per cell)."""
        return str(self.accumulation.directions.path)

    @property
    def acc(self) -> str:
        """D8 accumulation raster, in cells under a natural logarithm."""
        return str(self.accumulation.path)


def capped_breach_of(geographic: object) -> CappedBreach | None:
    """Return the capped-breach limits one geographic object selects, else ``None``.

    Reads ``dem_correc_type`` and ``capped_breach`` off a ``GeographicConfig`` or
    off the ``CatchmentDelineation`` that carries the same two attributes, so a
    solver rebuilding its routing rasters conditions the DEM as the delineation
    did. A ``capped_breach`` run with no section uses the defaults of the
    section, which is what the configuration documents.
    """
    if str(getattr(geographic, "dem_correc_type", "")) != "capped_breach":
        return None
    from hydromodpy.spatial.geographic.geographic_config import CappedBreachConfig

    section = getattr(geographic, "capped_breach", None) or CappedBreachConfig()
    return CappedBreach(
        max_depth_m=float(section.max_depth), max_distance_m=float(section.max_distance)
    )


def conditioning_method(
    dem_correc_type: str, capped_breach: CappedBreach | None = None
) -> ConditioningMethod:
    """Return the port's conditioning method one configuration string names.

    ``capped_breach`` carries the limits of the ``capped_breach`` method and is
    refused for the others, so a limit is never passed that nothing applies.
    """
    if dem_correc_type not in CORRECTED_DEM_NAMES:
        raise ValueError(
            f"Unknown dem_correc_type={dem_correc_type!r}. "
            "Expected 'fill', 'breach' or 'capped_breach'."
        )
    if dem_correc_type == "capped_breach":
        if capped_breach is None:
            raise ValueError(
                "dem_correc_type='capped_breach' needs its limits (capped_breach=...)."
            )
        return capped_breach
    if capped_breach is not None:
        raise ValueError(
            f"Capped-breach limits were given with dem_correc_type={dem_correc_type!r}, "
            "which has none."
        )
    return "fill" if dem_correc_type == "fill" else "breach"


def corrected_dem_name(dem_correc_type: str) -> str:
    """Return the file name one conditioning method writes."""
    if dem_correc_type not in CORRECTED_DEM_NAMES:
        raise ValueError(
            f"Unknown dem_correc_type={dem_correc_type!r}. "
            "Expected 'fill', 'breach' or 'capped_breach'."
        )
    return CORRECTED_DEM_NAMES[dem_correc_type]


def flow_products_from_paths(
    *,
    dem_out_dir_path: str | Path,
    dem_correc_type: str,
    capped_breach: CappedBreach | None = None,
    breach_report: CappedBreachReport | None = None,
) -> FlowProducts:
    """Describe a stack that is already on disk, reading its facts from it.

    ``breach_report`` is what the capped breach that wrote the stack measured,
    read back from the description stored with it: the rasters alone cannot say
    what was dug without the raw DEM.

    The CRS and the nodata come from the rasters themselves rather than from
    whatever the caller believes, which is the only way a reconstruction can
    describe files it did not write. Every named file has to exist.
    """
    out_dir = Path(dem_out_dir_path)
    correc = out_dir / corrected_dem_name(dem_correc_type)
    direc = out_dir / DIRECTION_NAME
    acc = out_dir / ACCUMULATION_NAME

    conditioned = ConditionedDem(
        path=correc,
        method=conditioning_method(dem_correc_type, capped_breach),
        extent=ConditioningExtent.regional(),
        crs=raster_crs(correc),
        breach_report=breach_report,
    )
    directions = DrainageDirections(
        path=direc,
        pointer_convention="d8_wbt",
        conditioned_dem=conditioned,
    )
    return FlowProducts(
        accumulation=FlowAccumulation(
            path=acc,
            units=ACCUMULATION_UNITS,
            transform=ACCUMULATION_TRANSFORM,
            directions=directions,
            nodata=raster_nodata(acc),
        )
    )


def build_regional_flow_products(
    *,
    dem_init_path: str | Path,
    dem_out_dir_path: str | Path,
    dem_correc_type: str,
    crs_project: str | None = None,
    backend: object | None = None,
    engine_id: str | None = None,
    capped_breach: CappedBreach | None = None,
) -> FlowProducts:
    """Generate corrected DEM, D8 direction and D8 accumulation rasters.

    Parameters
    ----------
    dem_init_path:
        Input regional DEM.
    dem_out_dir_path:
        Output directory for generated rasters.
    dem_correc_type:
        Hydrologic correction strategy:
        - ``"fill"``: fills closed depressions so water can exit each cell,
        - ``"breach"``: carves narrow paths through barriers/depressions,
        - ``"capped_breach"``: carves within ``capped_breach`` limits, then fills
          the depressions the limits refused.
    capped_breach:
        Limits of ``"capped_breach"``, required for it and refused otherwise.
    crs_project:
        Optional CRS to enforce on output metadata. The engine already stamps
        the CRS of the source DEM; this one is the project's policy on top, and
        it is the caller's, not the engine's.
    backend:
        Optional Whitebox backend injected for runtime/tests. It reaches the
        engine only if that engine names ``backend`` in its constructor.
    engine_id:
        Name of the terrain engine to route with. ``None`` resolves the default
        this build ships, which is the one every committed number was produced
        with.
    """
    engine = terrain_registry.create(engine_id, backend=backend)

    out_dir = Path(dem_out_dir_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    correc_name = corrected_dem_name(dem_correc_type)

    with progress.status("Correcting DEM"):
        conditioned = engine.condition_dem(
            Path(dem_init_path),
            method=conditioning_method(dem_correc_type, capped_breach),
            extent=ConditioningExtent.regional(),
            out=out_dir / correc_name,
        )
    with progress.status("Computing flow accumulation"):
        directions = engine.drainage_directions(conditioned, out=out_dir / DIRECTION_NAME)
        accumulation = engine.flow_accumulation(
            directions,
            units=ACCUMULATION_UNITS,
            transform=ACCUMULATION_TRANSFORM,
            out=out_dir / ACCUMULATION_NAME,
        )

    products = FlowProducts(accumulation=accumulation)
    # Normalize CRS metadata to keep downstream GIS/raster steps predictable.
    for path in (products.correc, products.direc, products.acc):
        ensure_crs(path, crs_project)
    return products
