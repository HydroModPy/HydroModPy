"""MF6 LAK package builder on a DISV grid.

The lake is a boundary package laid on the existing aquifer grid: lake cells are
made inactive (``idomain = 0``) and LAK supplies storage and exchange through its
own CONNECTIONDATA. We build that CONNECTIONDATA ourselves from the cell mesh
because ``flopy.mf6.utils.get_lak_connections`` does not support embedded /
horizontal lakes on DISV (it raises for unstructured grids and only handles the
trivial surface-lake case).

The lake cells come from the cell mesh. On a mesh whose faces follow the whole
lake shore (``exact_faces`` and a ``lakes`` face family that covers every shore
line), a lake owns the regions the shore faces enclose, each cell whole. On any
other mesh, including one that follows the shore only in part, it owns every cell
its polygon overlaps by a positive area, credited with that overlap.

Each lake cell gets:

* one VERTICAL connection to the first active cell below the lake column (the
  leakage / infiltration path towards the aquifer, using K33), and
* one HORIZONTAL connection across every shared edge to each active cell of a
  non-lake neighbor column that faces the lake water, whatever its layer
  (bank seepage, using K11). ``connwidth`` is the shared-edge length,
  ``connlen`` the perpendicular half-distance from the neighbor centroid to the
  edge, and ``belev`` / ``telev`` the neighbor cell bottom / top clipped to the
  lake vertical extent.

Functions are pure and keyword-only, mirroring ``builders/wells.py``. They raise
plain ``ValueError`` naming the offending TOML path, exactly as ``wells.py`` does.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from typing import Any

import flopy
import numpy as np

from hydromodpy.core.fields.vertical_column import top_active_layer
from hydromodpy.core.logging import get_logger
from hydromodpy.core.units.quantities import parse_to_per_s
from hydromodpy.model.initial.state import PriorState, SolvedState
from hydromodpy.solver.modflow6.builders._lake_connection import (
    _abacus_rows,
    _lak_output_stem,
    _safe_lake_tag,
)
from hydromodpy.solver.modflow6.builders._lake_definitions import (
    _active_lake_definitions,
    _scalar,
)
from hydromodpy.solver.modflow6.builders._lake_geometry import (
    _cell_faces,
    _first_active_layer_below,
    _point_to_segment_distance,
    cutoff_wall_faces,
)
from hydromodpy.solver.modflow6.builders._lake_outlets import (
    _emit_forcing_rows,
    _emit_outlet_rate_rows,
    _emit_steady_stage_hold_rows,
    _forcing_si_per_period,
)
from hydromodpy.solver.modflow6.builders.lake_cells import resolve_lake_cells_for_active_lakes
from hydromodpy.solver.modflow6.builders.lake_obs import build_lake_obs_spec, cutoff_wall_flow_faces
from hydromodpy.solver.modflow6.builders.lake_outflow import (
    build_lake_mover_records,
    build_lake_outlets,
)
from hydromodpy.solver.modflow6.builders.mvr import (
    build_mvr_period_records,
    mover_package_count,
)
from hydromodpy.solver.modflow6.builders.period_forcing import resolve_forcing_mode
from hydromodpy.solver.modflow6.builders.sfr import mover_rows_reach_lake
from hydromodpy.solver.modflow6.builders.sidecar import write_sidecar
from hydromodpy.solver.modflow6.support.time_series import Ts6Series, attach_time_series
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

logger = get_logger(__name__)

LAK_STAGE_SUFFIX = ".lak.stage"
"""The end of the binary file MODFLOW 6 writes the stage of each lake in, at every time step."""

# CONNECTIONDATA claktype labels (FloPy passes these strings through to MF6).
_VERTICAL = "VERTICAL"
_HORIZONTAL = "HORIZONTAL"

# A leakance is non-negative. bedleak = 0 means a perfectly sealed lakebed (the
# lakebed conductance, hence the harmonic-mean lake-aquifer conductance, is 0):
# no leakage, which is a valid choice for a fully lined reservoir. Negative
# leakance is rejected.
_MIN_BEDLEAK = 0.0

# Thinnest band of lake water a bank connection must face. Elevations hold to the
# millimeter, so a thinner overlap of the lake band and a neighbor cell is
# round-off between two columns, not a bank.
_MIN_BANK_THICKNESS_M = 1.0e-3


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
    sealed_faces: Collection[tuple[int, int]] | None = None,
    bank_seepage: bool = True,
) -> list[list[Any]]:
    """Build the CONNECTIONDATA rows for one lake on a DISV grid.

    Rows follow the FloPy LAK layout
    ``[ifno, iconn, cellid, claktype, bedleak, belev, telev, connlen, connwidth]``
    with 0-based ``ifno`` / ``iconn`` and ``cellid = (lay, cell2d)``.

    The lake occupies the top ``occupied_layers`` layers of each lake column
    (matching ``apply_lake_idomain_mask``). For each lake column we emit:

    * one VERTICAL connection to the first active cell below the occupied layers
      (the leakage path towards the aquifer), pass-through cells skipped, and
    * one HORIZONTAL connection across every shared edge to each active cell of
      a non-lake neighbor column that faces the lake water (bank seepage).

    The lake water of a column spans its occupied cap ``[bed, top]``. A bank
    connection is clipped to the part of that band the neighbor cell holds,
    whatever the layer index of that cell: on a sloping or pinched stack the
    neighbor layers do not line up with the lake ones, and a pass-through
    neighbor has handed its thickness to the active cell below it. A column
    whose cap is pinched out has no band, so it exchanges through its bed only.

    ``solver_mesh`` must already carry the lake idomain mask so that
    ``idomain > 0`` identifies active non-lake neighbours. ``sealed_faces``
    holds the ``(cell_a, cell_b)`` pairs, ``cell_a < cell_b``, a cutoff wall
    bars: no HORIZONTAL connection crosses them.
    """
    if float(bedleak) < _MIN_BEDLEAK:
        raise ValueError(f"flow.sinks_sources.lakes bedleak must be >= 0, got {bedleak}.")

    lake_set = {int(c) for c in lake_cell_ids}
    if not lake_set:
        raise ValueError("build_lake_connectiondata requires at least one lake cell.")

    idomain = solver_mesh.idomain  # (nlay, n_cells)
    top = np.asarray(solver_mesh.top, dtype=float)
    botm = np.asarray(solver_mesh.botm, dtype=float)  # (nlay, n_cells)
    nlay = int(solver_mesh.nlay)
    vertices = np.asarray(solver_mesh.planar_mesh.vertices, dtype=float)
    centroids = solver_mesh.cell_centers()
    top_active = top_active_layer(idomain)

    def _occ(cid: int) -> int:
        """Per-cell occupied-layer count (carved-bed depth), else the lake scalar."""
        if occupied_layers_by_cell is not None:
            return int(occupied_layers_by_cell.get(int(cid), occupied_layers))
        return int(occupied_layers)

    lake_cells = sorted(lake_set)

    # Dam seal: cut every HORIZONTAL bank connection across a face the cutoff
    # wall bars, so the lake never seeps sideways past the dam. This is a LAK
    # concern, independent of the HFB: the HFB is a GWF-GWF barrier that does not
    # throttle LAK-GWF flow, so the seal lives here, on the same faces as the HFB.
    # Vertical (bed) connections are kept.
    sealed_pairs = set(sealed_faces or ())

    def _neighbour_behind_wall(cid: int, neighbour: int) -> bool:
        return (min(cid, neighbour), max(cid, neighbour)) in sealed_pairs

    sealed = [0]

    def _horizontal_rows(cid: int, lake_top: float, lake_bottom: float, iconn: int):
        """HORIZONTAL bank connections of one lake column, sealed at the dam.

        Fixed area: the bank spans the occupied cap ``[lake_bottom, lake_top]``.
        Marnage (decision D8): the lake column stays active below its carved bed,
        so the bank spans ``[carved bed, neighbor top]`` and never sits below the
        bed. Every active neighbor cell that crosses that band by more than
        ``_MIN_BANK_THICKNESS_M`` gets one row.
        """
        out: list[list[Any]] = []
        faces = _cell_faces(solver_mesh.cell_mesh, cid)
        for lay in range(nlay):
            for neighbour, node_a, node_b, width in faces:
                if width <= 0.0:
                    continue  # degenerate (zero-length) edge: skip
                if neighbour in lake_set:
                    continue  # never connect a lake to another lake cell
                if int(idomain[lay, neighbour]) <= 0:
                    continue  # neighbor inactive at this layer
                cell_top = float(top[neighbour]) if lay == 0 else float(botm[lay - 1, neighbour])
                if dynamic_area:
                    belev = max(float(botm[lay, neighbour]), lake_top)
                    telev = min(cell_top, float(top[neighbour]))
                else:
                    belev = max(float(botm[lay, neighbour]), lake_bottom)
                    telev = min(cell_top, lake_top)
                if telev - belev <= _MIN_BANK_THICKNESS_M:
                    continue  # neighbor cell sits outside the lake vertical extent
                if _neighbour_behind_wall(cid, neighbour):
                    sealed[0] += 1
                    continue  # seal: no bank seepage across the dam
                connlen = _point_to_segment_distance(
                    centroids[neighbour], vertices[node_a], vertices[node_b]
                )
                if connlen <= 0.0:
                    continue
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
            # bathymetric bed as its top; one VERTICAL connection on the top active
            # cell of the column (bed seepage; MF6 wets it when stage > bed and
            # toggles RCH/ET per cell). A pinched top layer is skipped.
            if int(top_active[cid]) < 0:
                raise ValueError(
                    f"Lake {int(lake_index)} (marnage): column {int(cid)} has no active "
                    "layer, so its bed connection has no cell. Keep the lake polygon "
                    "inside the active domain."
                )
            rows.append(
                [
                    int(lake_index),
                    iconn,
                    (int(top_active[cid]), int(cid)),
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
            hrows = _horizontal_rows(cid, lake_top, lake_bottom, iconn)
            rows.extend(hrows)
            iconn += len(hrows)

    if sealed[0]:
        logger.warning(
            "Lake %d: cutoff_wall seals %d bank connection(s) behind the dam. "
            "The seal is a perfect wall, independent of the HFB hydchr.",
            int(lake_index),
            int(sealed[0]),
        )
    if model is not None:
        try:
            counts = dict(getattr(model, "_lake_sealed_bank_connections", {}) or {})
            counts[int(lake_index)] = int(sealed[0])
            model._lake_sealed_bank_connections = counts
        except AttributeError:
            pass

    if not rows:
        raise ValueError(
            "Lake has no aquifer connection: every neighbour is inactive or another "
            "lake cell. Check the lake footprint and the active domain."
        )
    return rows


def cutoff_wall_pairs(
    definition: Mapping[str, Any], lake_cell_ids: Sequence[int], solver_mesh: SolverMesh
) -> set[tuple[int, int]]:
    """The ``(cell_a, cell_b)`` pairs a lake's cutoff wall bars, none without a wall.

    The faces are those of the HFB (:func:`cutoff_wall_faces`), so the LAK seal
    and the HFB close the same faces.
    """
    line = definition.get("cutoff_wall_line")
    if line is None or getattr(line, "is_empty", True):
        return set()
    faces = cutoff_wall_faces(
        solver_mesh.cell_mesh, line, np.asarray(lake_cell_ids, dtype=np.int64)
    )
    return {(face.cell_a, face.cell_b) for face in faces}


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


# Small depression depth that smooths the dry/wet behavior and helps Newton
# convergence. It is intentionally tiny relative to lake stages.
_DEFAULT_SURFDEP = 0.1
# Fallback leakance (1/T) used until a calibratable per-lake value is declared.
_DEFAULT_BEDLEAK = 1.0


_TABLE_FLOOR_TOL_M = 1e-3
"""Gap (m) between the table bottom and min(belev) that triggers a warning."""


def _lake_connection_floor(rows: Sequence[Sequence[Any]], solver_mesh: SolverMesh) -> float:
    """Return the lowest connection bottom MF6 derives for one lake.

    MF6 bounds the lake stage at this floor. A VERTICAL connection bottoms at
    the top of its cell. A HORIZONTAL one bottoms at ``belev``, or at the cell
    bottom when ``belev == telev``.
    """
    top = np.asarray(solver_mesh.top, dtype=float)
    botm = np.asarray(solver_mesh.botm, dtype=float)
    floors: list[float] = []
    for row in rows:
        lay, cid = int(row[2][0]), int(row[2][1])
        cell_top = float(top[cid]) if lay == 0 else float(botm[lay - 1, cid])
        if row[3] == _VERTICAL:
            floors.append(cell_top)
        elif float(row[5]) == float(row[6]):
            floors.append(float(botm[lay, cid]))
        else:
            floors.append(float(row[5]))
    return float(min(floors))


def _warn_table_off_connection_floor(
    lake_id: str, table: Sequence[Sequence[float]], floor: float
) -> None:
    """Warn when the abacus bottom does not match the MF6 stage floor.

    Below the floor the table holds dead storage MF6 never drains. Above it
    MF6 extrapolates the table under its first row.
    """
    bottom = float(table[0][0])
    if abs(bottom - floor) <= _TABLE_FLOOR_TOL_M:
        return
    side = "below" if bottom < floor else "above"
    logger.warning(
        "Lake '%s': table bottom %.3f m is %s min(belev) %.3f m of its connections "
        "(gap %.3f m). MF6 bounds the stage at min(belev).",
        lake_id,
        bottom,
        side,
        floor,
        abs(bottom - floor),
    )


def _chd_cellids(model) -> set[tuple[int, int]]:
    """Return the ``(lay, cell2d)`` cells held by the model CHD package, if any."""
    chd = getattr(model, "chd", None)
    if chd is None:
        return set()
    data = chd.stress_period_data.get_data() or {}
    cells: set[tuple[int, int]] = set()
    for records in data.values():
        if records is None:
            continue
        for rec in records:
            cellid = rec["cellid"] if getattr(rec, "dtype", None) is not None else rec[0]
            cells.add((int(cellid[0]), int(cellid[-1])))
    return cells


def _refuse_chd_connections(model, *, lake_id: str, rows: Sequence[Sequence[Any]]) -> None:
    """Refuse a lake connected to a CHD cell: MF6 fails on the LAK residual."""
    chd_cells = _chd_cellids(model)
    if not chd_cells:
        return
    hit = sorted({(int(r[2][0]), int(r[2][1])) for r in rows} & chd_cells)
    if hit:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} connects to {len(hit)} CHD cell(s) "
            f"(first (layer, cell): {hit[0]}). A lake must not touch a constant-head "
            "cell; move the CHD boundary or the lake polygon."
        )


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

    # Hotstart: the prior run ([flow] restart_from) or the spin-up cycle before
    # this one seeds each lake's initial stage from its last value, overriding
    # initial_stage. Absent lake / older store -> empty map, so the
    # initial_stage fallback below still applies.
    initial = model.inputs.initial
    restart_stages = initial.lake_stages if isinstance(initial, PriorState | SolvedState) else {}

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
            sealed_faces=cutoff_wall_pairs(definition, cell_ids, solver_mesh),
            bank_seepage=bank_seepage,
        )
        _refuse_chd_connections(model, lake_id=str(lake_id), rows=rows)
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
                "wall_faces": cutoff_wall_flow_faces(definition, cell_ids, solver_mesh),
            }
        )

        abacus = definition.get("abacus")
        table = build_lake_table(model, lake_id=lake_id, abacus=abacus)
        _warn_table_off_connection_floor(
            str(lake_id), table, _lake_connection_floor(rows, solver_mesh)
        )
        initial_stage = definition.get("initial_stage")
        if lake_id in restart_stages:
            # Written with all its digits: the text FloPy makes of a float keeps
            # eight decimals, which moves a lake by 2e-9 m between two windows.
            strt = repr(float(restart_stages[lake_id]))
        elif initial_stage is not None:
            strt = _scalar(initial_stage)
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
        "time_conversion": 1.0,
        "length_conversion": 1.0,
        "print_stage": True,
        "print_flows": True,
        "save_flows": True,
        "stage_filerecord": f"{stem}{LAK_STAGE_SUFFIX}",
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


def read_final_lake_stages(stage_path: Path, lake_ids: Sequence[str]) -> dict[str, float] | None:
    """Return the stage of each lake at the last time step, from a LAK stage file.

    ``stage_path`` is the binary file ``stage_filerecord`` names, written in
    double precision at every time step. ``lake_ids`` are the lakes in LAK
    packagedata order, the order of the records. The stages come back with
    every digit MODFLOW 6 computed, where the observation file keeps ten
    significant digits. ``None`` when the file does not exist, which is a run
    without a lake or a folder whose scratch is gone.
    """
    if not Path(stage_path).is_file():
        return None
    import flopy.utils.binaryfile as bf

    stage_file = bf.HeadFile(str(stage_path), text="STAGE", precision="double")
    try:
        times = stage_file.get_times()
        if not times:
            return None
        last = np.asarray(stage_file.get_data(totim=times[-1]), dtype=np.float64).reshape(-1)
    finally:
        stage_file.close()
    if last.size != len(lake_ids):
        raise ValueError(
            f"{stage_path.name} holds {last.size} lake stage(s) and the model declares "
            f"{len(lake_ids)} lake(s): {list(lake_ids)}."
        )
    return {str(lake): float(stage) for lake, stage in zip(lake_ids, last, strict=True)}


def lake_ids_in_package_order(model) -> list[str]:
    """Return the ids of the active lakes of ``model`` in LAK packagedata order, ``[]`` without one."""
    return list(_active_lake_definitions(model))


def apply_lake_stages(lak: Any, stages: Mapping[str, float]) -> None:
    """Set the starting stage of each lake in the built LAK package ``lak``, all digits kept.

    ``stages`` maps a lake id to its stage in metres. A lake absent from it
    keeps its stage. The package names its lakes by boundname, which the
    builder sets to the lake id. Each stage is written as ``repr`` of the
    float, as ``build_lak_package_args`` does for a restart. FloPy casts a
    string to the type of the column the package holds, a float of eight
    decimals, so the column is made of objects first, which it writes as they are.
    """
    current = lak.packagedata.get_data()
    names = list(current.dtype.names)
    kinds = [(name, "O" if name == "strt" else current.dtype[name]) for name in names]
    rows = [list(row) for row in current]
    strt, boundname = names.index("strt"), names.index("boundname")
    for row in rows:
        lake_id = str(row[boundname])
        if lake_id in stages:
            row[strt] = repr(float(stages[lake_id]))
    lak.packagedata.set_data(np.rec.fromrecords([tuple(row) for row in rows], dtype=kinds))


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
    "LAK_STAGE_SUFFIX",
    "apply_lake_stages",
    "build_lak_package_args",
    "build_lake_connectiondata",
    "build_lake_period_data",
    "build_lake_table",
    "convert_bedleak_to_per_s",
    "lake_ids_in_package_order",
    "read_final_lake_stages",
]


def _write_lake_abacus_meta(model) -> None:
    """Write the reference and simulated abacus of each reconstructed lake bed."""
    reconstruction = getattr(model, "_lake_bed_reconstruction", None)
    entries = [
        {
            "lake_id": str(lid),
            "stage": rec["abacus_stage"],
            "real_volume": rec.get("abacus_volume"),
            "real_sarea": rec["abacus_sarea"],
            "sim_volume": rec["sim_volume"],
            "sim_sarea": rec["sim_sarea"],
        }
        for lid, rec in (reconstruction or {}).items()
        if rec.get("abacus_stage") is not None
        and rec.get("sim_volume") is not None
        and rec.get("abacus_volume") is not None
    ]
    if entries:
        write_sidecar(model, ".lake_abacus.json", {"entries": entries})


def build_lakes(
    model,
    solver_mesh: SolverMesh,
    lake_cell_ids_by_lake,
    sfr_mover_records,
    drainage_mover_rows,
    downstream_reach_by_lake,
):
    """LAK, its tables, observations and sidecars; returns the mover rows so far."""
    # LAK (lake / reservoir) package. Built after model.wel and before model.oc.
    # Lake cells were already made inactive above, so the CONNECTIONDATA targets
    # active aquifer neighbors only. Controlled transfers (LAK -> LAK, SFR -> LAK,
    # LAK -> SFR, DRN -> SFR) ride MVR, which is GWF-scoped and MUST be built last.
    all_mover_rows: list[list[object]] = list(drainage_mover_rows)
    n_lakes_built = 0
    lake_connections: list[list[object]] = []
    if lake_cell_ids_by_lake:
        lak_args = build_lak_package_args(
            model,
            solver_mesh=solver_mesh,
            lake_cell_ids_by_lake=lake_cell_ids_by_lake,
            occupied_layers_by_cell=getattr(model, "_lake_occupied_layers_by_cell", None),
            # A lake is fed by a mover from SFR, or from DRN when the descent of a
            # drain cell meets the lake before any reach. LAK must announce MOVER
            # for either, or MODFLOW 6 stops at the first DRN-to-LAK record.
            external_mover_to_lake=any(record.receiver == "LAK" for record in sfr_mover_records)
            or mover_rows_reach_lake(drainage_mover_rows),
            downstream_reach_by_lake=downstream_reach_by_lake,
        )
        if lak_args is not None:
            laktab_specs = lak_args.pop("laktab_specs")
            mover_records = lak_args.pop("mover_records", None)
            lak_args.pop("mover_maxpackages", 0)
            obs_continuous = lak_args.pop("obs_continuous", None)
            lake_obs_meta = lak_args.pop("lake_obs_meta", None)
            ts_specs = lak_args.pop("ts_specs", None)
            n_lakes_built = int(lak_args["nlakes"])
            lake_connections = lak_args["connectiondata"]
            lak = flopy.mf6.ModflowGwflak(model.gwf, pname="LAK", **lak_args)
            # Non-constant forcings routed to an external TS6 file: attach right
            # after construction so the series names are registered before write.
            if ts_specs:
                attach_time_series(lak, ts_specs, filename=f"{model.model_output_name}.lak.ts")
            for spec in laktab_specs:
                flopy.mf6.ModflowUtllaktab(
                    model.gwf,
                    nrow=len(spec["table"]),
                    ncol=3,
                    table=spec["table"],
                    filename=spec["filename"],
                    parent_file=lak,
                )
            # OBS6 for the per-lake output series, plus a JSON sidecar the
            # extractor reads to re-key the obs CSV by (lake_id, totim).
            if obs_continuous:
                lak.obs.initialize(
                    filename=f"{model.model_output_name}.lak.obs",
                    digits=10,
                    print_input=False,
                    continuous=obs_continuous,
                )
            if lake_obs_meta is not None:
                write_sidecar(model, ".lak.meta.json", lake_obs_meta)
            # Persist the bed-reconstruction abacus comparison for the QC figure.
            _write_lake_abacus_meta(model)
            model.lak = lak
            if mover_records:
                all_mover_rows.extend(mover_records)
            # Active-littoral lakes with exposed_band_runoff need the in-process BMI
            # runner: build the per-lake coupling specs now (lake order == LAK ifno).
            # Their presence flips the runner to 'api' and attaches the callback.
            band_specs = build_exposed_band_runoff_specs(model)
            if band_specs:
                model._exposed_band_runoff_specs = band_specs
    return all_mover_rows, n_lakes_built, lake_connections
