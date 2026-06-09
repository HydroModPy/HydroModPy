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
from numbers import Real
from typing import TYPE_CHECKING, Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.core.units.hydraulic_conductivity import parse_to_m_per_s
from hydromodpy.core.units.leakance import parse_to_per_s
from hydromodpy.core.units.volumetric_flow import parse_to_m3_per_s
from hydromodpy.physics.flow.time_forcing import resolve_period_values_from_forcing
from hydromodpy.solver.modflow6.builders.mvr import (
    MoverRecord,
    build_mvr_period_records,
    mover_package_count,
)
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


def build_vertex_grid_for_intersection(solver_mesh: SolverMesh):
    """Return a standalone ``flopy.discretization.VertexGrid`` for the lake polygon.

    The LAK builder runs *before* the DISV package is registered on the GWF
    model, so we rebuild a vertex grid from ``solver_mesh.to_disv_kwargs()``.
    The DISV vertices already carry absolute model coordinates, hence
    ``xoff = yoff = 0``. ``idomain`` is the PRE-lake active domain so the
    intersection sees the real footprint.
    """
    from flopy.discretization import VertexGrid

    disv_kwargs = solver_mesh.to_disv_kwargs()
    return VertexGrid(
        vertices=disv_kwargs["vertices"],
        cell2d=disv_kwargs["cell2d"],
        top=np.asarray(solver_mesh.top, dtype=float),
        botm=np.asarray(solver_mesh.botm, dtype=float),
        idomain=solver_mesh.idomain(),
        nlay=int(solver_mesh.nlay),
        ncpl=int(solver_mesh.n_cells),
        xoff=0.0,
        yoff=0.0,
    )


