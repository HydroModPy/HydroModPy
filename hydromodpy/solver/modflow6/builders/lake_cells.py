"""Where a lake sits on the mesh: its cells, its carved bed and its inactive footprint.

The ``_lake_*`` modules hold the geometry, the definitions, the connection rows and the
outlet rows of a lake, and ``lake.py`` builds LAK from them.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow6.builders._lake_definitions import (
    _active_lake_definitions,
)
from hydromodpy.solver.modflow6.builders._lake_geometry import (
    _abacus_stage_sarea,
    _abacus_volume,
    _drop_cutoff_wall_downstream_cells,
    _drop_interior_rings,
    _fill_lake_enclosed_cells,
    _flat_pass_through,
    _lake_bed_layers,
    _resolve_shared_lake_cells,
    interior_cells,
    polygon_overlap,
)

if TYPE_CHECKING:
    from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
    from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

logger = get_logger(__name__)


# Report the min_thickness clamp only when it moved the carved bed by more than a
# centimeter: below that the shift is re-proportioning round-off, not a geometry the
# user needs to know about.
_BED_CLAMP_REPORT_TOL = 0.01


# Share of the shore length the lakes faces must cover for the regions they enclose to
# stand for the lakes. A mesh that follows every shore reports 1 to rounding.
_CLOSED_SHORE_COVERAGE = 1.0 - 1e-6


def resolve_lake_cells(
    model,
    *,
    lake_id: str,
    polygon: object,
    cell_mesh: PlanarCellMesh,
    with_areas: bool = False,
) -> list[int] | tuple[list[int], dict[int, float]]:
    """Return the sorted cell ids of one lake polygon on the cell mesh.

    When the mesh faces follow the whole lake shore (the engine declares
    ``exact_faces`` and the ``lakes`` face family covers every shore line), the
    lake owns the regions those faces enclose that its polygon covers for most
    of their area, and each cell counts with its whole area. Otherwise it owns
    every cell its polygon overlaps by a positive area, and each cell counts
    with that overlap, so the edge cells under-fill. An empty result means the
    polygon misses the mesh, almost always a CRS or extent mistake, so we fail
    naming the lake. With ``with_areas=True`` also return the per-cell lake
    area [L2].
    """
    if _follows_lake_shores(cell_mesh):
        cells = interior_cells(cell_mesh, "lakes", polygon)
        areas = cell_mesh.geometry.areas[cells]
        if cells.size == 0 and polygon_overlap(cell_mesh, polygon)[0].size:
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id} polygon encloses no region of the "
                "lakes faces of the mesh: the mesh was built without this lake shore. "
                'Rebuild the mesh with the lake loaded, or set [mesh.families] lakes = "none".'
            )
    else:
        cells, areas = polygon_overlap(cell_mesh, polygon)
    if cells.size == 0:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} polygon does not intersect any grid "
            "cell; check the lake geometry CRS and the model extent."
        )
    cell_ids = [int(cid) for cid in cells]
    if not with_areas:
        return cell_ids
    return cell_ids, {int(cid): float(area) for cid, area in zip(cells, areas, strict=True)}


def _follows_lake_shores(cell_mesh: PlanarCellMesh) -> bool:
    """Whether the mesh faces close every lake shore.

    A family that follows the shore only in part (a generated mesh yields the
    shore where an arm is narrower than a cell) leaves the regions open, so the
    lake falls back on the overlap rule.
    """
    if not cell_mesh.qa.declarations["exact_faces"] or not cell_mesh.face_rows("lakes").any():
        return False
    covered = cell_mesh.qa.families.get("lakes", {}).get("covered_length_rel", 0.0)
    return covered >= _CLOSED_SHORE_COVERAGE


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
    that cuts a varying number of layers, deep center vs shallow rim), else
    ``occupied_layers_by_lake[lake_id]``, else the scalar ``occupied_layers``. The
    count is in grid layers, pass-through cells (``idomain = -1``) included: such a
    cell has no thickness, so a lake whose occupied layer is pinched out has no
    depth inside the stack in that column and leaks through its bed only.

    Every column must keep an active cell under the lake for the LAK VERTICAL
    connection. A column whose layers below are all pass-through or inactive is
    refused: the pinch-out has handed their thickness to the lake cap, so the lake
    would rest on the base of the model there.

    The frozen ``SolverMesh`` is left untouched; we ``dataclasses.replace`` a
    fresh ``idomain``. Applying this *before* the DISV / idomain / dem_mask
    derivations keeps RCH, EVT and DRN consistent with the lake footprint.
    """
    n_cells = int(solver_mesh.n_cells)
    nlay = int(solver_mesh.nlay)
    idomain = np.array(solver_mesh.idomain, copy=True)
    for lake_id, cell_ids in lake_cell_ids_by_lake.items():
        per_cell = (occupied_layers_by_cell or {}).get(lake_id)
        lake_layers = int(
            occupied_layers
            if occupied_layers_by_lake is None
            else occupied_layers_by_lake.get(lake_id, occupied_layers)
        )
        bottomless: list[int] = []
        flat_caps = 0
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
            if not (idomain[layers:, cell] > 0).any():
                bottomless.append(cell)
            if (idomain[:layers, cell] == -1).all():
                flat_caps += 1
            idomain[:layers, cell] = 0
        if bottomless:
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id} leaves {len(bottomless)} column(s) with "
                f"no active cell under the lake (first cell {bottomless[0]}): every layer "
                "below the occupied ones is a pass-through cell of the pinch-out "
                "(idomain -1) or inactive, so the lake would rest on the base of the model "
                "there with no bed exchange. Lower occupied_layers, lower the min_thickness "
                "of the [[domain.layers.layer]] under the lake, or set [domain.layers] "
                'pinch_out = "keep_min_thickness".'
            )
        if flat_caps:
            logger.info(
                "[LAK] lake '%s': %d column(s) occupy pass-through cells only; the lake has "
                "no depth inside the stack there and leaks through its bed into the first "
                "active cell below.",
                lake_id,
                flat_caps,
            )
    return dataclasses.replace(solver_mesh, idomain=idomain)


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

    On a stack with pass-through cells (``idomain = -1``) the cap above the bed
    takes its pass-through cells, which the lake mask then closes. Below the bed a
    pass-through cell keeps no thickness: only the cells that stay in the model are
    re-graded, so the first active cell under the lake has its top on the bed. A
    column with no such cell under its top layer is refused.

    Lakes without ``bed_reconstruction`` are left untouched. The frozen
    ``SolverMesh`` is replaced with a fresh ``botm`` (``top`` and the inactive
    mask are unchanged). The per-lake reconstruction is stashed on
    ``model._lake_bed_reconstruction`` for the abacus-comparison figure and the
    exposed-band runoff coupling; its ``bed_by_cell`` holds the bed the grid
    actually carries (after the ``min_thickness`` clamp), and
    ``diagnostics["bed_clamp_shift_max"]`` reports how far that clamp moved the
    bathymetric bed.
    """
    definitions = _active_lake_definitions(model)
    targets = {
        lake_id: definition
        for lake_id, definition in definitions.items()
        if definition.get("bed_reconstruction") is not None and lake_id in lake_cell_ids_by_lake
    }
    if not targets:
        return solver_mesh

    from hydromodpy.catchment.surface import Surface
    from hydromodpy.model.domain.lake_bed_abacus import simulate_abacus
    from hydromodpy.model.domain.lake_bed_regrid import reconstruct_lake_bed
    from hydromodpy.solver.modflow6.builders.lake_column_regrade import (
        regrade_column_active_top,
        regrade_column_to_bed,
    )

    top = np.asarray(solver_mesh.top, dtype=float).reshape(-1).copy()
    botm = np.asarray(solver_mesh.botm, dtype=float).copy()
    idomain = np.asarray(solver_mesh.idomain)
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
        # Full-pool stage: the ceiling the reconciled bed is expressed against.
        full_pool = float(stage_col[-1]) if stage_col is not None and len(stage_col) else None
        if reconcile and (stage_col is None or sarea_col is None):
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id} bed_reconstruction.reconcile_to_abacus "
                "is on but no abacus was loaded; declare [data.lake_abacus] or set "
                "reconcile_to_abacus = false."
            )

        surface = Surface.from_raster(raster, name="lake_bathymetry")
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
        # The re-grade clamps the bed into the band its column can hold at
        # min_thickness, so the elevation the grid ends up carrying is not always the
        # one the bathymetry asked for. Record the CARVED bed (post-clamp), because
        # every consumer of this record answers a question about the grid: the
        # simulated abacus measures how faithfully the mesh reproduces the
        # stage-volume curve, and the exposed-band runoff must exit at the same
        # elevation MF6 wets and dries.
        clamp_shift = 0.0
        if dynamic_area:
            # Active-littoral (marnage): the cell stays active, its TOP becomes the
            # bathymetric bed, and MF6 gates RCH/ET vs lake exchange per cell. A
            # pass-through cell stays flat; the active cells share the column.
            for cid in cell_ids:
                layers = _lake_bed_layers(idomain[:, cid], 0)
                new_top, new_botm = regrade_column_active_top(
                    orig_top=top[cid],
                    botm_col=botm[layers, cid],
                    bed=bed_by_cell[cid],
                    min_thickness=min_thickness,
                    stage_max=full_pool,
                )
                top[cid] = new_top
                botm[:, cid] = _flat_pass_through(new_top, layers, new_botm, nlay)
                clamp_shift = max(clamp_shift, abs(new_top - bed_by_cell[cid]))
                bed_by_cell[cid] = float(new_top)
            marnage_cells[lake_id] = cell_ids
        else:
            # Fixed-area reservoir: the inactive cap of each column follows the real
            # basin depth. The per-cell occupied-layer count is the number of grid
            # layers above the carved bed (deep center cells cut more layers than
            # shallow rim cells), clamped to keep one cell below that is not a
            # pass-through. The cap takes its pass-through cells with it; below the
            # bed they stay flat, so the first active cell has its top on the bed.
            per_cell_occ: dict[int, int] = {}
            for cid in cell_ids:
                kept_below = np.flatnonzero(idomain[1:, cid] != -1)
                if kept_below.size == 0:
                    raise ValueError(
                        f"flow.sinks_sources.lakes.{lake_id} bed_reconstruction: column {cid} "
                        "has no layer under its top one that is not a pass-through cell "
                        "(idomain -1), so the carved bed cannot keep an active cell under "
                        "the lake. Lower the min_thickness of the [[domain.layers.layer]] "
                        'under the lake, or set [domain.layers] pinch_out = "keep_min_thickness".'
                    )
                occ_c = int(np.count_nonzero(botm[:, cid] > bed_by_cell[cid]))
                occ_c = max(1, min(occ_c, int(kept_below[-1]) + 1))
                per_cell_occ[cid] = occ_c
                layers = _lake_bed_layers(idomain[:, cid], occ_c)
                new_botm = regrade_column_to_bed(
                    top=top[cid],
                    botm_col=botm[layers, cid],
                    bed=bed_by_cell[cid],
                    occupied_layers=occ_c,
                    min_thickness=min_thickness,
                    stage_max=full_pool,
                )
                botm[:, cid] = _flat_pass_through(top[cid], layers, new_botm, nlay)
                # regrade_column_to_bed pins the bottom of the deepest occupied layer
                # on the (clamped) bed, so that bottom IS the carved elevation.
                carved = float(botm[occ_c - 1, cid])
                clamp_shift = max(clamp_shift, abs(carved - bed_by_cell[cid]))
                bed_by_cell[cid] = carved
            occupied_by_cell[lake_id] = per_cell_occ
        if clamp_shift > _BED_CLAMP_REPORT_TOL:
            logger.warning(
                "[LAK] lake '%s': the min_thickness clamp moved the carved bed by up to "
                "%.3f m from the bathymetry (min_thickness=%.2f m). The grid, the simulated "
                "abacus and the exposed band all use the carved bed; deepen the column or "
                "lower min_thickness to follow the bathymetry more closely.",
                lake_id,
                clamp_shift,
                min_thickness,
            )
        diag = {**diag, "bed_clamp_shift_max": float(clamp_shift)}
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
            model,
            lake_id=lake_id,
            polygon=polygon,
            cell_mesh=solver_mesh.cell_mesh,
            with_areas=True,
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


__all__ = [
    "apply_lake_idomain_mask",
    "resolve_lake_cells",
    "resolve_lake_cells_for_active_lakes",
    "resolve_lake_occupied_layers",
]
