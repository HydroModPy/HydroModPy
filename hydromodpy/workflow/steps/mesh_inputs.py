"""Gather what the mesh planner reads besides ``[mesh]`` from the run context."""

from __future__ import annotations

from itertools import combinations
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from hydromodpy.core.exceptions import MeshError
from hydromodpy.spatial.geographic.core.derived_features import resolve_river_mesh_trace
from hydromodpy.spatial.mesh import registry
from hydromodpy.spatial.mesh.config.mesh import MeshConfig
from hydromodpy.spatial.mesh.planning import (
    CriterionInputs,
    LakeStructure,
    PlanningInputs,
    geology_lines,
    load_refinement_zones,
    read_input_triangulation,
    support_contacts,
)
from hydromodpy.spatial.mesh.planning.geology import GeologyLines
from hydromodpy.spatial.mesh.refinement.lake_refinement import LakeRefinementConfig
from hydromodpy.spatial.mesh.request import RasterGridSpec
from hydromodpy.workflow.steps.mesh_run_fields import read_run_fields

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext

__all__ = ["barrier_lines", "hydraulic_feature_geometries", "mesh_crs_wkt", "planning_inputs"]


def planning_inputs(ctx: WorkflowContext, mesh_cfg: MeshConfig) -> PlanningInputs:
    """Return the project inputs of the mesh request of *mesh_cfg*."""
    setup, cfg = ctx.setup, ctx.cfg
    crs_wkt = mesh_crs_wkt(setup)
    grid = RasterGridSpec.from_raster_support(setup.domain.surface_topo.support, crs_wkt=crs_wkt)
    synthetic = bool(cfg.geographic.uses_synthetic_geographic())
    active_bc = {str(bc).strip().lower() for bc in cfg.flow.active_bc}
    graded = registry.get(mesh_cfg.engine).capabilities.graded
    reads_catchment = graded or mesh_cfg.families.watershed_boundary == "face"
    triangle = mesh_cfg.triangle
    sized = graded and (triangle is None or triangle.path is None)
    geology, notes = _geology_contacts(ctx, mesh_cfg, crs_wkt, grid)
    river_trace = _river_trace(setup, mesh_cfg, active_bc=active_bc, synthetic=synthetic)
    return PlanningInputs(
        dem_grid=grid,
        crs_wkt=crs_wkt,
        domain=_domain_polygon(setup, cfg.geographic, grid, crs_wkt, synthetic),
        river_trace=river_trace,
        watershed=_watershed(setup, crs_wkt) if reads_catchment and not synthetic else None,
        lakes=_lake_polygons(setup),
        lake_structures=lake_structures(setup, cfg.geographic, mesh_cfg.lake_refinement),
        geology=geology,
        refinement_zones=load_refinement_zones(
            mesh_cfg.refinement_zone,
            config_dir=Path(ctx.config_path).parent,
            data_dir=_data_dir(setup),
            crs_wkt=crs_wkt,
            criteria=_criterion_inputs(setup, mesh_cfg, grid, river_trace) if sized else None,
        ),
        input_triangulation=(
            None
            if triangle is None or triangle.path is None
            else read_input_triangulation(triangle.path)
        ),
        synthetic=synthetic,
        barriers=barrier_lines(setup) if mesh_cfg.families.barriers == "face" else (),
        outlet=_declared_outlet(cfg.geographic),
        notes=notes,
    )