def resolve_lake_cells(
    model,
    *,
    lake_id: str,
    polygon: object,
    vertex_grid: object,
) -> list[int]:
    """Intersect one lake polygon with the grid and return the flat cell2d ids.

    Cells are returned sorted and de-duplicated. An empty result means the
    polygon misses the grid, which is almost always a CRS or extent mistake, so
    we fail naming the lake.
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
    return cell_ids


def apply_lake_idomain_mask(
    solver_mesh: SolverMesh,
    *,
    lake_cell_ids_by_lake: Mapping[str, Sequence[int]],
    occupied_layers: int = 1,
    occupied_layers_by_lake: Mapping[str, int] | None = None,
) -> SolverMesh:
    """Return a new ``SolverMesh`` with each lake's top layers made inactive.

    A lake occupies the top layers of each of its columns: ``occupied_layers``
    applies to every lake unless ``occupied_layers_by_lake`` overrides it per lake
    id (a surface lake fills only layer 0; a deep reservoir fills several). The
    layers below stay active so the LAK VERTICAL connection has a first active
    cell to leak into; the count must leave at least one active layer per lake
    column, otherwise the column has nothing to connect to.

    The frozen ``SolverMesh`` is left untouched; we ``dataclasses.replace`` a
    fresh inactive mask. Applying this *before* the DISV / idomain / dem_mask
    derivations keeps RCH, EVT and DRN consistent with the lake footprint.
    """
    n_cells = int(solver_mesh.n_cells)
    nlay = int(solver_mesh.nlay)
    mask = np.asarray(solver_mesh.inactive_mask, dtype=bool).copy()
    for lake_id, cell_ids in lake_cell_ids_by_lake.items():
        layers = int(
            occupied_layers
            if occupied_layers_by_lake is None
            else occupied_layers_by_lake.get(lake_id, occupied_layers)
        )
        if layers < 1:
            raise ValueError(f"flow.sinks_sources.lakes.{lake_id} occupied_layers must be >= 1.")
        if layers >= nlay:
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id} occupied_layers ({layers}) must leave at "
                f"least one active layer below the lake (nlay={nlay}); the VERTICAL connection "
                "needs an aquifer cell to leak into."
            )
        for cid in cell_ids:
            cell = int(cid)
            if cell < 0 or cell >= n_cells:
                raise ValueError(
                    f"flow.sinks_sources.lakes.{lake_id} cell {cell} is outside the grid "
                    f"({n_cells} cells)."
                )
            mask[:layers, cell] = True
    return dataclasses.replace(solver_mesh, inactive_mask=mask)


def _cell_edges(nodes: Sequence[int]) -> list[tuple[int, int]]:
    """Return the undirected edges (sorted vertex pairs) of one cell polygon."""
    seq = [int(n) for n in nodes]
    return [
        tuple(sorted((seq[i], seq[(i + 1) % len(seq)])))  # type: ignore[misc]
        for i in range(len(seq))
    ]


def _edge_length(vertices: np.ndarray, edge: tuple[int, int]) -> float:
    """Return the Euclidean length of one mesh edge."""
    a = vertices[edge[0]]
    b = vertices[edge[1]]
    return float(np.hypot(b[0] - a[0], b[1] - a[1]))


def _point_to_segment_distance(point: np.ndarray, seg_a: np.ndarray, seg_b: np.ndarray) -> float:
    """Return the perpendicular distance from a point to a segment's line.

    For a Voronoi mesh the neighbour centroid projects onto the shared edge, so
    this is the exact half cell-to-cell distance (CVFD ``connlen``). For other
    meshes it is the best local estimate.
    """
    ab = seg_b - seg_a
    length_sq = float(ab[0] ** 2 + ab[1] ** 2)
    if length_sq == 0.0:
        return float(np.hypot(point[0] - seg_a[0], point[1] - seg_a[1]))
    # Signed area / base length = perpendicular distance to the supporting line.
    ap = point - seg_a
    cross = float(ab[0] * ap[1] - ab[1] * ap[0])
    return abs(cross) / float(np.sqrt(length_sq))


def build_lake_connectiondata(
    model,
    *,
    lake_index: int,
    lake_cell_ids: Sequence[int],
    bedleak: float,
    solver_mesh: SolverMesh,
    occupied_layers: int = 1,
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

    # Lake vertical extent across the footprint: top of the highest occupied cell
    # down to the bottom of the deepest occupied layer.
    lake_cells = sorted(lake_set)
    lake_top = float(np.max(top[lake_cells]))
    lake_bottom = float(np.min(botm[occupied_layers - 1, lake_cells]))

    # Each cell's undirected edges, used to find shared edges with neighbours.
    cell_edges: dict[int, list[tuple[int, int]]] = {
        cid: _cell_edges(conn[cid]) for cid in range(int(solver_mesh.n_cells))
    }

    rows: list[list[Any]] = []
    iconn = 0
    for cid in lake_cells:
        # VERTICAL: connect to the first active cell below the occupied layers.
        below_layer = _first_active_layer_below(idomain, cid, occupied_layers, nlay)
        if below_layer is not None:
            rows.append(
                [
                    int(lake_index),
                    int(iconn),
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

        # HORIZONTAL: per occupied layer, one connection per shared edge with an
        # active non-lake neighbour at that layer.
        for lay in range(occupied_layers):
            for edge in cell_edges[cid]:
                width = _edge_length(vertices, edge)
                if width <= 0.0:
                    continue  # degenerate (zero-length) edge: skip
                for neighbour in _edge_neighbours(edge, cell_edges, cid):
                    if neighbour in lake_set:
                        continue  # never connect a lake to another lake cell
                    if int(idomain[lay, neighbour]) != 1:
                        continue  # neighbour inactive at this layer
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
                    rows.append(
                        [
                            int(lake_index),
                            int(iconn),
                            (int(lay), int(neighbour)),
                            _HORIZONTAL,
                            float(bedleak),
                            float(belev),
                            float(telev),
                            float(connlen),
                            float(width),
                        ]
                    )
                    iconn += 1

    if not rows:
        raise ValueError(
            "Lake has no aquifer connection: every neighbour is inactive or another "
            "lake cell. Check the lake footprint and the active domain."
        )
    return rows


def _first_active_layer_below(
    idomain: np.ndarray, cell_id: int, occupied_layers: int, nlay: int
) -> int | None:
    """Return the first active layer below the lake's occupied layers, or None."""
    for lay in range(occupied_layers, nlay):
        if int(idomain[lay, cell_id]) == 1:
            return lay
    return None


