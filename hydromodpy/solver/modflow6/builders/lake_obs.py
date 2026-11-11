"""The LAK observations: the per-lake series and the flows through a cutoff wall."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np
import shapely

from hydromodpy.solver.modflow6.builders._lake_connection import (
    _safe_lake_tag,
)
from hydromodpy.solver.modflow6.builders._lake_geometry import (
    cutoff_wall_faces,
)
from hydromodpy.solver.modflow6.builders._lake_outlets import (
    _lake_id_for_index,
)

if TYPE_CHECKING:
    from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh


# --------------------------------------------------------------------------- #
# LAK observations (OBS6) for the per-lake output series.
# --------------------------------------------------------------------------- #

# Per-lake scalar observation types keyed by the 0-based lake number (MF6 ifno),
# mapped to the HMP-side series name the extractor stores. MF6 LAK obs cannot be
# requested by boundname through flopy (its writer increments integer ids and
# chokes on strings), so every observation uses the integer lake / connection
# number and the lake-aquifer exchange is reconstructed from the per-connection
# terms. The MF6 ``storage`` obs is stored as ``lake_storage``, because
# ``storage`` names the budget field of the aquifer. ext-outflow / to-mvr /
# outlet are NOT here: MF6 keys them by outlet number, so they are requested in
# the per-outlet loop instead.
_LAKE_SCALAR_OBSTYPES: tuple[tuple[str, str], ...] = (
    ("stage", "stage"),
    ("volume", "volume"),
    ("surface-area", "surface_area"),
    ("ext-inflow", "inflow"),
    ("outlet-inflow", "outlet_inflow"),
    ("rainfall", "rainfall"),
    ("evaporation", "evaporation"),
    ("runoff", "runoff"),
    ("withdrawal", "withdrawal"),
    ("storage", "lake_storage"),
)


def cutoff_wall_flow_faces(
    definition: Mapping[str, Any], lake_cell_ids: Sequence[int], solver_mesh: SolverMesh
) -> list[tuple[int, int]]:
    """The faces of a lake's cutoff wall as ``(lake side, downstream side)`` pairs.

    The faces are those of the HFB and the LAK seal (:func:`cutoff_wall_faces`).
    A face with a lake cell has it first. Any other face (a wing, a face of the
    line off the shore) is ordered by the side of the wall: the wall has the lake
    on its left, so the first cell is the one the crossing leaves on the left.
    The extractor sums the face flow over these pairs (``cutoff_wall_flow``).
    Empty without a wall.
    """
    line = definition.get("cutoff_wall_line")
    if line is None or getattr(line, "is_empty", True):
        return []
    lake = {int(c) for c in lake_cell_ids}
    faces = cutoff_wall_faces(solver_mesh.cell_mesh, line, np.asarray(sorted(lake), dtype=np.int64))
    centres = np.asarray(solver_mesh.cell_mesh.centers, dtype=float)
    pairs: list[tuple[int, int]] = []
    for face in faces:
        a, b = int(face.cell_a), int(face.cell_b)
        if a in lake:
            pairs.append((a, b))
        elif b in lake or _crosses_to_the_left(line, centres[a], centres[b]):
            pairs.append((b, a))
        else:
            pairs.append((a, b))
    return pairs


def _crosses_to_the_left(line: Any, start: np.ndarray, end: np.ndarray) -> bool:
    """Whether going from ``start`` to ``end`` crosses the wall to its left side."""
    mid = shapely.points(0.5 * (start[0] + end[0]), 0.5 * (start[1] + end[1]))
    along = float(shapely.line_locate_point(line, mid))
    step = 1.0e-6 * max(float(line.length), 1.0)
    before = shapely.get_coordinates(line.interpolate(max(along - step, 0.0)))[0]
    after = shapely.get_coordinates(line.interpolate(min(along + step, float(line.length))))[0]
    tangent = after - before
    move = np.asarray(end[:2], dtype=float) - np.asarray(start[:2], dtype=float)
    return float(tangent[0] * move[1] - tangent[1] * move[0]) > 0.0


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
    MF6's 1-based convention). ``lake_obs_meta`` is the JSON-serializable sidecar
    mapping each observation name to its lake / quantity / connection so the
    extractor can re-key the obs CSV by ``(lake_id, totim)`` and isolate the
    VERTICAL exchange of the lake bed. A lake whose info carries ``wall_faces``
    (:func:`cutoff_wall_flow_faces`) has them listed under ``cutoff_walls``, read
    with the GWF budget ``gwf_budget_bin`` into ``cutoff_wall_flow``.

    When ``has_mover`` is set the LAK package routes water through MVR, so a
    ``from-mvr`` obs is added per lake (water received from the mover, MF6 id =
    lake number) and a ``to-mvr`` obs per outlet (water sent to the mover, id =
    outlet number). These obs are only valid once the package advertises MOVER.

    Returns empty structures when no lake is present.
    """
    if not lake_conn_info:
        return {}, {"obs_csv": "", "budgetcsv": None, "budget_bin": None, "entries": []}

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
        "budget_bin": f"{stem}.lak.cbc",
        "entries": entries,
        # The faces of each cutoff wall, lake side first, and the GWF budget whose
        # FLOW-JA-FACE carries the flow across them (series cutoff_wall_flow).
        "cutoff_walls": {
            str(info["lake_id"]): [[int(a), int(b)] for a, b in info["wall_faces"]]
            for info in lake_conn_info
            if info.get("wall_faces")
        },
        "gwf_budget_bin": f"{stem}.cbc",
    }
    return obs_continuous, lake_obs_meta


__all__ = [
    "build_lake_obs_spec",
    "cutoff_wall_flow_faces",
]
