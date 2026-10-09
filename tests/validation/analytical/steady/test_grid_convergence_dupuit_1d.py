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

from tests.regression.golden_utils import assert_required_executables
from tests.validation.helpers import assert_metric_below, record_series
from validation_cases.analytical.steady.dupuit_fixed_head_1d.comparison import (
    CASE_DIR,
    build_dupuit_fixed_head_comparison,
)
from validation_cases.shared import load_case_metadata, run_launcher_validation_case

# Column counts of the refinement. With the 400 m x 50 m strip, square cells
# need a width that divides 50 m: 25, 12.5 and 6.25 m.
COLUMNS = (16, 32, 64)
CELLS_PER_ROW_LENGTH = 8  # length_x / length_y

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


def _refined_case(root: Path, *, ncol: int, newton: bool | None, label: str) -> Path:
    """Copy the case configuration with ``ncol`` columns of square cells.

    The copy keeps the case directory name, so the launcher applies the same
    validation solver profile as for the case itself. ``label`` makes the run
    name, and so the output folder, unique per variant and grid.
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

    for solver_config in ("config_modflow6.toml", "config_modflownwt.toml"):
        config = _read(case_dir / solver_config)
        section = "modflow6" if solver_config == "config_modflow6.toml" else "modflownwt"
        config[section]["sgrid"]["planar"].update(nx=ncol, ny=nrow)
        if section == "modflow6" and newton is not None:
            runtime = config[section].setdefault("runtime", {})
            runtime.update(TIGHT_MF6_RUNTIME)
            runtime["mf6_newton"] = newton
        _write(case_dir / solver_config, config)
    return case_dir


def _head_rmse(root: Path, *, solver: str, ncol: int, newton: bool | None, label: str) -> float:
    case_dir = _refined_case(root, ncol=ncol, newton=newton, label=label)
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


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.steady
@pytest.mark.slow
@pytest.mark.parametrize(
    ("solver", "newton", "expected_order", "require_modflow", "require_modflow6"),
    [
        # MODFLOW 6 runs Newton by default: that variant takes the solver's own name,
        # the other one a name of its own, so the page shows them apart.
        pytest.param("modflow6_no_newton", False, 2.0, False, True, id="modflow6_no_newton"),
        pytest.param("modflow6", True, 1.0, False, True, id="modflow6"),
        pytest.param("modflow_nwt", None, 1.0, True, False, id="modflow_nwt"),
    ],
)
def test_grid_convergence_dupuit_fixed_head_1d(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    solver: str,
    newton: bool | None,
    expected_order: float,
    require_modflow: bool,
    require_modflow6: bool,
) -> None:
    """Refine the launcher case twice and check the observed order of the head RMSE."""
    assert_required_executables(
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
        require_modpath=False,
        require_mt3dms=False,
    )

    length_x = float(load_case_metadata(CASE_DIR)["reference"]["xmax"])
    cell_sizes = np.asarray([length_x / ncol for ncol in COLUMNS], dtype=float)
    label = request.node.callspec.id
    run_solver = "modflow6" if solver == "modflow6_no_newton" else solver
    errors = np.asarray(
        [
            _head_rmse(tmp_path, solver=run_solver, ncol=ncol, newton=newton, label=label)
            for ncol in COLUMNS
        ],
        dtype=float,
    )
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
        0.2,
    )