def _edge_neighbours(
    edge: tuple[int, int],
    cell_edges: Mapping[int, list[tuple[int, int]]],
    owner: int,
) -> list[int]:
    """Return the cells (other than ``owner``) that share one edge."""
    return [cid for cid, edges in cell_edges.items() if cid != owner and edge in edges]


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
        if prev_volume is not None and volume < prev_volume:
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id}.abacus volume must not decrease "
                f"with stage (dV/dz >= 0); got {volume} after {prev_volume}."
            )
        table.append((float(stage), float(volume), float(sarea)))
        prev_stage = stage
        prev_volume = volume
    return table


def _abacus_rows(lake_id: str, abacus: object) -> list[tuple[float, float, float]]:
    """Coerce one abacus payload to a list of ``(stage, volume, sarea)`` tuples."""
    if abacus is None:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id}.abacus is required to build the LAK "
            "stage-volume-area table."
        )
    if isinstance(abacus, Mapping):
        stage = np.asarray(abacus["stage"], dtype=float).ravel()
        volume = np.asarray(abacus["volume"], dtype=float).ravel()
        sarea = np.asarray(abacus["sarea"], dtype=float).ravel()
        if not (stage.size == volume.size == sarea.size):
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id}.abacus stage, volume and sarea "
                "columns must have the same length."
            )
        return [
            (float(s), float(v), float(a)) for s, v, a in zip(stage, volume, sarea, strict=True)
        ]

    if not isinstance(abacus, Sequence):
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id}.abacus must be a mapping of "
            "stage/volume/sarea columns or a sequence of (stage, volume, sarea) rows."
        )
    rows: list[tuple[float, float, float]] = []
    for entry in abacus:
        triple = tuple(float(x) for x in entry)
        if len(triple) != 3:
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id}.abacus rows must be (stage, volume, sarea)."
            )
        rows.append((triple[0], triple[1], triple[2]))
    return rows


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
) -> dict[str, Any] | None:
    """Assemble the ``ModflowGwflak`` arguments for every active lake.

    Returns ``None`` when no lake is active. ``solver_mesh`` must already carry
    the lake idomain mask. The returned dict feeds ``flopy.mf6.ModflowGwflak``
    plus a per-lake ``ModflowUtllaktab`` abacus, with output filerecords and
    ``time_conversion``/``length_conversion`` consistent with the model time
    units (HMP runs TDIS in seconds, so both stay 1.0 unless declared otherwise).
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
        rows = build_lake_connectiondata(
            model,
            lake_index=lake_index,
            lake_cell_ids=cell_ids,
            bedleak=bedleak_value,
            solver_mesh=solver_mesh,
            occupied_layers=lake_layers,
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
        strt = _scalar(stageinit) if stageinit is not None else float(table[0][0])

        packagedata.append([int(lake_index), strt, len(rows), str(lake_id)])
        filename = f"{_lak_output_stem(model)}.{_safe_lake_tag(lake_id)}.laktab"
        # FloPy fills the TAB6 / FILEIN keywords; the recarray row is (ifno, file).
        tables.append([int(lake_index), filename])
        laktab_specs.append({"lake_index": int(lake_index), "table": table, "filename": filename})

    outlets = build_lake_outlets(model, lakes=lakes)
    perioddata, ts_specs = build_lake_period_data(model, lakes=lakes)
    mover_records = build_mvr_period_records(build_lake_mover_records(model, lakes=lakes))
    time_conversion, length_conversion = _lak_unit_conversions(model)
    stem = _lak_output_stem(model)
    obs_continuous, lake_obs_meta = build_lake_obs_spec(
        stem=stem,
        lake_conn_info=lake_conn_info,
        outlets=outlets,
        has_mover=bool(mover_records),
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
        "surfdep": _DEFAULT_SURFDEP,
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
    # build.py can instantiate ModflowGwfmvr once every package exists.
    if mover_records:
        args["mover"] = True
        args["mover_records"] = mover_records
        args["mover_maxpackages"] = mover_package_count(mover_records)
    # OBS6 definitions (stage/volume/surface-area, per-connection lake-aquifer
    # exchange, outlet) and the JSON sidecar the extractor reads at post-run.
    args["obs_continuous"] = obs_continuous
    args["lake_obs_meta"] = lake_obs_meta
    return args


def _scalar(value: object) -> float:
    """Coerce a plain number or a pint Quantity to a float magnitude."""
    magnitude = getattr(value, "magnitude", value)
    return float(magnitude)  # type: ignore[arg-type]


def _lak_output_stem(model) -> str:
    """Return the output file stem for LAK files (mirrors model.model_output_name)."""
    name = getattr(model, "model_output_name", None)
    if name:
        return str(name)
    return str(getattr(model, "model_name", "") or "model")


def _safe_lake_tag(lake_id: str) -> str:
    """Return a filename-safe tag for one lake id."""
    return "".join(ch if ch.isalnum() else "_" for ch in str(lake_id))


def _lak_unit_conversions(model) -> tuple[float, float]:
    """Return ``(time_conversion, length_conversion)`` for the LAK outlets.

    MF6 LAK needs these only to scale MANNING/WEIR outlet flow into the model's
    unit system. HMP runs TDIS in seconds and METERS, so both are 1.0; we read
    ``model.time_units`` to stay correct if that ever changes.
    """
    time_units = str(getattr(model, "time_units", "seconds") or "seconds").lower()
    seconds_per_unit = {
        "seconds": 1.0,
        "minutes": 60.0,
        "hours": 3600.0,
        "days": 86400.0,
        "years": 31557600.0,
    }
    return float(seconds_per_unit.get(time_units, 1.0)), 1.0


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
    for lake_id, definition in lakes.items():
        polygon = definition.get("polygon")
        if polygon is None:
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id} has no polygon geometry; load the "
                "lake_geometry data family before pre-processing."
            )
        cells_by_lake[lake_id] = resolve_lake_cells(
            model, lake_id=lake_id, polygon=polygon, vertex_grid=vertex_grid
        )
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


def _active_lake_definitions(model) -> dict[str, dict[str, Any]]:
    """Return the active lake definitions ``{lake_id: {polygon, bedleak, abacus}}``.

    A lake is active when ``lake`` or ``reservoir`` is listed in
    ``flow.active_bc``. Geometry, bedleak and abacus are surfaced by the data /
    physics layers; this helper only normalizes the lookup so the orchestrator
    stays grid-focused.
    """
    flow = getattr(model, "flow", None)
    if flow is None:
        return {}
    active_bc = {str(name).lower() for name in getattr(flow, "active_bc", []) or []}
    if not ({"lake", "reservoir"} & active_bc):
        return {}

    sinks_sources = getattr(flow, "sinks_sources", {})
    lakes = sinks_sources.get("lakes") if isinstance(sinks_sources, Mapping) else None
    if not isinstance(lakes, Mapping) or not lakes:
        return {}

    definitions: dict[str, dict[str, Any]] = {}
    for lake_id, payload in lakes.items():
        definitions[str(lake_id)] = {
            "polygon": _lake_attr(payload, "polygon"),
            "bedleak": _lake_attr(payload, "bedleak"),
            "bedleak_unit": _lake_attr(payload, "bedleak_unit"),
            "abacus": _lake_attr(payload, "abacus"),
            "stageinit": _lake_attr(payload, "stageinit"),
            "occupied_layers": _lake_attr(payload, "occupied_layers"),
            "outlets": _lake_attr(payload, "outlets"),
            "rainfall": _lake_attr(payload, "rainfall"),
            "evaporation": _lake_attr(payload, "evaporation"),
            "runoff": _lake_attr(payload, "runoff"),
            "inflow": _lake_attr(payload, "inflow"),
            "withdrawal": _lake_attr(payload, "withdrawal"),
        }
    return definitions


def _lake_attr(payload: object, name: str) -> object:
    if isinstance(payload, Mapping):
        return payload.get(name)
    return getattr(payload, name, None)


# --------------------------------------------------------------------------- #
# Outlets (surverse / spillway), forcings and unit conversions.
# --------------------------------------------------------------------------- #

# Config lakeout: 0 = external boundary, N = the Nth lake (1-based). FloPy stores
# the destination 0-based and writes +1, so external is -1 and lake N is N - 1.
_EXTERNAL_LAKEOUT = -1

# couttype labels accepted by MF6 (FloPy passes the string straight through).
_OUTLET_COUTTYPES = ("WEIR", "MANNING", "SPECIFIED")


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


def _outlet_couttype(lake_id: str, outlet: object) -> str:
    raw = _lake_attr(outlet, "couttype")
    couttype = str(raw).strip().upper() if raw is not None else ""
    if couttype not in _OUTLET_COUTTYPES:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet couttype must be one of "
            f"{', '.join(_OUTLET_COUTTYPES)}; got {raw!r}."
        )
    return couttype


def _resolve_lakeout(
    lake_id: str,
    outlet: object,
    lake_index_by_id: Mapping[str, int],
) -> int:
    """Translate the config 1-based ``lakeout`` into the FloPy destination index."""
    raw = _lake_attr(outlet, "lakeout")
    value = int(_scalar(raw)) if raw is not None else 0
    if value < 0:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet lakeout must be >= 0 "
            f"(0 = external boundary); got {value}."
        )
    if value == 0:
        return _EXTERNAL_LAKEOUT
    nlakes = len(lake_index_by_id)
    if value > nlakes:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet lakeout={value} has no "
            f"matching downstream lake ({nlakes} lakes declared)."
        )
    if value == lake_index_by_id[lake_id] + 1:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet lakeout={value} routes the lake to itself."
        )
    return value - 1


def _outlet_geometry(
    lake_id: str,
    couttype: str,
    outlet: object,
) -> tuple[float, float, float, float]:
    """Return ``(invert, width, rough, slope)`` for one outlet, validated."""
    if couttype == "SPECIFIED":
        # A specified outlet has no weir/channel geometry; MF6 ignores these.
        return 0.0, 0.0, 0.0, 0.0

    invert = _lake_attr(outlet, "invert")
    width = _lake_attr(outlet, "width")
    if invert is None:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet '{couttype}' requires an invert "
            "(crest / channel-bottom elevation)."
        )
    if width is None:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet '{couttype}' requires a width."
        )

    if couttype == "MANNING":
        rough = _lake_attr(outlet, "rough")
        slope = _lake_attr(outlet, "slope")
        if rough is None or _scalar(rough) <= 0.0:
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id} MANNING outlet requires a positive "
                "rough (Manning n)."
            )
        if slope is None or _scalar(slope) <= 0.0:
            raise ValueError(
                f"flow.sinks_sources.lakes.{lake_id} MANNING outlet requires a positive slope."
            )
        return _scalar(invert), _scalar(width), _scalar(rough), _scalar(slope)

    # WEIR: rough / slope are unused by MF6.
    return _scalar(invert), _scalar(width), 0.0, 0.0


# The single LAK package name used across the GWF model (see build.py: pname="LAK").
_LAK_PACKAGE_NAME = "LAK"


def build_lake_mover_records(
    model,
    *,
    lakes: Mapping[str, dict[str, Any]],
) -> list[MoverRecord]:
    """Compile the LAK outlet ``mover`` specs into general MVR transfers.

    Each outlet carrying a ``mover`` spec becomes one :class:`MoverRecord` with
    provider ``LAK`` outlet number (0-based, assigned in the same order as
    :func:`build_lake_outlets`) and receiver ``LAK`` lake number (0-based, the
    ``mover.lake`` 1-based config index translated to packagedata position).

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
            receiver_index = _resolve_receiver_lake(lake_id, mover, lake_count)
            raw_mvrtype = _lake_attr(mover, "mvrtype")
            mvrtype = str(raw_mvrtype).strip().upper() if raw_mvrtype is not None else "FACTOR"
            raw_value = _lake_attr(mover, "value")
            value = _scalar(raw_value) if raw_value is not None else 1.0
            records.append(
                MoverRecord(
                    provider=_LAK_PACKAGE_NAME,
                    provider_id=int(outletno),
                    receiver=_LAK_PACKAGE_NAME,
                    receiver_id=int(receiver_index),
                    mvrtype=mvrtype,
                    value=value,
                )
            )
            outletno += 1
    return records