def _criterion_inputs(
    setup: object, mesh_cfg: MeshConfig, grid: RasterGridSpec, river_trace: object | None
) -> CriterionInputs | None:
    """What the zones drawn by a threshold read, None when no zone is drawn so.

    The DEM is the model top on the mesh grid. The streams are the river
    network traced from the DEM, never a mapped one. The fields of earlier
    runs are read under the project root.
    """
    zones = mesh_cfg.refinement_zone
    if not any(zone.where is not None for zone in zones):
        return None
    elevation = np.asarray(setup.domain.surface_topo.as_array(), dtype=float)
    if elevation.shape != (grid.nrow, grid.ncol):
        raise MeshError(
            f"the model top holds {elevation.shape} values, the mesh grid is "
            f"{(grid.nrow, grid.ncol)}"
        )
    nodata = getattr(setup.domain.surface_topo.support, "nodata", None)
    if nodata is not None:
        elevation = np.where(elevation == float(nodata), np.nan, elevation)
    lines = None
    if mesh_cfg.refines_above_stream():
        trace = river_trace or resolve_river_mesh_trace(
            geographic_features=setup.geographic_features
        )
        lines = None if trace is None else tuple(trace.lines)
    run_fields = {}
    if any(zone.run is not None for zone in zones):
        workspace = getattr(setup, "workspace", None)
        if workspace is None:
            raise MeshError(
                "A refinement zone reads an earlier run of the project, and no workspace is set up."
            )
        run_fields = read_run_fields(Path(workspace.project_root), zones)
    return CriterionInputs(
        grid=grid, elevation=elevation, stream_lines=lines, run_fields=run_fields
    )


def mesh_crs_wkt(setup: object) -> str:
    """Return the WKT of the run's projected CRS: geographic first, then the DEM support."""
    from pyproj import CRS

    geographic = getattr(setup, "geographic", None)
    declared = getattr(geographic, "crs_project", None) or getattr(geographic, "crs_proj", None)
    if not declared:
        surface = getattr(getattr(setup, "domain", None), "surface_topo", None)
        declared = getattr(getattr(surface, "support", None), "crs", None)
    if not declared:
        raise MeshError(
            "The cell mesh needs the run's CRS: neither the geographic setup nor the DEM "
            "surface support declares one. Set [geographic] crs_project."
        )
    return CRS.from_user_input(declared).to_wkt()


def _data_dir(setup: object) -> Path | None:
    workspace = getattr(setup, "workspace", None)
    data_dir = getattr(workspace, "data_dir", None)
    return None if data_dir is None else Path(data_dir)


def _domain_polygon(
    setup: object, geographic_cfg: object, grid: RasterGridSpec, crs_wkt: str, synthetic: bool
) -> Polygon:
    """The polygon of the active extent: the DEM rectangle, or the catchment (buffered or not)."""
    extent = geographic_cfg.domain_extent
    if synthetic or extent == "box":
        return box(grid.xmin, grid.ymin, grid.xmax, grid.ymax)
    watershed_shp = Path(str(setup.domain_geographic.watershed_shp))
    path = watershed_shp if extent == "watershed" else watershed_shp.with_name("watershed_buff.shp")
    polygon = _read_polygon(path, crs_wkt)
    if polygon is None:
        raise MeshError(
            f"geographic.domain_extent = {extent!r} needs the polygon {path}, not found."
        )
    return polygon


def _watershed(setup: object, crs_wkt: str) -> Polygon | None:
    """The catchment polygon, or None when the run has no delineated catchment."""
    domain_geographic = getattr(setup, "domain_geographic", None)
    shp = getattr(domain_geographic, "watershed_shp", None)
    return None if shp is None else _read_polygon(Path(str(shp)), crs_wkt)


def _read_polygon(path: Path, crs_wkt: str) -> Polygon | None:
    """The union of the polygons of a vector file in the CRS *crs_wkt*, or None without the file."""
    if not path.is_file():
        return None
    import geopandas as gpd

    frame = gpd.read_file(path)
    frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty]
    if frame.empty:
        raise MeshError(f"{path} holds no polygon.")
    if frame.crs is not None:
        frame = frame.to_crs(crs_wkt)
    union = unary_union(list(frame.geometry))
    if isinstance(union, Polygon):
        return union
    return max(getattr(union, "geoms", ()), key=lambda part: part.area, default=None)


def _river_trace(
    setup: object, mesh_cfg: MeshConfig, *, active_bc: set[str], synthetic: bool
) -> object | None:
    """The traced river network when the mesh follows it, failing when none was traced."""
    if not mesh_cfg.requires_river_trace(active_bc=active_bc, synthetic=synthetic):
        return None
    trace = resolve_river_mesh_trace(geographic_features=setup.geographic_features)
    if trace is None:
        raise MeshError(
            f'mesh.engine = "{mesh_cfg.engine}" follows the rivers, and no river network was '
            "traced from the DEM. Enable [geographic.river_network] with a threshold, or set "
            '[mesh.families] rivers = "none".'
        )
    return trace


