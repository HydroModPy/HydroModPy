"""Validate the grid convergence of the steady Dupuit fixed-head case on the production path.

Compared with: the steady Dupuit profile `h^2 = h_w^2 + (h_e^2 - h_w^2) (x - x_w) / (x_e - x_w)` between the heads held at the centres of the boundary columns, on 16, 32 and 64 columns.

The case runs through the launcher, the route of ``test_dupuit_fixed_head_1d.py``,
on copies of its configuration refined twice by 2 (cells of 25, 12.5 and
6.25 m). The slope of the head RMSE against the cell size is the observed
order of the scheme.

Without Newton, MODFLOW 6 takes the harmonic mean of the two cell
transmissivities, a centred scheme of order 2. A head posed half a cell away
from where the reference expects it adds an error of order 1 and drops the
observed order to 1. This is the check the MMS tests cannot make: they import
nothing from ``hydromodpy``.

Under Newton, the HydroModPy default, MODFLOW 6 weights the saturated
thickness of the upstream cell, and so does MODFLOW-NWT. That scheme is of
order 1 by construction: the RMSE halves when the cells halve (13.3, 6.7 and
3.4 mm here). Both runs are checked against order 1.

The same refinement runs on the other grids of the strip. The triangle and
Voronoi grids are built in ``tmp_path`` from the uniform right-triangle strip
(``write_uniform_strip_bundle`` and ``write_gmsh22_triangle_mesh_from_bundle_csv``),
with ``dx = dy`` so that the centroid line across a diagonal stays normal to the
edge; no bundle is committed. MODFLOW 6 on triangles and on the Voronoi dual
observes the same orders as the structured grid, 2 without Newton and 1 under
Newton (the upstream thickness weighting). The Boussinesq solver averages the
thickness of the two cells in the edge flux, which is exact in ``h^2`` at the
centroids. Its second-order error is that of the aggregation: the profile is the
column mean of the centroids at dx/3 and 2dx/3, read against the reference at the
column centre. PETSc and the default local engine give the same errors to 1e-9
m; the local engine goes from the dense solver (64 and 256 cells) to scipy_sparse
(1024 cells at 64 columns) inside the refinement without moving the result.

Every run closes the head to 1e-9 m, far below the discretization error, so
the observed order is the order of the scheme. The bands are those of the MMS
orders, ``|p - 2| < 0.2`` and ``|p - 1| < 0.2`` (``tests/TOLERANCES.md``).
"""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

import numpy as np
import pytest
import tomli_w

from tests._helpers.tolerances import tol
from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below, record_series
from validation_cases.analytical.steady.dupuit_fixed_head_1d import runtime_boussinesq
from validation_cases.analytical.steady.dupuit_fixed_head_1d.comparison import (
    CASE_DIR,
    build_dupuit_fixed_head_comparison,
)
from validation_cases.shared import load_case_metadata, run_launcher_validation_case
from validation_cases.shared.boussinesq_uniform_strip import write_uniform_strip_bundle
from validation_cases.shared.gmsh_irregular_strip import write_gmsh22_triangle_mesh_from_bundle_csv

# Column counts of the refinement. With the 400 m x 50 m strip, square cells
# need a width that divides 50 m: 25, 12.5 and 6.25 m.
COLUMNS = (16, 32, 64)
CELLS_PER_ROW_LENGTH = 8  # length_x / length_y
WIDTH_Y_M = 50.0
# Solvers that read a mesh bundle, written in tmp_path for each grid.
MESH_SOLVERS = ("modflow6_irregular_tri", "modflow6_voronoi")
BOUSSINESQ_SOLVERS = ("boussinesq", "boussinesq_local")

# A head closure far below the 1e-5 m error of the finest standard run.
TIGHT_MF6_RUNTIME = {
    "mf6_outer_dvclose": 1e-9,
    "mf6_inner_dvclose": 1e-10,
    "mf6_inner_rclose": 1e-10,
    "mf6_outer_maximum": 2000,
    "mf6_inner_maximum": 2000,
}


def _read(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, payload: dict) -> None:
    path.write_text(tomli_w.dumps(payload), encoding="utf-8")