def _resolve_receiver_lake(lake_id: str, mover: object, lake_count: int) -> int:
    """Translate a ``mover.lake`` (1-based) to its 0-based receiver lake index."""
    raw = _lake_attr(mover, "lake")
    if raw is None:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet mover requires a 'lake' "
            "(1-based downstream receiving lake)."
        )
    value = int(_scalar(raw))
    if value < 1:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet mover lake must be >= 1 "
            f"(1-based downstream lake); got {value}."
        )
    if value > lake_count:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet mover lake={value} has no "
            f"matching downstream lake ({lake_count} lakes declared)."
        )
    return value - 1


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
    mode, min_periods = _lak_forcing_mode(model)
    nper = int(getattr(model, "nper", 0) or 0)
    period_rows: dict[int, list[list[Any]]] = {}
    ts_series: list[Ts6Series] = []
    for lake_index, (lake_id, definition) in enumerate(lakes.items()):
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
    return period_rows, ts_series


def _emit_forcing_rows(
    model,
    *,
    lake_index: int,
    lake_id: str,
    keyword: str,
    forcing: object,
    volumetric: bool,
    mode: str,
    min_periods: int,
    nper: int,
    period_rows: dict[int, list[list[Any]]],
    ts_series: list[Ts6Series],
) -> None:
    """Append LAK PERIOD rows (inline floats or a TS6 name) for one forcing.

    A constant forcing emits a single inline ``[i, kw, float]`` row in period 0.
    A non-constant forcing routes to a TS6 series when ``resolve_use_ts6`` opts
    in (one period-0 row carrying the series name). Otherwise it is expanded
    inline: one ``[i, kw, float]`` row per stress period whenever the value
    changes (period 0 always), so a time-varying forcing is never dropped.
    """
    if forcing is None:
        return
    location = f"flow.sinks_sources.lakes.{lake_id}.{keyword}"
    value = _constant_forcing_value(forcing)
    use_ts6 = resolve_use_ts6(forcing, mode=mode, nper=nper, min_periods=min_periods)
    if value is not None and not use_ts6:
        period_rows.setdefault(0, []).append(
            [int(lake_index), keyword, float(_to_si(value, forcing, location, volumetric))]
        )
        return

    # A non-constant forcing needs the solver period grid to expand. Without a
    # model (nper unknown) there is nothing to resolve, so emit nothing.
    if nper <= 0:
        return

    per_period = resolve_period_values_from_forcing(
        forcing=forcing,
        simulation_window=None if model.time_grid is None else model.time_grid.window,
        nper=nper,
        label=location,
    )
    unit = _forcing_unit(forcing)
    per_period_si = tuple(
        float(_to_si(raw, forcing, f"{location}[{idx}]", volumetric, explicit_unit=unit))
        for idx, raw in enumerate(per_period)
    )

    if use_ts6:
        series_name = _ts6_series_name(lake_index, keyword)
        period_rows.setdefault(0, []).append([int(lake_index), keyword, series_name])
        times, values = _ts6_times_and_values(model, per_period_si)
        ts_series.append(
            Ts6Series(
                name=series_name,
                times=times,
                values=values,
                interpolation="stepwise",
            )
        )
        return

    # Inline expansion: one row per stress period whenever the value changes. MF6
    # carries each value forward until the next row, so a constant tail collapses
    # to a single row while every genuine change is preserved.
    previous: float | None = None
    for kper, si_value in enumerate(per_period_si):
        if previous is None or si_value != previous:
            period_rows.setdefault(kper, []).append([int(lake_index), keyword, si_value])
            previous = si_value