def _lake_payloads(setup: object) -> dict:
    flow = getattr(setup, "flow", None)
    lakes = getattr(flow, "sinks_sources", {}).get("lakes", {}) if flow is not None else {}
    return lakes if isinstance(lakes, dict) else {}


def _lake_polygons(setup: object) -> tuple[Polygon, ...]:
    """The footprints of the lakes bound on the flow payload."""
    return tuple(
        payload["polygon"]
        for payload in _lake_payloads(setup).values()
        if isinstance(payload, dict) and payload.get("polygon") is not None
    )


def barrier_lines(setup: object) -> tuple[LineString, ...]:
    """The lines of the flow barriers: each lake cutoff wall, then each general barrier.

    A lake wall is the line laid on the lake shore, a general barrier its
    resolved trace; both are bound on the flow payload before the mesh step.
    """
    flow = getattr(setup, "flow", None)
    barriers = getattr(flow, "sinks_sources", {}).get("flow_barriers") if flow is not None else None
    found = [
        *((payload, "cutoff_wall_line") for payload in _lake_payloads(setup).values()),
        *((payload, "line") for payload in (barriers or {}).values()),
    ]
    lines = (payload.get(key) for payload, key in found if isinstance(payload, dict))
    return tuple(line for line in lines if line is not None and not line.is_empty)


def lake_structures(
    setup: object, geographic_cfg: object, lake_cfg: LakeRefinementConfig | None
) -> tuple[LakeStructure, ...]:
    """The hydraulic structures of the lakes to refine, none without ``[mesh.lake_refinement]``."""
    if lake_cfg is None:
        return ()
    structures = hydraulic_feature_geometries(setup, lake_cfg)
    outlet = _declared_outlet(geographic_cfg)
    if outlet is not None:
        # The outlet disk is redundant only when a cutoff-wall zone actually reaches
        # it: the wall zone (radius = its buffer) must overlap the disk (dam_buffer).
        has_cutoff_wall = any(
            label.startswith("voile:")
            and float(geometry.distance(outlet)) <= float(width) + float(lake_cfg.dam_buffer)
            for label, geometry, _size, width in structures
        )
        if lake_cfg.dam_outlet_disk is True or (
            lake_cfg.dam_outlet_disk is None and not has_cutoff_wall
        ):
            structures.append(("dam_outlet", outlet, lake_cfg.dam_cell_size, lake_cfg.dam_buffer))
    return tuple(structures)


def _declared_outlet(geographic_cfg: object) -> Point | None:
    """The outlet the configuration declares, in the project CRS, None without one."""
    x_outlet = getattr(geographic_cfg, "x_outlet", None)
    y_outlet = getattr(geographic_cfg, "y_outlet", None)
    if x_outlet is None or y_outlet is None:
        return None
    return Point(float(x_outlet), float(y_outlet))


