"""The computational top of the MODFLOW 6 grid.

Under Newton, MODFLOW 6 builds the horizontal conductance from the full
thickness of the two cells (harmonic mean of K (top - bottom)) times the
saturation of the upstream cell. Where the thickness changes from one cell to
the next, the transmissivity is too low by about dD / (2 D). MODFLOW-NWT and
the Boussinesq solver use the saturated thickness and have no such bias.

The grid MODFLOW 6 reads therefore carries a computational top
T' = G + (Dmax - D), with G the ground, D = G - botm[0] and Dmax the largest D
of the raised cells. Every raised cell of the top layer then has the same
thickness, and the bias goes. A constant thickness gives G back. It is a
numerical device of HydroModPy, not a USGS practice.

Only the DISV files of the GWF, GWT and PRT models carry T'. The solver mesh,
every package elevation and the run store keep G. The build leaves G beside
the model as ``<model>.ground.npz`` so that the extractor stores the ground
and not T'.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.exceptions import SolverInputError

THICKNESS_TOLERANCE_M = 1.0e-3
"""A thickness deficit below this is zero. The input rasters hold elevations to
the millimetre, so a smaller gap is rounding, not geometry."""

GROUND_SIDECAR_SUFFIX = ".ground.npz"
"""Name of the file the build leaves beside the model for the extractor."""


def computational_top(
    ground: np.ndarray,
    layer_bottom: np.ndarray,
    raised: np.ndarray,
) -> np.ndarray:
    """Return T' = G + (Dmax - D) on the ``raised`` cells and G elsewhere.

    ``D = ground - layer_bottom`` and ``Dmax`` is its maximum over the raised
    cells. A deficit under :data:`THICKNESS_TOLERANCE_M` counts as zero, so a
    constant thickness gives the ground back exactly.
    """
    ground = np.asarray(ground, dtype=float).reshape(-1)
    bottom = np.asarray(layer_bottom, dtype=float).reshape(-1)
    raised = np.asarray(raised, dtype=bool).reshape(-1)
    if not ground.size == bottom.size == raised.size:
        raise ValueError(
            f"ground, layer_bottom and raised differ in size: "
            f"{ground.size}, {bottom.size}, {raised.size}."
        )
    top = ground.copy()
    if not raised.any():
        return top
    thickness = ground[raised] - bottom[raised]
    if not np.all(np.isfinite(thickness)):
        raise ValueError("a raised cell has no finite ground or bottom.")
    deficit = thickness.max() - thickness
    deficit[deficit < THICKNESS_TOLERANCE_M] = 0.0
    top[raised] = ground[raised] + deficit
    return top


def raised_cells(solver_mesh: Any, open_water_cell_ids: Iterable[int]) -> np.ndarray:
    """Return the cells whose top is raised: active in the top layer, not open water.

    A lake column keeps its ground. Raising the top of the cell under a lake
    would push the cell into the lake, so the thickness contrast stays at the
    banks.
    """
    raised = ~np.asarray(solver_mesh.inactive_mask, dtype=bool)[0].copy()
    lake_cells = np.asarray(sorted({int(cid) for cid in open_water_cell_ids}), dtype=int)
    raised[lake_cells] = False
    return raised


def model_computational_top(model: Any) -> np.ndarray:
    """Return the top MODFLOW 6 reads for the solver mesh of ``model``.

    It reads the mesh after the lake beds were carved, so the carved columns
    keep their own top.
    """
    solver_mesh = model.solver_mesh
    return computational_top(
        solver_mesh.top,
        solver_mesh.botm[0],
        raised_cells(solver_mesh, model.open_water_cell_ids),
    )


def disv_grid_kwargs(model: Any) -> dict[str, Any]:
    """Return the DISV keyword arguments of every MODFLOW 6 model of a run.

    MODFLOW 6 requires the GWF, GWT and PRT grids to be identical, so the
    three of them are built from this one call. DISV vertices already hold
    absolute model coordinates, so the package origin is 0.
    """
    solver_mesh = model.solver_mesh
    kwargs = solver_mesh.to_disv_kwargs()
    kwargs["top"] = model_computational_top(model)
    return {
        "nlay": solver_mesh.nlay,
        **kwargs,
        "idomain": solver_mesh.idomain(),
        "xorigin": 0.0,
        "yorigin": 0.0,
        "length_units": "METERS",
    }


def top_layer_ground_fraction(model: Any) -> np.ndarray:
    """Return ``(G - botm[0]) / (T' - botm[0])`` per cell, 1 where the top is not raised.

    It is the share of the written top-layer cell that lies below the ground.
    A fraction of the cell height that MODFLOW 6 reads (a pumping turnoff, a
    particle release) is scaled by it to stay a fraction of the aquifer.
    """
    solver_mesh = model.solver_mesh
    ground = np.asarray(solver_mesh.top, dtype=float)
    bottom = np.asarray(solver_mesh.botm[0], dtype=float)
    top = model_computational_top(model)
    fraction = np.ones_like(ground)
    raised = top > ground
    fraction[raised] = (ground[raised] - bottom[raised]) / (top[raised] - bottom[raised])
    return fraction


def well_flow_reduce_fraction(
    model: Any,
    well_spd: Mapping[int, Sequence[Sequence[float]]],
    *,
    of_aquifer: float,
) -> float:
    """Return the WEL ``AUTO_FLOW_REDUCE`` fraction that keeps ``of_aquifer`` of the aquifer.

    MODFLOW 6 reads the option as a fraction of the cell height. Under a raised
    top that height exceeds the aquifer, and a well would be throttled with
    the aquifer full. The option is one scalar per package, so the fraction
    is the smallest that keeps the interval within ``of_aquifer`` of the
    thickness below the ground in every well cell. Rows are ``[layer, cell, q]``.
    """
    top_layer_cells = sorted(
        {int(row[1]) for rows in well_spd.values() for row in rows if int(row[0]) == 0}
    )
    if not top_layer_cells:
        return float(of_aquifer)
    fraction = top_layer_ground_fraction(model)
    return float(of_aquifer) * float(np.min(fraction[top_layer_cells]))


def write_ground_sidecar(model: Any) -> Path:
    """Leave the ground of the solver mesh beside the model as ``<model>.ground.npz``.

    The extractor reads the model folder, and the DISV top there is T'. A
    failure to write is an error: the run could not store its ground.
    """
    path = Path(model.full_path) / f"{model.model_output_name}{GROUND_SIDECAR_SUFFIX}"
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(path, ground=np.asarray(model.solver_mesh.top, dtype=np.float64))
    return path


def read_ground_sidecar(
    solver_output_dir: str | Path,
    *,
    written_top: np.ndarray,
) -> np.ndarray:
    """Return the ground the build left in ``solver_output_dir``.

    Raises
    ------
    SolverInputError
        When the folder holds no ground file or several, or when the ground
        does not fit the written top. The top of the MODFLOW 6 grid file is
        a computational top, so it cannot stand in for the ground.
    """
    folder = Path(solver_output_dir)
    files = sorted(folder.glob(f"*{GROUND_SIDECAR_SUFFIX}"))
    if len(files) != 1:
        found = ", ".join(f.name for f in files) or "none"
        raise SolverInputError(
            f"{folder} must hold one *{GROUND_SIDECAR_SUFFIX} file, found {found}. The top of "
            "a MODFLOW 6 grid file is a computational top above the ground, so the ground "
            "cannot be read from it. Run the model again to write the file."
        )
    with np.load(files[0], allow_pickle=False) as payload:
        ground = np.asarray(payload["ground"], dtype=np.float64).reshape(-1)
    written = np.asarray(written_top, dtype=np.float64).reshape(-1)
    if ground.size != written.size:
        raise SolverInputError(
            f"{files[0].name} holds {ground.size} cells, the grid file {written.size}."
        )
    if np.any(written < ground - THICKNESS_TOLERANCE_M):
        raise SolverInputError(
            f"{files[0].name} puts the ground above the top of the grid file: it was not "
            "written for this model."
        )
    return ground


__all__ = [
    "GROUND_SIDECAR_SUFFIX",
    "THICKNESS_TOLERANCE_M",
    "computational_top",
    "disv_grid_kwargs",
    "model_computational_top",
    "raised_cells",
    "read_ground_sidecar",
    "top_layer_ground_fraction",
    "well_flow_reduce_fraction",
    "write_ground_sidecar",
]