def _to_si(
    value: object,
    forcing: object,
    location: str,
    volumetric: bool,
    *,
    explicit_unit: str | None = None,
) -> float:
    """Convert one forcing value to its canonical SI unit (m/s or m3/s)."""
    unit = explicit_unit if explicit_unit is not None else _forcing_unit(forcing)
    if volumetric:
        return parse_to_m3_per_s(value, location=location, default_unit="m3/s", explicit_unit=unit)[
            0
        ]
    return parse_to_m_per_s(value, location=location, default_unit="m/s", explicit_unit=unit)[0]


def _lak_forcing_mode(model) -> tuple[str, int]:
    """Return the ``(lak_forcing_mode, ts6_min_periods)`` config pair."""
    config = getattr(model, "modflow_config", None)
    process_specific = getattr(config, "process_specific", None)
    mode = str(getattr(process_specific, "lak_forcing_mode", "auto") or "auto")
    min_periods = int(getattr(process_specific, "ts6_min_periods", 120) or 120)
    return mode, min_periods


def resolve_use_ts6(forcing: object, *, mode: str, nper: int, min_periods: int) -> bool:
    """Return whether one forcing should be written as an external TS6 series.

    A bare-constant forcing always stays inline (a one-row TS6 file would be
    wasteful and would perturb output), so ``False`` for it regardless of mode.
    ``inline`` never uses TS6. ``ts6`` always routes a non-constant forcing.
    ``auto`` routes a non-constant forcing only when ``nper > min_periods``.
    """
    if _constant_forcing_value(forcing) is not None:
        return False
    if _forcing_kind(forcing) == "constant":
        return False
    if nper <= 1:
        return False
    if mode == "inline":
        return False
    if mode == "ts6":
        return True
    return nper > int(min_periods)


