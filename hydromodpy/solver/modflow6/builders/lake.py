"""MF6 LAK package builder on a DISV grid.

The lake is a boundary package laid on the existing aquifer grid: lake cells are
made inactive (``idomain = 0``) and LAK supplies storage and exchange through its
own CONNECTIONDATA. We build that CONNECTIONDATA ourselves with
``flopy.utils.GridIntersect`` because ``flopy.mf6.utils.get_lak_connections`` does
not support embedded / horizontal lakes on DISV (it raises for unstructured grids
and only handles the trivial surface-lake case).

Each lake cell gets:

* one VERTICAL connection to the first active cell below the lake column (the
  leakage / infiltration path towards the aquifer, using K33), and
* one HORIZONTAL connection across every shared edge to an active, non-lake
  neighbour (bank seepage, using K11). ``connwidth`` is the shared-edge length,
  ``connlen`` the perpendicular half-distance from the neighbour centroid to the
  edge, and ``belev`` / ``telev`` the neighbour cell bottom / top clipped to the
  lake vertical extent.

Functions are pure and keyword-only, mirroring ``builders/wells.py``. They raise
plain ``ValueError`` naming the offending TOML path, exactly as ``wells.py`` does.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.core.units.leakance import parse_to_per_s
from hydromodpy.solver.modflow6.builders._lake_connection import (
    _abacus_rows,
    _lak_output_stem,
    _safe_lake_tag,
)
from hydromodpy.solver.modflow6.builders._lake_definitions import (
    _active_lake_definitions,
    _lake_attr,
    _scalar,
)
from hydromodpy.solver.modflow6.builders._lake_geometry import (
    _abacus_stage_sarea,
    _abacus_volume,
    _cell_behind_wall,
    _cell_edges,
    _drop_cutoff_wall_downstream_cells,
    _drop_interior_rings,
    _edge_length,
    _edge_neighbours,
    _fill_lake_enclosed_cells,
    _first_active_layer_below,
    _point_to_segment_distance,
    _resolve_shared_lake_cells,
    _wall_endpoints,
)
from hydromodpy.solver.modflow6.builders._lake_outlets import (
    _downstream_spillway_ref,
    _emit_forcing_rows,
    _emit_outlet_rate_rows,
    _emit_steady_stage_hold_rows,
    _forcing_si_per_period,
    _lake_id_for_index,
    _outlet_couttype,
    _outlet_geometry,
    _resolve_lakeout,
    _resolve_receiver_lake,
)
from hydromodpy.solver.modflow6.builders.initial_conditions import (
    read_restart_lake_stages,
    resolve_restart_from,
)
from hydromodpy.solver.modflow6.builders.mvr import (
    MoverRecord,
    build_mvr_period_records,
    mover_package_count,
)
from hydromodpy.solver.modflow6.builders.period_forcing import (
    package_unit_conversions,
    resolve_forcing_mode,
)
from hydromodpy.solver.modflow6.builders.vertex_grid import build_vertex_grid_for_intersection
from hydromodpy.solver.modflow6.common.time_series import Ts6Series

if TYPE_CHECKING:
    from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

logger = get_logger(__name__)


# CONNECTIONDATA claktype labels (FloPy passes these strings through to MF6).
_VERTICAL = "VERTICAL"
_HORIZONTAL = "HORIZONTAL"

# A leakance is non-negative. bedleak = 0 means a perfectly sealed lakebed (the
# lakebed conductance, hence the harmonic-mean lake-aquifer conductance, is 0):
# no leakage, which is a valid choice for a fully lined reservoir. Negative
# leakance is rejected.
_MIN_BEDLEAK = 0.0


def resolve_lake_cells(
    model,
    *,
    lake_id: str,
    polygon: object,
    vertex_grid: object,
    with_areas: bool = False,
) -> list[int] | tuple[list[int], dict[int, float]]:
    """Intersect one lake polygon with the grid and return the flat cell2d ids.

    Cells are returned sorted and de-duplicated. An empty result means the
    polygon misses the grid, which is almost always a CRS or extent mistake, so
    we fail naming the lake. With ``with_areas=True`` also return the per-cell
    intersected area [L2] (the part of each cell actually inside the polygon),
    which edge cells under-fill; this is the true lake area, free of the
    full-cell footprint over-count.
    """
    from flopy.utils import GridIntersect

    gi = GridIntersect(vertex_grid)
    result = gi.intersect(polygon, geo_dataframe=False)
    cell_ids = sorted({int(cid) for cid in np.asarray(result["cellids"]).ravel()})
    if not cell_ids:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} polygon does not intersect any grid "
            "cell; check the lake geometry CRS and the model extent."
        )
    if not with_areas:
        return cell_ids
    intersected: dict[int, float] = {}
    for cid, area in zip(
        np.asarray(result["cellids"]).ravel(),
        np.asarray(result["areas"]).ravel(),
        strict=True,
    ):
        intersected[int(cid)] = intersected.get(int(cid), 0.0) + float(area)
    return cell_ids, intersected


def apply_lake_idomain_mask(
    solver_mesh: SolverMesh,
    *,
    lake_cell_ids_by_lake: Mapping[str, Sequence[int]],
    occupied_layers: int = 1,
    occupied_layers_by_lake: Mapping[str, int] | None = None,
    occupied_layers_by_cell: Mapping[str, Mapping[int, int]] | None = None,
) -> SolverMesh:
    """Return a new ``SolverMesh`` with each lake's top layers made inactive.

    A lake occupies the top layers of each of its columns. The per-cell count is
    resolved in order: ``occupied_layers_by_cell[lake_id][cell]`` (a carved bed
    that cuts a varying number of layers, deep centre vs shallow rim), else
    ``occupied_layers_by_lake[lake_id]``, else the scalar ``occupied_layers``. The
    layers below stay active so the LAK VERTICAL connection has a first active
    cell to leak into; the count must leave at least one active layer per column.

    The frozen ``SolverMesh`` is left untouched; we ``dataclasses.replace`` a
    fresh inactive mask. Applying this *before* the DISV / idomain / dem_mask
    derivations keeps RCH, EVT and DRN consistent with the lake footprint.
    """
    n_cells = int(solver_mesh.n_cells)
    nlay = int(solver_mesh.nlay)
    mask = np.asarray(solver_mesh.inactive_mask, dtype=bool).copy()
    for lake_id, cell_ids in lake_cell_ids_by_lake.items():
        per_cell = (occupied_layers_by_cell or {}).get(lake_id)
        lake_layers = int(
            occupied_layers
            if occupied_layers_by_lake is None
            else occupied_layers_by_lake.get(lake_id, occupied_layers)
        )
        for cid in cell_ids:
            cell = int(cid)
            if cell < 0 or cell >= n_cells:
                raise ValueError(
                    f"flow.sinks_sources.lakes.{lake_id} cell {cell} is outside the grid "
                    f"({n_cells} cells)."
                )
            layers = int(per_cell.get(cell, lake_layers)) if per_cell is not None else lake_layers
            if layers < 1:
                raise ValueError(
                    f"flow.sinks_sources.lakes.{lake_id} occupied_layers must be >= 1."
                )
            if layers >= nlay:
                raise ValueError(
                    f"flow.sinks_sources.lakes.{lake_id} occupied_layers ({layers}) must leave at "
                    f"least one active layer below the lake (nlay={nlay}); the VERTICAL "
                    "connection needs an aquifer cell to leak into."
                )
            mask[:layers, cell] = True
    return dataclasses.replace(solver_mesh, inactive_mask=mask)


def carve_lake_bed(
    model,
    solver_mesh: SolverMesh,
    *,
    lake_cell_ids_by_lake: Mapping[str, Sequence[int]],
    occupied_layers_by_lake: Mapping[str, int] | None = None,
) -> SolverMesh:
    """Carve the real lake bed from bathymetry into ``top``/``botm`` per lake cell.

    For every active lake whose config sets ``bed_reconstruction``, the
    ``lake_bathymetry`` raster is resampled onto the lake cells (zonal mean) and,
    by default, reconciled to the abacus by area-weighted quantile mapping. Each
    lake column is then re-graded so the bottom of its deepest occupied layer sits
    at the carved bed; the first active cell below therefore exchanges with the
    lake at the real bed elevation, and the flow lines follow the real basin.

    Lakes without ``bed_reconstruction`` are left untouched. The frozen
    ``SolverMesh`` is replaced with a fresh ``botm`` (``top`` and the inactive
    mask are unchanged). The per-lake reconstruction is stashed on
    ``model._lake_bed_reconstruction`` for the abacus-comparison figure.
    """
    definitions = _active_lake_definitions(model)
    targets = {
        lake_id: definition
        for lake_id, definition in definitions.items()
        if definition.get("bed_reconstruction") is not None and lake_id in lake_cell_ids_by_lake
    }
    if not targets:
        return solver_mesh

    from hydromodpy.spatial.lake_bed import (
        load_surface_from_raster,
        reconstruct_lake_bed,
        regrade_column_active_top,
        regrade_column_to_bed,
        simulate_abacus,
    )

    top = np.asarray(solver_mesh.top, dtype=float).reshape(-1).copy()
    botm = np.asarray(solver_mesh.botm, dtype=float).copy()
    areas = solver_mesh.cell_areas()
    nlay = int(solver_mesh.nlay)
    occupied = occupied_layers_by_lake or {}
    reconstruction: dict[str, dict[str, Any]] = {}
    marnage_cells: dict[str, list[int]] = {}
    occupied_by_cell: dict[str, dict[int, int]] = {}

    for lake_id, definition in targets.items():
        cfg = definition["bed_reconstruction"]
        reconcile = bool(getattr(cfg, "reconcile_to_abacus", True))
        min_thickness = float(getattr(cfg, "min_thickness", 0.5))
        min_pixels = int(getattr(cfg, "min_pixels", 1))
        dynamic_area = bool(getattr(cfg, "dynamic_area", False))

        raster = definition.get("bathymetry")
        if not raster:
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id} sets bed_reconstruction but no "
                "lake_bathymetry raster was loaded; declare [data.lake_bathymetry]."
            )
        cell_ids = [int(c) for c in lake_cell_ids_by_lake[lake_id]]
        occ = int(occupied.get(lake_id, 1))
        # Use the per-cell intersected area (the part of each cell actually inside the
        # lake polygon) so edge cells do not over-count: the footprint then matches the
        # real lake area (area_scale -> ~1) and the abacus reconciliation is exact.
        intersected = getattr(model, "_lake_cell_intersected_area", {}).get(lake_id, {})
        area_by_cell = {cid: float(intersected.get(cid, areas[cid])) for cid in cell_ids}

        stage_col, sarea_col = _abacus_stage_sarea(definition.get("abacus"))
        if reconcile and (stage_col is None or sarea_col is None):
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id} bed_reconstruction.reconcile_to_abacus "
                "is on but no abacus was loaded; declare [data.lake_abacus] or set "
                "reconcile_to_abacus = false."
            )

        surface = load_surface_from_raster(raster)
        bed_by_cell, diag = reconstruct_lake_bed(
            planar_mesh=solver_mesh.planar_mesh,
            surface=surface,
            cell_ids=cell_ids,
            area_by_cell=area_by_cell,
            abacus_stage=stage_col if reconcile else [0.0, 1.0],
            abacus_sarea=sarea_col if reconcile else [0.0, 1.0],
            reconcile=reconcile,
            min_pixels=min_pixels,
        )
        if dynamic_area:
            # Active-littoral (marnage): the cell stays active, its TOP becomes the
            # bathymetric bed, and MF6 gates RCH/ET vs lake exchange per cell.
            for cid in cell_ids:
                new_top, new_botm = regrade_column_active_top(
                    orig_top=top[cid],
                    botm_col=botm[:, cid],
                    bed=bed_by_cell[cid],
                    min_thickness=min_thickness,
                )
                top[cid] = new_top
                botm[:, cid] = new_botm
            marnage_cells[lake_id] = cell_ids
        else:
            # Fixed-area reservoir: the inactive cap of each column follows the real
            # basin depth. The per-cell occupied-layer count is the number of grid
            # layers above the carved bed (deep centre cells cut more layers than
            # shallow rim cells), clamped to keep one active aquifer cell below.
            per_cell_occ: dict[int, int] = {}
            for cid in cell_ids:
                occ_c = int(np.count_nonzero(botm[:, cid] > bed_by_cell[cid]))
                occ_c = max(1, min(occ_c, nlay - 1))
                per_cell_occ[cid] = occ_c
                botm[:, cid] = regrade_column_to_bed(
                    top=top[cid],
                    botm_col=botm[:, cid],
                    bed=bed_by_cell[cid],
                    occupied_layers=occ_c,
                    min_thickness=min_thickness,
                )
            occupied_by_cell[lake_id] = per_cell_occ
        record = {
            "bed_by_cell": bed_by_cell,
            "area_by_cell": area_by_cell,
            "occupied_layers": occ,
            "diagnostics": diag,
            "abacus_stage": stage_col,
            "abacus_sarea": sarea_col,
            "abacus_volume": _abacus_volume(definition.get("abacus")),
        }
        if stage_col is not None:
            # Pre-compute the simulated abacus in the solver layer so the display
            # figure (which cannot import spatial) only receives plain arrays.
            sim = simulate_abacus(
                bed_by_cell=bed_by_cell, area_by_cell=area_by_cell, stages=stage_col
            )
            record["sim_volume"] = [float(v) for v in sim["volume"]]
            record["sim_sarea"] = [float(v) for v in sim["sarea"]]
        reconstruction[lake_id] = record
        logger.info(
            "[LAK] carved bed for lake '%s': %d cells, bed in [%.2f, %.2f], area scale %.3f",
            lake_id,
            len(cell_ids),
            diag.get("carved_bed_min", float("nan")),
            diag.get("carved_bed_max", float("nan")),
            diag.get("area_scale", float("nan")),
        )

    model._lake_bed_reconstruction = reconstruction
    if occupied_by_cell:
        model._lake_occupied_layers_by_cell = occupied_by_cell
    if marnage_cells:
        model._marnage_lake_ids = set(marnage_cells)
        model._marnage_lake_cells = marnage_cells
    return dataclasses.replace(solver_mesh, top=top, botm=botm)


def build_lake_connectiondata(
    model,
    *,
    lake_index: int,
    lake_cell_ids: Sequence[int],
    bedleak: float,
    solver_mesh: SolverMesh,
    occupied_layers: int = 1,
    occupied_layers_by_cell: Mapping[int, int] | None = None,
    dynamic_area: bool = False,
    cutoff_wall_line: object | None = None,
    bank_seepage: bool = True,
) -> list[list[Any]]:
    """Build the CONNECTIONDATA rows for one lake on a DISV grid.

    Rows follow the FloPy LAK layout
    ``[ifno, iconn, cellid, claktype, bedleak, belev, telev, connlen, connwidth]``
    with 0-based ``ifno`` / ``iconn`` and ``cellid = (lay, cell2d)``.

    The lake occupies the top ``occupied_layers`` layers of each lake column
    (matching ``apply_lake_idomain_mask``). For each lake column we emit:

    * one VERTICAL connection to the first active cell below the occupied layers
      (the leakage path towards the aquifer), and
    * one HORIZONTAL connection per occupied layer across every shared edge with
      an active, non-lake neighbour at that layer (bank seepage).

    ``solver_mesh`` must already carry the lake idomain mask so that
    ``idomain == 1`` identifies active non-lake neighbours.
    """
    if float(bedleak) < _MIN_BEDLEAK:
        raise ValueError(f"flow.sinks_sources.lakes bedleak must be >= 0, got {bedleak}.")

    lake_set = {int(c) for c in lake_cell_ids}
    if not lake_set:
        raise ValueError("build_lake_connectiondata requires at least one lake cell.")

    idomain = solver_mesh.idomain()  # (nlay, n_cells)
    top = np.asarray(solver_mesh.top, dtype=float)
    botm = np.asarray(solver_mesh.botm, dtype=float)  # (nlay, n_cells)
    nlay = int(solver_mesh.nlay)
    vertices = np.asarray(solver_mesh.planar_mesh.vertices, dtype=float)
    conn = solver_mesh.planar_mesh.flat_connectivity
    centroids = solver_mesh.cell_centroids()

    def _occ(cid: int) -> int:
        """Per-cell occupied-layer count (carved-bed depth), else the lake scalar."""
        if occupied_layers_by_cell is not None:
            return int(occupied_layers_by_cell.get(int(cid), occupied_layers))
        return int(occupied_layers)

    lake_cells = sorted(lake_set)

    # Dam seal: cut every HORIZONTAL bank connection to a cell BEHIND the cutoff
    # wall (across the dam from the lake body), so the lake never seeps sideways
    # past the dam. This is a LAK concern, independent of the HFB: the HFB is an
    # optional GWF-GWF barrier that does not throttle LAK-GWF flow, so the seal
    # lives here and uses only the wall trace. Vertical (bed) connections are kept.
    _wall = None
    if cutoff_wall_line is not None and not getattr(cutoff_wall_line, "is_empty", True):
        _wx = float(np.mean([centroids[c, 0] for c in lake_cells]))
        _wy = float(np.mean([centroids[c, 1] for c in lake_cells]))
        _wall = (_wall_endpoints(cutoff_wall_line), (_wx, _wy))

    def _neighbour_behind_wall(neighbour: int) -> bool:
        if _wall is None:
            return False
        (p0, p1), (bx, by) = _wall
        return _cell_behind_wall(
            float(centroids[neighbour, 0]), float(centroids[neighbour, 1]), bx, by, p0, p1
        )

    # Each cell's undirected edges, used to find shared edges with neighbours.
    cell_edges: dict[int, list[tuple[int, int]]] = {
        cid: _cell_edges(conn[cid]) for cid in range(int(solver_mesh.n_cells))
    }

    def _horizontal_rows(cid: int, lake_top: float, lake_bottom: float, occ_c: int, iconn: int):
        """HORIZONTAL bank connections of one lake column, sealed at the dam."""
        out: list[list[Any]] = []
        for lay in range(occ_c):
            for edge in cell_edges[cid]:
                width = _edge_length(vertices, edge)
                if width <= 0.0:
                    continue  # degenerate (zero-length) edge: skip
                for neighbour in _edge_neighbours(edge, cell_edges, cid):
                    if neighbour in lake_set:
                        continue  # never connect a lake to another lake cell
                    if int(idomain[lay, neighbour]) != 1:
                        continue  # neighbour inactive at this layer
                    if _neighbour_behind_wall(neighbour):
                        continue  # seal: no bank seepage across the dam
                    connlen = _point_to_segment_distance(
                        centroids[neighbour], vertices[edge[0]], vertices[edge[1]]
                    )
                    if connlen <= 0.0:
                        continue
                    belev = max(float(botm[lay, neighbour]), lake_bottom)
                    cell_top = (
                        float(top[neighbour]) if lay == 0 else float(botm[lay - 1, neighbour])
                    )
                    telev = min(cell_top, lake_top)
                    if telev <= belev:
                        continue  # neighbour cell sits outside the lake vertical extent
                    out.append(
                        [
                            int(lake_index),
                            len(out) + iconn,
                            (int(lay), int(neighbour)),
                            _HORIZONTAL,
                            float(bedleak),
                            float(belev),
                            float(telev),
                            float(connlen),
                            float(width),
                        ]
                    )
        return out

    rows: list[list[Any]] = []
    iconn = 0
    for cid in lake_cells:
        occ_c = _occ(cid)
        # This column's vertical extent: its own top down to the bottom of its
        # occupied cap (per-cell, so bank seepage clips to the real local basin).
        lake_top = float(top[cid])
        lake_bottom = float(botm[occ_c - 1, cid])
        if dynamic_area:
            # Active-littoral (marnage): the lakebed cell stays ACTIVE with the
            # bathymetric bed as its top; one VERTICAL connection on the cell itself
            # (bed seepage; MF6 wets it when stage > bed and toggles RCH/ET per cell).
            rows.append(
                [
                    int(lake_index),
                    iconn,
                    (0, int(cid)),
                    _VERTICAL,
                    float(bedleak),
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                ]
            )
            iconn += 1
        else:
            # Fixed-area: the footprint is inactive; VERTICAL to the first active
            # cell below the occupied cap.
            below_layer = _first_active_layer_below(idomain, cid, occ_c, nlay)
            if below_layer is not None:
                rows.append(
                    [
                        int(lake_index),
                        iconn,
                        (int(below_layer), int(cid)),
                        _VERTICAL,
                        float(bedleak),
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                    ]
                )
                iconn += 1

        # HORIZONTAL (bank) seepage: for a fixed-area lake always; for a marnage
        # lake only when bank_seepage is on (add the bank path to the bed one).
        if (not dynamic_area) or bank_seepage:
            hrows = _horizontal_rows(cid, lake_top, lake_bottom, occ_c, iconn)
            rows.extend(hrows)
            iconn += len(hrows)

    if not rows:
        raise ValueError(
            "Lake has no aquifer connection: every neighbour is inactive or another "
            "lake cell. Check the lake footprint and the active domain."
        )
    return rows


def build_lake_table(
    model,
    *,
    lake_id: str,
    abacus: object,
) -> list[tuple[float, float, float]]:
    """Return the ``(stage, volume, sarea)`` rows for ``ModflowUtllaktab``.

    ``abacus`` is a sequence of ``(stage, volume, sarea)`` rows or a mapping of
    those three columns. The table is sorted by stage and validated: stage must
    be strictly increasing, volume non-decreasing (``dV/dz >= 0``) and surface
    area non-negative, because MF6 interpolates the abacus and extrapolates
    poorly outside it.
    """
    rows = _abacus_rows(lake_id, abacus)
    if len(rows) < 2:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id}.abacus needs at least two rows to "
            "bracket the stage range."
        )
    rows.sort(key=lambda r: r[0])

    table: list[tuple[float, float, float]] = []
    prev_stage: float | None = None
    prev_volume: float | None = None
    prev_sarea: float | None = None
    for stage, volume, sarea in rows:
        if prev_stage is not None and stage <= prev_stage:
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id}.abacus stage must be strictly "
                f"increasing; got {stage} after {prev_stage}."
            )
        if volume < 0.0 or sarea < 0.0:
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id}.abacus volume and sarea must be "
                f">= 0; got volume={volume}, sarea={sarea}."
            )
        # MF6 lak_read_table requires strictly increasing volume and non-decreasing
        # sarea; matching it here turns an MF6-abort into a clear config error.
        if prev_volume is not None and volume <= prev_volume:
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id}.abacus volume must strictly increase "
                f"with stage (MF6 rejects equal volumes); got {volume} after {prev_volume}. "
                "Drop dead-storage rows of equal volume below the bed."
            )
        if prev_sarea is not None and sarea < prev_sarea:
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id}.abacus surface area must not decrease "
                f"with stage; got {sarea} after {prev_sarea}."
            )
        table.append((float(stage), float(volume), float(sarea)))
        prev_stage = stage
        prev_volume = volume
        prev_sarea = sarea
    return table


# Small depression depth that smooths the dry/wet behaviour and helps Newton
# convergence. It is intentionally tiny relative to lake stages.
_DEFAULT_SURFDEP = 0.1
# Fallback leakance (1/T) used until a calibratable per-lake value is declared.
_DEFAULT_BEDLEAK = 1.0


def build_lak_package_args(
    model,
    *,
    solver_mesh: SolverMesh,
    lake_cell_ids_by_lake: Mapping[str, Sequence[int]] | None = None,
    occupied_layers: int = 1,
    occupied_layers_by_cell: Mapping[str, Mapping[int, int]] | None = None,
    external_mover_to_lake: bool = False,
    downstream_reach_by_lake: Mapping[str, int] | None = None,
) -> dict[str, Any] | None:
    """Assemble the ``ModflowGwflak`` arguments for every active lake.

    Returns ``None`` when no lake is active. ``solver_mesh`` must already carry
    the lake idomain mask. The returned dict feeds ``flopy.mf6.ModflowGwflak``
    plus a per-lake ``ModflowUtllaktab`` abacus, with output filerecords and
    ``time_conversion``/``length_conversion`` consistent with the model time
    units (HMP runs TDIS in seconds, so both stay 1.0 unless declared otherwise).

    ``external_mover_to_lake`` flags an MVR record from ANOTHER package (an SFR
    terminal reach) targeting this LAK: the package then advertises MOVER and the
    obs spec requests the ``from-mvr`` series even with no lake-owned mover.
    """
    lakes = _active_lake_definitions(model)
    if not lakes:
        return None

    if lake_cell_ids_by_lake is None:
        lake_cell_ids_by_lake = resolve_lake_cells_for_active_lakes(model, solver_mesh)

    packagedata: list[list[Any]] = []
    connectiondata: list[list[Any]] = []
    tables: list[list[Any]] = []
    laktab_specs: list[dict[str, Any]] = []
    lake_conn_info: list[dict[str, Any]] = []

    # Hotstart: a prior run's Zarr (via [flow] restart_from) seeds each lake's
    # initial stage from its last value, overriding stageinit. Absent lake / older
    # store -> empty map, so the stageinit fallback below still applies.
    restart_source = resolve_restart_from(model)
    restart_stages = read_restart_lake_stages(restart_source) if restart_source else {}

    for lake_index, (lake_id, definition) in enumerate(lakes.items()):
        cell_ids = list(lake_cell_ids_by_lake.get(lake_id, []))
        if not cell_ids:
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id} resolved to no grid cell; check the "
                "lake polygon extent."
            )
        bedleak = definition.get("bedleak")
        if bedleak is None:
            logger.warning(
                "flow.sinks_sources.lakes.%s has no bedleak; using the default "
                "%s 1/s. Declare bedleak (with bedleak_unit) to control the "
                "lake-aquifer leakage.",
                lake_id,
                _DEFAULT_BEDLEAK,
            )
            bedleak_value = _DEFAULT_BEDLEAK
        else:
            bedleak_unit = definition.get("bedleak_unit")
            bedleak_value = convert_bedleak_to_per_s(
                bedleak,
                lake_id=lake_id,
                unit=str(bedleak_unit) if bedleak_unit is not None else None,
            )
        lake_layers = int(definition.get("occupied_layers") or occupied_layers)
        bed_cfg = definition.get("bed_reconstruction")
        dynamic_area = bool(getattr(bed_cfg, "dynamic_area", False))
        bank_seepage = bool(getattr(bed_cfg, "bank_seepage", True))
        rows = build_lake_connectiondata(
            model,
            lake_index=lake_index,
            lake_cell_ids=cell_ids,
            bedleak=bedleak_value,
            solver_mesh=solver_mesh,
            occupied_layers=lake_layers,
            occupied_layers_by_cell=(occupied_layers_by_cell or {}).get(lake_id),
            dynamic_area=dynamic_area,
            cutoff_wall_line=definition.get("cutoff_wall_line"),
            bank_seepage=bank_seepage,
        )
        connectiondata.extend(rows)
        # VERTICAL connections sit under the lake footprint: their per-lake iconn
        # tags the under-dam leakage the extractor sums separately.
        vertical_iconns = [int(row[1]) for row in rows if row[3] == _VERTICAL]
        lake_conn_info.append(
            {
                "lake_index": int(lake_index),
                "lake_id": str(lake_id),
                "n_conn": len(rows),
                "vertical_iconns": vertical_iconns,
            }
        )

        abacus = definition.get("abacus")
        table = build_lake_table(model, lake_id=lake_id, abacus=abacus)
        stageinit = definition.get("stageinit")
        if lake_id in restart_stages:
            strt = float(restart_stages[lake_id])
        elif stageinit is not None:
            strt = _scalar(stageinit)
        else:
            strt = float(table[0][0])

        packagedata.append([int(lake_index), strt, len(rows), str(lake_id)])
        filename = f"{_lak_output_stem(model)}.{_safe_lake_tag(lake_id)}.laktab"
        # FloPy fills the TAB6 / FILEIN keywords; the recarray row is (ifno, file).
        tables.append([int(lake_index), filename])
        laktab_specs.append({"lake_index": int(lake_index), "table": table, "filename": filename})

    outlets = build_lake_outlets(model, lakes=lakes)
    perioddata, ts_specs = build_lake_period_data(model, lakes=lakes)
    mover_records = build_mvr_period_records(
        build_lake_mover_records(
            model, lakes=lakes, downstream_reach_by_lake=downstream_reach_by_lake
        )
    )
    surfdep = max(
        (float(d["surfdep"]) for d in lakes.values() if d.get("surfdep") is not None),
        default=_DEFAULT_SURFDEP,
    )
    time_conversion, length_conversion = package_unit_conversions(model)
    stem = _lak_output_stem(model)
    obs_continuous, lake_obs_meta = build_lake_obs_spec(
        stem=stem,
        lake_conn_info=lake_conn_info,
        outlets=outlets,
        has_mover=bool(mover_records) or bool(external_mover_to_lake),
    )
    args: dict[str, Any] = {
        "nlakes": len(packagedata),
        "ntables": len(tables),
        "noutlets": len(outlets),
        "packagedata": packagedata,
        "connectiondata": connectiondata,
        "tables": tables,
        "laktab_specs": laktab_specs,
        "boundnames": True,
        "surfdep": surfdep,
        "time_conversion": time_conversion,
        "length_conversion": length_conversion,
        "print_stage": True,
        "print_flows": True,
        "save_flows": True,
        "stage_filerecord": f"{stem}.lak.stage",
        "budget_filerecord": f"{stem}.lak.cbc",
        "budgetcsv_filerecord": f"{stem}.lak.budget.csv",
    }
    # FloPy rejects empty outlets / perioddata recarrays, so only attach them when
    # populated (noutlets stays 0 when there is no spillway). perioddata is already
    # keyed by stress period (constant / TS6 rows land in period 0, inline forcings
    # spread across the periods where their value changes).
    if outlets:
        args["outlets"] = outlets
    if perioddata:
        args["perioddata"] = perioddata
    # Non-constant forcings routed to external TS6 files travel alongside the LAK
    # args so build.py can attach them to the package right after construction.
    if ts_specs:
        args["ts_specs"] = ts_specs
    # Controlled LAK -> LAK transfers ride the MVR package (built last in
    # build.py). LAK must advertise mover=True for MF6 to accept the records; the
    # records themselves and the package count travel alongside the LAK args so
    # build.py can instantiate ModflowGwfmvr once every package exists. An MVR
    # receiver must advertise MOVER too, so an external SFR -> LAK transfer also
    # raises the flag.
    if mover_records:
        args["mover_records"] = mover_records
        args["mover_maxpackages"] = mover_package_count(mover_records)
    if mover_records or external_mover_to_lake:
        args["mover"] = True
    # OBS6 definitions (stage/volume/surface-area, per-connection lake-aquifer
    # exchange, outlet) and the JSON sidecar the extractor reads at post-run.
    args["obs_continuous"] = obs_continuous
    args["lake_obs_meta"] = lake_obs_meta
    return args


def resolve_lake_cells_for_active_lakes(
    model,
    solver_mesh: SolverMesh,
) -> dict[str, list[int]]:
    """Resolve every active lake polygon to its flat cell2d ids.

    Returns ``{}`` when no lake / reservoir boundary is active, which keeps the
    LAK wiring in ``build.py`` a no-op for models without a lake. The lake
    polygons come from the loaded ``lake_geometry`` data family.
    """
    lakes = _active_lake_definitions(model)
    if not lakes:
        return {}

    vertex_grid = build_vertex_grid_for_intersection(solver_mesh)
    cells_by_lake: dict[str, list[int]] = {}
    intersected_area_by_lake: dict[str, dict[int, float]] = {}
    for lake_id, definition in lakes.items():
        polygon = definition.get("polygon")
        if polygon is None:
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id} has no polygon geometry; load the "
                "lake_geometry data family before pre-processing."
            )
        if definition.get("fill_enclosed_cells"):
            polygon = _drop_interior_rings(polygon)
        cells, intersected = resolve_lake_cells(
            model, lake_id=lake_id, polygon=polygon, vertex_grid=vertex_grid, with_areas=True
        )
        cells_by_lake[lake_id] = cells
        intersected_area_by_lake[lake_id] = intersected
    _resolve_shared_lake_cells(cells_by_lake, intersected_area_by_lake)
    _fill_lake_enclosed_cells(cells_by_lake, intersected_area_by_lake, solver_mesh)
    _drop_cutoff_wall_downstream_cells(model, cells_by_lake, intersected_area_by_lake, solver_mesh)
    # The true per-cell lake area (edge cells under-filled), used by the carve so the
    # area_scale and the abacus reconciliation see the real lake area, not the
    # full-cell footprint over-count.
    model._lake_cell_intersected_area = intersected_area_by_lake
    return cells_by_lake


def lake_definitions_for_bedleak(model) -> dict[str, dict[str, Any]]:
    """Return the active lake definitions in LAK packagedata (``ifno``) order.

    Public entry point for the calibration runtime-reuse path, which refreshes the
    ``bedleak`` column in place. The dict ordering matches the order in which
    lakes are written to the LAK package, so its index is the 0-based ``ifno``.
    """
    return _active_lake_definitions(model)


def resolve_lake_occupied_layers(model) -> dict[str, int]:
    """Return the per-lake occupied-layer count (>= 1) keyed by lake id.

    Reads the ``occupied_layers`` config field surfaced onto each lake payload,
    defaulting to 1 (surface lake). Used by ``build.py`` to thread the count into
    the idomain mask so a deep reservoir is deactivated over all of its layers.
    """
    return {
        lake_id: max(1, int(definition.get("occupied_layers") or 1))
        for lake_id, definition in _active_lake_definitions(model).items()
    }


def build_exposed_band_runoff_specs(model) -> list:
    """Build the exposed-band (marnage) runoff coupling specs, or ``[]``.

    One :class:`~hydromodpy.solver.modflow6.support.lake_band_runoff.LakeBandRunoffSpec`
    per active-littoral lake whose ``bed_reconstruction.exposed_band_runoff`` is
    on. ``lake_index`` matches the LAK packagedata order (the
    ``_active_lake_definitions`` order). The watershed runoff RATE and the lake's
    existing runoff VOLUME are read from the surfaced forcings; an SFR-routed lake
    has no direct runoff volume, so the band term is the only lake runoff.
    """
    reconstruction = getattr(model, "_lake_bed_reconstruction", None) or {}
    marnage = getattr(model, "_marnage_lake_ids", set())
    if not reconstruction or not marnage:
        return []

    from hydromodpy.solver.modflow6.support.lake_band_runoff import LakeBandRunoffSpec

    nper = int(getattr(model, "nper", 0) or 0)
    specs: list[LakeBandRunoffSpec] = []
    for lake_index, (lake_id, definition) in enumerate(_active_lake_definitions(model).items()):
        cfg = definition.get("bed_reconstruction")
        if not getattr(cfg, "exposed_band_runoff", False) or lake_id not in marnage:
            continue
        rec = reconstruction.get(lake_id)
        if rec is None:
            continue
        cells = sorted(rec["bed_by_cell"])
        specs.append(
            LakeBandRunoffSpec(
                pkg="LAK",
                lake_index=lake_index,
                bed=np.array([rec["bed_by_cell"][c] for c in cells], dtype=float),
                area=np.array([rec["area_by_cell"][c] for c in cells], dtype=float),
                rate_per_period=_forcing_si_per_period(
                    model,
                    definition.get("runoff_rate"),
                    volumetric=False,
                    label=f"flow.sinks_sources.lakes.{lake_id}.runoff_rate",
                    nper=nper,
                ),
                base_runoff_per_period=_forcing_si_per_period(
                    model,
                    definition.get("runoff"),
                    volumetric=True,
                    label=f"flow.sinks_sources.lakes.{lake_id}.runoff",
                    nper=nper,
                ),
            )
        )
    return specs


def build_lake_outlets(
    model,
    *,
    lakes: Mapping[str, dict[str, Any]],
) -> list[list[Any]]:
    """Build the OUTLETS rows for every active lake.

    Rows follow the FloPy LAK layout
    ``[outletno, lakein, lakeout, couttype, invert, width, rough, slope]`` with
    0-based ``outletno`` and ``lakein``. ``lakeout`` is ``-1`` for an external
    boundary (config ``lakeout = 0``) or the 0-based index of the downstream lake
    (config ``lakeout = N`` is the Nth lake, 1-based).

    ``invert`` / ``width`` are required for WEIR and MANNING; ``rough`` / ``slope``
    are required for MANNING and default to 0.0 otherwise; SPECIFIED outlets carry
    no geometry (their rate is supplied through ``perioddata``).
    """
    lake_index_by_id = {lake_id: idx for idx, lake_id in enumerate(lakes)}
    rows: list[list[Any]] = []
    outletno = 0
    for lake_index, (lake_id, definition) in enumerate(lakes.items()):
        outlets = definition.get("outlets") or []
        for outlet in outlets:
            couttype = _outlet_couttype(lake_id, outlet)
            lakeout = _resolve_lakeout(lake_id, outlet, lake_index_by_id)
            invert, width, rough, slope = _outlet_geometry(lake_id, couttype, outlet)
            rows.append(
                [
                    int(outletno),
                    int(lake_index),
                    int(lakeout),
                    couttype,
                    float(invert),
                    float(width),
                    float(rough),
                    float(slope),
                ]
            )
            outletno += 1
    return rows


# The single LAK package name used across the GWF model (see build.py: pname="LAK").
_LAK_PACKAGE_NAME = "LAK"
# The single SFR package name (LAK -> SFR spillway receiver); a string, never an
# import edge to builders/sfr.py.
_SFR_PACKAGE_NAME = "SFR"


def build_lake_mover_records(
    model,
    *,
    lakes: Mapping[str, dict[str, Any]],
    downstream_reach_by_lake: Mapping[str, int] | None = None,
) -> list[MoverRecord]:
    """Compile the LAK outlet ``mover`` specs into general MVR transfers.

    Each outlet carrying a ``mover`` spec becomes one :class:`MoverRecord` with
    provider ``LAK`` outlet number (0-based, assigned in the same order as
    :func:`build_lake_outlets`). The receiver is either a lake (``mover.lake``,
    1-based, translated to its packagedata position) or an SFR reach
    (``mover.reach``, 1-based, the spillway-release direction); the config
    enforces exactly one of the two.

    An outlet routed directly via ``lakeout`` (no ``mover``) is skipped while
    still advancing the shared outlet number. The ``mvrtype`` is read and
    uppercased here but validated downstream by
    :func:`build_mvr_period_records`. An empty result means no controlled transfer
    is requested.
    """
    lake_count = len(lakes)
    records: list[MoverRecord] = []
    outletno = 0
    for lake_id, definition in lakes.items():
        outlets = definition.get("outlets") or []
        for outlet in outlets:
            mover = _lake_attr(outlet, "mover")
            if mover is None:
                outletno += 1
                continue
            reach = _lake_attr(mover, "reach")
            if _lake_attr(mover, "to_downstream_reach"):
                receiver = _SFR_PACKAGE_NAME
                if downstream_reach_by_lake is None or lake_id not in downstream_reach_by_lake:
                    raise ValueError(
                        f"flow.sinks_sources.lakes.{lake_id} outlet mover to_downstream_reach "
                        "could not resolve a downstream SFR reach (no SFR channel below the dam?)."
                    )
                receiver_index = int(downstream_reach_by_lake[lake_id])
            elif reach is not None:
                receiver = _SFR_PACKAGE_NAME
                receiver_index = int(_scalar(reach)) - 1
                if receiver_index < 0:
                    raise ValueError(
                        f"flow.sinks_sources.lakes.{lake_id} outlet mover reach must be "
                        f">= 1 (1-based downstream reach); got {reach}."
                    )
            else:
                receiver = _LAK_PACKAGE_NAME
                receiver_index = _resolve_receiver_lake(lake_id, mover, lake_count)
            raw_mvrtype = _lake_attr(mover, "mvrtype")
            mvrtype = str(raw_mvrtype).strip().upper() if raw_mvrtype is not None else "FACTOR"
            raw_value = _lake_attr(mover, "value")
            value = _scalar(raw_value) if raw_value is not None else 1.0
            records.append(
                MoverRecord(
                    provider=_LAK_PACKAGE_NAME,
                    provider_id=int(outletno),
                    receiver=receiver,
                    receiver_id=int(receiver_index),
                    mvrtype=mvrtype,
                    value=value,
                )
            )
            outletno += 1
    return records


def resolve_spillway_seed_cells(
    model,
    *,
    lake_cells_by_id: Mapping[str, Sequence[int]],
    cell_adjacency: Sequence[set[int]],
    cell_centroids: np.ndarray,
    idomain: np.ndarray,
    mesh_top: np.ndarray,
    outlet_xy: tuple[float, float] | None,
) -> dict[str, int]:
    """Dam-toe cell for each lake whose spillway routes to the downstream reach.

    The seed is the cell at the foot of the dam: the lowest active non-lake neighbour of
    the lake's discharge point. The discharge point is the outlet mover's explicit
    ``discharge_xy`` when given, else the lake shoreline cell nearest the domain outlet.
    Feeding it to the SFR rectification extends the channel up to the dam, so the spillway
    feeds an SFR reach at the dam foot rather than a gap of hillslope DRN cells. Returns
    ``{lake_id: toe_cell}`` for the lakes that request it.
    """
    seeds: dict[str, int] = {}
    centroids = np.asarray(cell_centroids, dtype=float)
    top = np.asarray(mesh_top, dtype=float).reshape(-1)
    active0 = np.asarray(idomain[0] > 0)
    all_lake_cells = {int(c) for cells in lake_cells_by_id.values() for c in cells}
    for lake_id, definition in _active_lake_definitions(model).items():
        ref = _downstream_spillway_ref(definition, outlet_xy)
        if ref is None:
            continue
        ox, oy = ref
        cells = [int(c) for c in lake_cells_by_id.get(lake_id, [])]
        shore = [
            c
            for c in cells
            if any(nb not in all_lake_cells and active0[nb] for nb in cell_adjacency[c])
        ]
        if not shore:
            continue
        dam = min(shore, key=lambda c: float(np.hypot(centroids[c][0] - ox, centroids[c][1] - oy)))
        toe = [nb for nb in cell_adjacency[dam] if nb not in all_lake_cells and active0[nb]]
        if toe:
            seeds[lake_id] = int(min(toe, key=lambda c: float(top[c])))
    return seeds


def resolve_downstream_spillway_reaches(
    seed_cell_by_lake: Mapping[str, int],
    *,
    reach_cell_to_ifno: Mapping[int, int],
    cell_centroids: np.ndarray,
) -> dict[str, int]:
    """Map each spillway dam-toe seed to the 0-based SFR reach that receives its overflow.

    After the rectification seeds the dam toe (:func:`resolve_spillway_seed_cells`), that
    cell is itself a reach, so the receiver is exact. If it is not (rectification off, or
    the extension did not reach it), fall back to the nearest reach to the toe. Returns
    ``{lake_id: reach_ifno}``.
    """
    resolved: dict[str, int] = {}
    if not reach_cell_to_ifno:
        return resolved
    centroids = np.asarray(cell_centroids, dtype=float)
    for lake_id, seed in seed_cell_by_lake.items():
        if seed in reach_cell_to_ifno:
            resolved[lake_id] = int(reach_cell_to_ifno[seed])
            continue
        sx, sy = float(centroids[seed][0]), float(centroids[seed][1])
        target = min(
            reach_cell_to_ifno,
            key=lambda c: float(np.hypot(centroids[c][0] - sx, centroids[c][1] - sy)),
        )
        resolved[lake_id] = int(reach_cell_to_ifno[target])
    return resolved


# Per-lake forcing keywords and their MF6 unit convention. Rates are L/T
# (rainfall, evaporation); the rest are volumetric L^3/T.
_RATE_FORCINGS = ("rainfall", "evaporation")
_VOLUMETRIC_FORCINGS = ("runoff", "inflow", "withdrawal")


def build_lake_period_data(
    model,
    *,
    lakes: Mapping[str, dict[str, Any]],
) -> tuple[dict[int, list[list[Any]]], list[Ts6Series]]:
    """Build the LAK PERIOD rows and any external TS6 series for per-lake forcings.

    Returns ``(period_rows, ts_series)`` where ``period_rows`` maps a 0-based
    stress period to its FloPy ``[number, keyword, value]`` rows (``number`` is
    the 0-based lake index). ``rainfall`` / ``evaporation`` are converted to
    ``m/s`` (rate, L/T) and ``runoff`` / ``inflow`` / ``withdrawal`` to ``m3/s``
    (volumetric, L^3/T), the canonical SI units that match HMP's seconds-based
    TDIS.

    A constant forcing emits a single inline row in period 0 (MF6 carries it for
    the whole run). A non-constant forcing is either routed to an external TS6
    file (one period-0 row carrying the series NAME, a :class:`Ts6Series`
    accumulated in the second return value) or, when TS6 is not selected, expanded
    inline: one row is emitted in every stress period where the value changes
    (period 0 always). No declared forcing is ever dropped. The choice between TS6
    and inline expansion is made by :func:`resolve_use_ts6`. The TS6 series are
    attached to the package in ``build.py``.
    """
    mode, min_periods = resolve_forcing_mode(model)
    nper = int(getattr(model, "nper", 0) or 0)
    period_rows: dict[int, list[list[Any]]] = {}
    ts_series: list[Ts6Series] = []
    for lake_index, (lake_id, definition) in enumerate(lakes.items()):
        _emit_steady_stage_hold_rows(
            model, lake_index=lake_index, definition=definition, period_rows=period_rows
        )
        for keyword in _RATE_FORCINGS:
            _emit_forcing_rows(
                model,
                lake_index=lake_index,
                lake_id=lake_id,
                keyword=keyword,
                forcing=definition.get(keyword),
                volumetric=False,
                mode=mode,
                min_periods=min_periods,
                nper=nper,
                period_rows=period_rows,
                ts_series=ts_series,
            )
        for keyword in _VOLUMETRIC_FORCINGS:
            _emit_forcing_rows(
                model,
                lake_index=lake_index,
                lake_id=lake_id,
                keyword=keyword,
                forcing=definition.get(keyword),
                volumetric=True,
                mode=mode,
                min_periods=min_periods,
                nper=nper,
                period_rows=period_rows,
                ts_series=ts_series,
            )
    _emit_outlet_rate_rows(
        model,
        lakes=lakes,
        mode=mode,
        min_periods=min_periods,
        nper=nper,
        period_rows=period_rows,
        ts_series=ts_series,
    )
    return period_rows, ts_series


# --------------------------------------------------------------------------- #
# LAK observations (OBS6) for the per-lake output series.
# --------------------------------------------------------------------------- #

# Per-lake scalar observation types keyed by the 0-based lake number (MF6 ifno),
# mapped to the HMP-side series name the extractor stores. MF6 LAK obs cannot be
# requested by boundname through flopy (its writer increments integer ids and
# chokes on strings), so every observation uses the integer lake / connection
# number and the lake-aquifer exchange is reconstructed from the per-connection
# terms. ext-outflow / to-mvr / outlet are NOT here: MF6 keys them by outlet
# number, so they are requested in the per-outlet loop instead.
_LAKE_SCALAR_OBSTYPES: tuple[tuple[str, str], ...] = (
    ("stage", "stage"),
    ("volume", "volume"),
    ("surface-area", "surface_area"),
    ("ext-inflow", "inflow"),
    ("rainfall", "rainfall"),
    ("evaporation", "evaporation"),
    ("runoff", "runoff"),
    ("withdrawal", "withdrawal"),
    ("storage", "storage"),
)


def build_lake_obs_spec(
    *,
    stem: str,
    lake_conn_info: Sequence[Mapping[str, Any]],
    outlets: Sequence[Sequence[Any]],
    has_mover: bool = False,
) -> tuple[dict[str, list[tuple[Any, ...]]], dict[str, Any]]:
    """Return ``(obs_continuous, lake_obs_meta)`` for the LAK package.

    ``obs_continuous`` is the flopy ``continuous`` mapping ``{csv_file: [(name,
    type, id[, id2]), ...]}`` with 0-based integer ids (flopy increments them to
    MF6's 1-based convention). ``lake_obs_meta`` is the JSON-serialisable sidecar
    mapping each observation name to its lake / quantity / connection so the
    extractor can re-key the obs CSV by ``(lake_id, totim)`` and isolate the
    under-dam (VERTICAL) leakage.

    When ``has_mover`` is set the LAK package routes water through MVR, so a
    ``from-mvr`` obs is added per lake (water received from the mover, MF6 id =
    lake number) and a ``to-mvr`` obs per outlet (water sent to the mover, id =
    outlet number). These obs are only valid once the package advertises MOVER.

    Returns empty structures when no lake is present.
    """
    if not lake_conn_info:
        return {}, {"obs_csv": "", "budgetcsv": None, "entries": []}

    obs_csv = f"{stem}.lak.obs.csv"
    obslist: list[tuple[Any, ...]] = []
    entries: list[dict[str, Any]] = []

    for info in lake_conn_info:
        lake_index = int(info["lake_index"])
        lake_id = str(info["lake_id"])
        tag = _safe_lake_tag(lake_id)
        for obstype, quantity in _LAKE_SCALAR_OBSTYPES:
            obsname = f"{tag}_{quantity}"
            obslist.append((obsname, obstype, (lake_index,)))
            entries.append({"obsname": obsname, "lake_id": lake_id, "quantity": quantity})
        if has_mover:
            # from-mvr is a per-lake obs (id = lake number): water this lake
            # receives from the MVR package.
            obsname = f"{tag}_from_mvr"
            obslist.append((obsname, "from-mvr", (lake_index,)))
            entries.append({"obsname": obsname, "lake_id": lake_id, "quantity": "from_mvr"})
        vertical = {int(i) for i in info.get("vertical_iconns", [])}
        for iconn in range(int(info["n_conn"])):
            obsname = f"{tag}_lak_{iconn}"
            obslist.append((obsname, "lak", (lake_index,), (iconn,)))
            entries.append(
                {
                    "obsname": obsname,
                    "lake_id": lake_id,
                    "quantity": "lak_connection",
                    "iconn": iconn,
                    "under_dam": iconn in vertical,
                }
            )

    for outletno, outlet in enumerate(outlets):
        lake_index = int(outlet[1])
        lake_id = _lake_id_for_index(lake_conn_info, lake_index)
        tag = _safe_lake_tag(lake_id)
        obsname = f"{tag}_outlet_{outletno}"
        obslist.append((obsname, "outlet", (outletno,)))
        entries.append({"obsname": obsname, "lake_id": lake_id, "quantity": "outlet"})
        # ext-outflow is keyed by outlet number, so it belongs here, not in the
        # per-lake loop (requesting it by lake number errors once the lake index
        # exceeds the outlet count).
        ext_name = f"{tag}_ext_outflow_{outletno}"
        obslist.append((ext_name, "ext-outflow", (outletno,)))
        entries.append({"obsname": ext_name, "lake_id": lake_id, "quantity": "ext_outflow"})
        if has_mover:
            # to-mvr is a per-outlet obs (id = outlet number): water this outlet
            # sends to the MVR package (0 for an outlet not routed through MVR).
            mvr_name = f"{tag}_to_mvr_{outletno}"
            obslist.append((mvr_name, "to-mvr", (outletno,)))
            entries.append({"obsname": mvr_name, "lake_id": lake_id, "quantity": "to_mvr"})

    obs_continuous = {obs_csv: obslist}
    lake_obs_meta = {
        "obs_csv": obs_csv,
        "budgetcsv": f"{stem}.lak.budget.csv",
        "entries": entries,
    }
    return obs_continuous, lake_obs_meta


def convert_bedleak_to_per_s(value: object, *, lake_id: str, unit: str | None = None) -> float:
    """Convert one ``bedleak`` declaration (1/T) to ``1/s`` for MF6.

    HMP runs MF6 in seconds, so a legacy ``1/day`` leakance must reach the LAK
    package in ``1/s``. The canonical SI value is returned.
    """
    return parse_to_per_s(
        value,
        location=f"flow.sinks_sources.lakes.{lake_id}.bedleak",
        default_unit="1/s",
        explicit_unit=unit,
    )[0]


__all__ = [
    "apply_lake_idomain_mask",
    "build_lak_package_args",
    "build_lake_connectiondata",
    "build_lake_mover_records",
    "build_lake_obs_spec",
    "build_lake_outlets",
    "build_lake_period_data",
    "build_lake_table",
    "convert_bedleak_to_per_s",
    "lake_definitions_for_bedleak",
    "resolve_downstream_spillway_reaches",
    "resolve_lake_cells",
    "resolve_spillway_seed_cells",
    "resolve_lake_cells_for_active_lakes",
    "resolve_lake_occupied_layers",
]