def _write_strip_mesh(root: Path, *, ncol: int, nrow: int, reference: dict) -> Path:
    """Write the uniform right-triangle strip of ``ncol`` x ``nrow`` squares and its Gmsh mesh."""
    bundle = write_uniform_strip_bundle(
        root / "bundle",
        nx=ncol,
        ny=nrow,
        length_x_m=float(reference["xmax"]) - float(reference["xmin"]),
        width_y_m=WIDTH_Y_M,
        z_top_m=float(reference["aquifer_thickness_m"]),
        z_bottom_m=0.0,
        hydraulic_conductivity_m_s=float(reference["hydraulic_conductivity_m_per_s"]),
        storage_coefficient=0.1,
    )
    write_gmsh22_triangle_mesh_from_bundle_csv(bundle)
    return bundle


def _refined_case(root: Path, *, ncol: int, newton: bool | None, label: str, solver: str) -> Path:
    """Copy the case configuration with ``ncol`` columns of square cells.

    The copy keeps the case directory name, so the launcher applies the same
    validation solver profile as for the case itself. ``label`` makes the run
    name, and so the output folder, unique per variant and grid. The triangle
    and Voronoi solvers read a mesh generated in ``root``, by absolute path.
    """
    nrow = ncol // CELLS_PER_ROW_LENGTH
    case_dir = root / f"ncol_{ncol}" / CASE_DIR.name
    case_dir.mkdir(parents=True)
    # Hidden files are the runtime configs a concurrent run of the case writes
    # and removes: copying them races with that run.
    for source in CASE_DIR.glob("*.toml"):
        if not source.name.startswith("."):
            shutil.copy(source, case_dir / source.name)

    metadata = _read(case_dir / "metadata.toml")
    metadata["case_id"] = f"grid_{label}_{ncol}"
    metadata["output"]["expected_shape"] = [nrow, ncol]
    _write(case_dir / "metadata.toml", metadata)

    common = _read(case_dir / metadata["base_config"])
    common["geographic"]["synthetic"]["grid"].update(nx=ncol, ny=nrow)
    _write(case_dir / metadata["base_config"], common)

    solver_config = metadata["config_files"][solver]
    config = _read(case_dir / solver_config)
    section = "modflownwt" if solver == "modflow_nwt" else "modflow6"
    if solver in MESH_SOLVERS:
        bundle = _write_strip_mesh(case_dir, ncol=ncol, nrow=nrow, reference=metadata["reference"])
        config["mesh"]["triangle"]["path"] = str(bundle / "mesh_2d.msh")
    # A structured solver meshes the synthetic grid written above: its cells are the pixels.
    if section == "modflow6" and newton is not None:
        runtime = config[section].setdefault("runtime", {})
        runtime.update(TIGHT_MF6_RUNTIME)
        runtime["mf6_newton"] = newton
    _write(case_dir / solver_config, config)
    return case_dir


def _launcher_head_rmse(
    root: Path, *, solver: str, ncol: int, newton: bool | None, label: str
) -> float:
    case_dir = _refined_case(root, ncol=ncol, newton=newton, label=label, solver=solver)
    result = run_launcher_validation_case(case_dir=case_dir, test_file=__file__, solver=solver)
    try:
        comparison = build_dupuit_fixed_head_comparison(
            result=result,
            metadata=load_case_metadata(case_dir),
            tolerances={},
        )
    finally:
        result.store.close()
    return float(comparison.rms_error)


def _boussinesq_head_rmse(
    monkeypatch: pytest.MonkeyPatch, *, solver: str, ncol: int, label: str
) -> float:
    """Run the Boussinesq strip on ``ncol`` columns and return its head RMSE.

    The runtime of the case reads its grid from module constants. They are set
    for the run, with a case id per grid so that no output folder is shared.
    """
    nrow = ncol // CELLS_PER_ROW_LENGTH
    monkeypatch.setattr(runtime_boussinesq, "NX", ncol)
    monkeypatch.setattr(runtime_boussinesq, "NY", nrow)
    monkeypatch.setattr(runtime_boussinesq, "CASE_ID", f"grid_{label}_{ncol}")
    engine = (
        {"runtime_backend": "petsc", "surface_interaction_model": "vi_obstacle"}
        if solver == "boussinesq"
        else {"surface_interaction_model": None}
    )
    result = runtime_boussinesq.run_boussinesq_dupuit_fixed_head_case(
        caller_file=__file__, public_solver_label=solver, **engine
    )
    try:
        metadata = load_case_metadata(CASE_DIR)
        metadata["output"]["expected_shape"] = [nrow, ncol]
        comparison = build_dupuit_fixed_head_comparison(
            result=result, metadata=metadata, tolerances={}
        )
    finally:
        result.store.close()
    return float(comparison.rms_error)