def _ts6_series_name(lake_index: int, keyword: str) -> str:
    """Return a unique, MF6-length-safe TS6 series name for one lake forcing."""
    return f"lak{int(lake_index)}_{keyword}"[:16]


def _ts6_times_and_values(
    model, per_period_si: tuple[float, ...]
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Return the TS6 ``(times, values)`` covering the whole simulation.

    Period starts are ``[0, *cumsum(perlen)[:-1]]`` so each STEPWISE breakpoint is
    the exact start of its stress period and the value is held constant over that
    period. A terminal breakpoint at the simulation end (``cumsum(perlen)[-1]``)
    repeating the last value closes the final interval, which MF6 requires to
    integrate the series over the last period.
    """
    perlen = np.asarray(model.perlen, dtype=float).ravel()
    cumulative = np.cumsum(perlen)
    starts = np.concatenate(([0.0], cumulative[:-1]))
    times = tuple(float(t) for t in starts) + (float(cumulative[-1]),)
    values = tuple(per_period_si) + (float(per_period_si[-1]),)
    return times, values


def _forcing_kind(forcing: object) -> str | None:
    """Return the forcing discriminator (``constant`` / ``csv`` / ...) or None."""
    kind = _lake_attr(forcing, "kind")
    if kind is None:
        kind = _lake_attr(forcing, "mode")
    return str(kind) if kind is not None else None


def _constant_forcing_value(forcing: object) -> object:
    """Return the scalar value of a constant forcing, or None.

    A forcing may be a bare number, a ``{value, units}`` mapping, or a
    ``FlowWellForcingConstantConfig``-style object (``kind == 'constant'``). CSV /
    TS6 forcings are resolved at runtime and skipped here.
    """
    if forcing is None:
        return None
    if isinstance(forcing, Real) and not isinstance(forcing, bool):
        return float(forcing)
    kind = _lake_attr(forcing, "kind")
    if kind is not None and str(kind) != "constant":
        return None
    value = _lake_attr(forcing, "value")
    if value is not None:
        magnitude = getattr(value, "magnitude", value)
        return magnitude
    if isinstance(forcing, Mapping) and "value" not in forcing:
        return None
    return forcing


def _forcing_unit(forcing: object) -> str | None:
    unit = _lake_attr(forcing, "units")
    if unit is None:
        unit = _lake_attr(forcing, "unit")
    return str(unit) if unit is not None else None


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


def _lake_id_for_index(lake_conn_info: Sequence[Mapping[str, Any]], lake_index: int) -> str:
    """Return the lake id for one 0-based lake index."""
    for info in lake_conn_info:
        if int(info["lake_index"]) == lake_index:
            return str(info["lake_id"])
    raise ValueError(f"No lake registered for lake index {lake_index}.")


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
    "build_vertex_grid_for_intersection",
    "convert_bedleak_to_per_s",
    "lake_definitions_for_bedleak",
    "resolve_lake_cells",
    "resolve_lake_cells_for_active_lakes",
    "resolve_lake_occupied_layers",
    "resolve_use_ts6",
]