def hydraulic_feature_geometries(setup: object, lake_cfg: object) -> list[LakeStructure]:
    """Collect ``(label, geometry, target size, zone buffer)`` refinement targets.

    So each structure resolves cleanly on the mesh: the dam cutoff wall (voile)
    line at ``dam_cell_size``, dilated by ``hfb_buffer`` into a zone wide enough
    to cover the lake outlet, and the sill between every pair of coupled lakes
    (the shortest segment between the two footprints). The SILL size is forced
    BELOW the lake-to-lake gap (0.4 * gap), else a single cell straddles both
    lakes and MF6 LAK rejects the model (one lake per cell).
    """
    lakes = _lake_payloads(setup)
    dam_cell_size = float(lake_cfg.dam_cell_size)
    dam_buffer = float(lake_cfg.dam_buffer)
    hfb_buffer = lake_cfg.hfb_buffer
    hfb_width = float(hfb_buffer) if hfb_buffer is not None else 2.0 * dam_buffer
    features: list[LakeStructure] = []
    for lake_id, payload in lakes.items():
        if not isinstance(payload, dict):
            continue
        line = payload.get("cutoff_wall_line")
        if line is not None and not line.is_empty:
            features.append((f"voile:{lake_id}", line, dam_cell_size, hfb_width))
    # Sill between every pair of lakes: refine the WHOLE proximity zone, not just the
    # nearest point, so no cell along the sill straddles both footprints.
    polygons = {
        lake_id: payload["polygon"]
        for lake_id, payload in lakes.items()
        if isinstance(payload, dict) and payload.get("polygon") is not None
    }
    for (first_id, first), (second_id, second) in combinations(polygons.items(), 2):
        gap = float(first.distance(second))
        if gap <= 0.0:
            continue  # overlapping or touching footprints cannot be separated by refinement
        sill_size = max(5.0, min(dam_cell_size, 0.4 * gap))
        margin = max(1.5 * gap, dam_cell_size)
        sill_zone = _sill_zone(first, second, margin, sill_size=sill_size)
        if not sill_zone.is_empty:
            features.append((f"sill:{first_id}-{second_id}", sill_zone, sill_size, margin))
    return features


def _sill_zone(
    first: BaseGeometry, second: BaseGeometry, margin: float, *, sill_size: float
) -> BaseGeometry:
    """The overlap of the two lakes dilated by *margin*, from simplified outlines.

    A DEM-traced reservoir holds some 17 000 vertices, and its raw buffer cost
    16 to 20 s per build. The outlines are simplified first at a tenth of the
    sill size, far below the cells placed there, so the zone moves by less than
    that tolerance.
    """
    tolerance = 0.1 * float(sill_size)
    dilated = [
        geometry.simplify(tolerance, preserve_topology=True).buffer(margin)
        for geometry in (first, second)
    ]
    zone = dilated[0].intersection(dilated[1])
    return zone.simplify(tolerance, preserve_topology=True)


def _geology_contacts(
    ctx: WorkflowContext, mesh_cfg: MeshConfig, crs_wkt: str, grid: RasterGridSpec
) -> tuple[GeologyLines | None, tuple[str, ...]]:
    """The contacts of the zones a flow parameter reads, and the notes.

    The zones are the polygons of a custom vector source of ``[data.geology]``, or,
    for an engine that follows its face lines exactly and generates its own mesh, the
    bands and rings of an analytical support. The national maps and the rasters reach the model
    rasterized, with no contact to follow, which the notes say.
    """
    from hydromodpy.workflow.steps.setup import (
        collect_requested_support_ids,
        resolve_support_configs,
    )

    if mesh_cfg.families.geology != "face":
        return None, ()
    supports = resolve_support_configs(ctx.cfg.domain, collect_requested_support_ids(ctx.cfg.flow))
    reads_triangulation = mesh_cfg.triangle is not None and mesh_cfg.triangle.path is not None
    if not reads_triangulation and registry.get(mesh_cfg.engine).capabilities.exact_faces:
        bounds = (grid.xmin, grid.ymin, grid.xmax, grid.ymax)
        for support in supports.values():
            contacts = support_contacts(support, bounds)
            if contacts is not None:
                return contacts, ()
    if not any(getattr(support, "kind", None) == "geology" for support in supports.values()):
        return None, ()
    geology = ctx.cfg.data.geology
    source = next(
        (
            source
            for source in (geology.sources if geology is not None else ())
            if source.source == "custom" and source.code_field
        ),
        None,
    )
    skipped = (
        "families.geology = face found no vector geology map: the zones are sampled on the "
        "cells and no face follows a contact"
    )
    if source is None:
        return None, (skipped,)
    contacts = geology_lines(
        {"id": geology.id, "source": {"path": str(source.path), "code_field": source.code_field}},
        config_path=ctx.config_path,
        crs_wkt=crs_wkt,
    )
    return contacts, (() if contacts is not None else (skipped,))
