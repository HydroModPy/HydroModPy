"""Geometry gallery family extracted from the main manifest."""

from __future__ import annotations

from .gallery_schema import (
    GalleryCaseSpec,
    GalleryImageAsset,
    GalleryMetricSpec,
    _format_float,
    _format_int,
)

_GEOMETRY_CONSTRAINT_METRIC_SPECS = (
    GalleryMetricSpec("Boundary area", "boundary_area_km2", _format_float("km2", precision=1)),
    GalleryMetricSpec("River length", "river_length_km", _format_float("km", precision=1)),
    GalleryMetricSpec("Geology units", "geology_unit_count", _format_int),
)

_GEOMETRY_TOPO_METRIC_SPECS = (
    GalleryMetricSpec("Boundary area", "boundary_area_km2", _format_float("km2", precision=1)),
    GalleryMetricSpec("River length", "river_length_km", _format_float("km", precision=1)),
    GalleryMetricSpec("DEM min", "dem_min_m", _format_float("m", precision=0)),
    GalleryMetricSpec("DEM max", "dem_max_m", _format_float("m", precision=0)),
)

_GEOMETRY_INDICATOR_METRIC_SPECS = (
    GalleryMetricSpec("Boundary area", "boundary_area_km2", _format_float("km2", precision=1)),
    GalleryMetricSpec("Mean slope", "slope_mean_deg", _format_float("deg", precision=1)),
    GalleryMetricSpec("Slope p90", "slope_p90_deg", _format_float("deg", precision=1)),
    GalleryMetricSpec("DEM range", "dem_range_m", _format_float("m", precision=0)),
)


def build_geometry_specs() -> tuple[GalleryCaseSpec, ...]:
    return (
        GalleryCaseSpec(
            slug="geometry_constraints_canut",
            title="Catchment Geometry Constraints",
            category="geometry",
            deck="Basin outline, hydro network, geology units, and regional context rendered without mesh overlays.",
            summary=(
                "This case focuses on geometry only: a catchment mask, the clipped river network, "
                "geology units inside the boundary, and a regional DEM backdrop. It documents the "
                "inputs that drive meshing and solver setup before any discretization happens."
            ),
            what_it_shows=(
                "How the river network, geology units, and boundary align on the same domain.",
                "How geometry layers are clipped and contextualized before any mesh is generated.",
                "Where the catchment sits relative to the regional DEM backdrop.",
            ),
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "examples/data/masks/canut.shp",
                "examples/data/hydrography/regional_stream_network.shp",
                "examples/data/geology/GEO1M_brittany.shp",
                "tools/doc_gallery/update_gallery.py",
            ),
            generator="geometry_case",
            image_assets=(
                GalleryImageAsset(
                    filename="geometry_constraints_canut.png",
                    caption="Boundary, hydro network, and geology units clipped to the same domain.",
                    alt_text="Catchment geometry constraints map",
                ),
            ),
            metric_specs=_GEOMETRY_CONSTRAINT_METRIC_SPECS,
            case_setup=(
                "Domain mask sourced from the shipped `canut` polygon.",
                "Hydrography and geology layers clipped to the same boundary.",
                "Regional DEM added for context; no mesh data used.",
            ),
            metadata={
                "geometry_case_kind": "constraints_overview",
                "boundary_path": "examples/data/masks/canut.shp",
                "rivers_path": "examples/data/hydrography/regional_stream_network.shp",
                "geology_path": "examples/data/geology/GEO1M_brittany.shp",
                "dem_path": "examples/data/dem/regional_dem_naizin.tif",
            },
        ),
        GalleryCaseSpec(
            slug="geometry_topography_canut",
            title="Catchment Topography Context",
            category="geometry",
            deck="Topography and slope diagnostics shown alongside the catchment boundary.",
            summary=(
                "This case adds relief and slope context to the same geometry stack using the "
                "regional DEM. It stays mesh-free while providing visual context for elevation "
                "and terrain gradients."
            ),
            what_it_shows=(
                "Where the catchment sits on the DEM relief.",
                "How slope patterns complement elevation context.",
                "What elevation range is covered by the selected mask.",
            ),
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "examples/data/masks/canut.shp",
                "examples/data/hydrography/regional_stream_network.shp",
                "examples/data/dem/regional_dem_naizin.tif",
                "tools/doc_gallery/update_gallery.py",
            ),
            generator="geometry_case",
            image_assets=(
                GalleryImageAsset(
                    filename="geometry_topography_canut.png",
                    caption="Regional DEM with catchment boundary and river network overlays.",
                    alt_text="Catchment topography context map",
                ),
            ),
            metric_specs=_GEOMETRY_TOPO_METRIC_SPECS,
            case_setup=(
                "Regional DEM background (Naizin).",
                "Catchment boundary clipped to the same extent.",
                "Mesh-free visualization to document geometry inputs.",
            ),
            metadata={
                "geometry_case_kind": "topography_context",
                "boundary_path": "examples/data/masks/canut.shp",
                "rivers_path": "examples/data/hydrography/regional_stream_network.shp",
                "dem_path": "examples/data/dem/regional_dem_naizin.tif",
            },
        ),
        GalleryCaseSpec(
            slug="geometry_indicators_canut",
            title="Catchment Geometry Indicators",
            category="geometry",
            deck="Hypsometry and slope diagnostics derived from the regional DEM and catchment mask.",
            summary=(
                "This case focuses on geometry metrics that do not require meshing: elevation "
                "distribution, slope statistics, and a hypsometric curve computed on the masked DEM."
            ),
            what_it_shows=(
                "How elevation is distributed inside the catchment boundary.",
                "How slope metrics provide a geometry-only proxy for terrain complexity.",
                "A compact hypsometric curve suitable for documentation pages.",
            ),
            reproduction_command="python -m tools.doc_gallery",
            source_paths=(
                "examples/data/masks/canut.shp",
                "examples/data/dem/regional_dem_naizin.tif",
                "tools/doc_gallery/update_gallery.py",
            ),
            generator="geometry_case",
            image_assets=(
                GalleryImageAsset(
                    filename="geometry_indicators_canut.png",
                    caption="Hypsometric curve and slope diagnostics for the Canut mask.",
                    alt_text="Geometry indicators based on DEM and catchment mask",
                ),
            ),
            metric_specs=_GEOMETRY_INDICATOR_METRIC_SPECS,
            case_setup=(
                "Regional DEM masked by the Canut boundary.",
                "Slope estimated from DEM gradients.",
                "Hypsometric curve derived from masked elevations.",
            ),
            metadata={
                "geometry_case_kind": "hypsometry_indicators",
                "boundary_path": "examples/data/masks/canut.shp",
                "dem_path": "examples/data/dem/regional_dem_naizin.tif",
            },
        ),
    )


__all__ = ["build_geometry_specs"]