ORDER_BANDS = {
    "boussinesq": tol("grid_convergence_dupuit_fixed_head_1d_boussinesq_petsc_and_local_engine"),
    "boussinesq_local": tol(
        "grid_convergence_dupuit_fixed_head_1d_boussinesq_petsc_and_local_engine"
    ),
    "modflow6_irregular_tri": tol(
        "grid_convergence_dupuit_fixed_head_1d_modflow_6_triangles_voronoi_dual"
    ),
    "modflow6_voronoi": tol(
        "grid_convergence_dupuit_fixed_head_1d_modflow_6_triangles_voronoi_dual"
    ),
}


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.steady
@pytest.mark.parametrize(
    ("solver", "newton", "expected_order", "require_modflow", "require_modflow6"),
    [
        # MODFLOW 6 runs Newton by default: that variant takes the solver's own name,
        # the other one a name of its own, so the page shows them apart. The suffix
        # keeps the prefix of the grid, which is the column of the matrix.
        pytest.param(
            "modflow6_no_newton",
            False,
            2.0,
            False,
            True,
            id="modflow6_no_newton",
            marks=pytest.mark.slow,
        ),
        pytest.param("modflow6", True, 1.0, False, True, id="modflow6", marks=pytest.mark.slow),
        pytest.param(
            "modflow_nwt", None, 1.0, True, False, id="modflow_nwt", marks=pytest.mark.slow
        ),
        pytest.param(
            "modflow6_irregular_tri_no_newton",
            False,
            2.0,
            False,
            True,
            id="modflow6_irregular_tri_no_newton",
            marks=pytest.mark.slow,
        ),
        pytest.param(
            "modflow6_irregular_tri",
            True,
            1.0,
            False,
            True,
            id="modflow6_irregular_tri",
            marks=pytest.mark.slow,
        ),
        pytest.param(
            "modflow6_voronoi_no_newton",
            False,
            2.0,
            False,
            True,
            id="modflow6_voronoi_no_newton",
            marks=pytest.mark.slow,
        ),
        pytest.param(
            "modflow6_voronoi",
            True,
            1.0,
            False,
            True,
            id="modflow6_voronoi",
            marks=pytest.mark.slow,
        ),
        # Boussinesq: order 2 whatever the engine, that of the column aggregation.
        pytest.param(
            "boussinesq",
            None,
            2.0,
            False,
            False,
            id="boussinesq",
            marks=[pytest.mark.petsc, pytest.mark.fast],
        ),
        pytest.param(
            "boussinesq_local",
            None,
            2.0,
            False,
            False,
            id="boussinesq_local",
            marks=pytest.mark.fast,
        ),
    ],
)
def test_grid_convergence_dupuit_fixed_head_1d(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    solver: str,
    newton: bool | None,
    expected_order: float,
    require_modflow: bool,
    require_modflow6: bool,
) -> None:
    """Refine the case twice and check the observed order of the head RMSE."""
    assert_required_executables(
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
        require_modpath=False,
        require_mt3dms=False,
    )

    length_x = float(load_case_metadata(CASE_DIR)["reference"]["xmax"])
    cell_sizes = np.asarray([length_x / ncol for ncol in COLUMNS], dtype=float)
    label = request.node.callspec.id
    run_solver = solver.removesuffix("_no_newton")
    if run_solver in BOUSSINESQ_SOLVERS:
        errors = [
            _boussinesq_head_rmse(monkeypatch, solver=run_solver, ncol=ncol, label=label)
            for ncol in COLUMNS
        ]
    else:
        errors = [
            _launcher_head_rmse(tmp_path, solver=run_solver, ncol=ncol, newton=newton, label=label)
            for ncol in COLUMNS
        ]
    errors = np.asarray(errors, dtype=float)
    order = float(np.polyfit(np.log(cell_sizes), np.log(errors), 1)[0])

    record_series(
        "Head RMSE against the cell size",
        cell_sizes,
        errors[0] * (cell_sizes / cell_sizes[0]) ** expected_order,
        errors,
        x_label="cell size (m)",
        y_label="head RMSE (m)",
        log=True,
    )
    assert_metric_below(
        f"Distance of the observed order from {expected_order:g}",
        abs(order - expected_order),
        ORDER_BANDS.get(run_solver, 0.2),
    )
