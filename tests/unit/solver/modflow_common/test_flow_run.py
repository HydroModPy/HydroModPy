"""Helpers the two MODFLOW flow adapters share: build, run, read a solved run back.

``build_flow_model`` writes nothing and ``run_flow_model`` writes the input files and solves. The
name and the folder of a run come from the ``RunSlot`` the runner fills. Heads are in m, times in s.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.exceptions import MeshError, ObservableNotAvailableError, SolverDivergedError
from hydromodpy.model.model import ModelOptions, ModelTime
from hydromodpy.solver.base.plan import (
    WATER_BUDGET_METRIC,
    WATER_BUDGET_WORST_METRIC,
    RunSlot,
    SolverRun,
)
from hydromodpy.solver.modflow6.support.names import mf6_output_name, mf6_safe_name
from hydromodpy.solver.modflow_common.flow_run import (
    build_flow_model,
    build_preprocess_options,
    end_of_last_period,
    final_state_head,
    nwt_safe_name,
    resolve_solver_run_output,
    run_flow_model,
)
from tests._helpers.model_factory import make_model, small_geometry, time_grid


def test_preprocess_options_defaults() -> None:
    from hydromodpy.solver.base.solver_config import SolverConfig
    from hydromodpy.solver.modflow_common.options import ModflowPreprocessOptions

    options = build_preprocess_options(
        make_model(options=ModelOptions.from_settings(SolverConfig()))
    )

    defaults = ModflowPreprocessOptions()
    assert options.box is defaults.box
    assert options.sink_fill is defaults.sink_fill
    assert options.check_grid is defaults.check_grid


def test_preprocess_options_from_model() -> None:
    grid = time_grid(10, 20)
    model = make_model(
        time=ModelTime(grid=grid, regime="transient", first_period_steady=True),
        options=ModelOptions(
            sink_fill=True,
            drain_band_depth_m=0.5,
            drain_bed_thickness_m=2.0,
            drain_conductance_floor_m2_s=1e-9,
        ),
    )

    options = build_preprocess_options(model)

    assert options.time_grid is grid
    assert options.sink_fill is True
    assert options.drain_band_depth_m == 0.5
    assert options.drain_bed_thickness_m == 2.0
    assert options.drain_conductance_floor_m2_s == 1e-9


@pytest.mark.parametrize(
    ("root", "name"),
    [
        pytest.param(
            "C:\\" + "\\".join(["hydromodpy_regression_outputs"] * 8),
            "natural_mesh_10km2_transient_pulse_mf6_vs_bouss__mf6_ref",
            id="a Windows folder far past the limit",
        ),
        pytest.param("C:\\hmp\\scratch", "demo", id="a short Windows folder"),
        pytest.param("/home/user/run", "demo", id="a POSIX folder"),
    ],
)
def test_mf6_output_name(root: str, name: str) -> None:
    # The path length is held by the reservation, so the stem never depends on the folder.
    model = SimpleNamespace(full_path=root, model_name=name, model_name_mf6=mf6_safe_name(name))

    assert mf6_output_name(model) == name


# MF6 rejects a space in a model name, so a run of whitespace becomes one "_".
# A name over the 16 character limit is hashed.
SAFE_NAMES = [
    pytest.param("lake e2e", "lake_e2e", id="space"),
    pytest.param("  spaced  name ", "spaced_name", id="padded"),
    pytest.param("tab\tsep", "tab_sep", id="tab"),
    pytest.param("demo", "demo", id="clean name"),
]


@pytest.mark.parametrize(("name", "safe"), SAFE_NAMES)
def test_mf6_safe_name(name: str, safe: str) -> None:
    assert mf6_safe_name(name) == safe


def test_mf6_long_name_hashed() -> None:
    safe = mf6_safe_name("a very long model name that exceeds the limit")
    assert len(safe) <= 16
    assert " " not in safe


class _Solver:
    """A MODFLOW solver object that writes nothing and records the calls it receives."""

    def __init__(self, folder: Path, *, success: bool = True, input_files=("a.nam", "a.dis")):
        self.full_path = str(folder)
        self.input_files = input_files
        self.last_flow_solve_time_seconds = 1.5
        self.success = success
        self.pre: list[tuple] = []
        self.runs: list[Any] = []

    def pre_processing(self, model, options=None, *, slot=None) -> None:
        self.pre.append((model, options, slot))

    def processing(self, options=None) -> bool:
        self.runs.append(options)
        return self.success


_OPTIONS = build_preprocess_options(make_model())


def _built(folder: Path, **solver: Any) -> tuple[SolverRun, _Solver]:
    slot = RunSlot(folder.parent, folder.name)
    solver_model = _Solver(folder, **solver)
    built = build_flow_model(solver_model, make_model(), None, slot, _OPTIONS)
    return built, solver_model


def test_build_solves_nothing(
    tmp_path: Path,
) -> None:
    model = make_model()
    slot = RunSlot(tmp_path, "island")
    solver = _Solver(tmp_path / "island")

    built = build_flow_model(solver, model, None, slot, _OPTIONS)

    assert solver.pre == [(model, _OPTIONS, slot)]
    assert solver.runs == []
    assert built.solver_model is solver and built.model is model and built.slot is slot
    assert (built.written, built.solved, built.output_dir, built.input_files) == (
        False,
        False,
        None,
        (),
    )


def test_build_needs_cell_mesh(tmp_path: Path) -> None:
    from dataclasses import replace

    model = make_model(geometry=replace(small_geometry(), cells=None))
    solver = _Solver(tmp_path / "island")

    with pytest.raises(MeshError, match="planar cell mesh"):
        build_flow_model(solver, model, None, RunSlot(tmp_path, "island"), _OPTIONS)

    assert solver.pre == []


def test_run_writes_and_solves(tmp_path: Path) -> None:
    built, solver = _built(tmp_path / "island")
    (tmp_path / "island").mkdir()

    solved = run_flow_model(built, solver_name="modflow_nwt")

    (options,) = solver.runs
    assert (options.write_model, options.run_model, options.runner) == (True, True, "subprocess")
    assert options.link_mt3dms is False
    assert solved.output_dir == tmp_path / "island"
    assert solved.input_files == ("a.nam", "a.dis")
    assert (solved.written, solved.solved) == (True, True)
    assert solved.solver_model is solver and solved.slot is built.slot
    assert solved.solve_s == 1.5
    assert solved.metrics == {}  # the time of a solve is no result of the run


def test_solve_time_unset(tmp_path: Path) -> None:
    built, solver = _built(tmp_path / "island")
    solver.last_flow_solve_time_seconds = None

    assert run_flow_model(built, solver_name="modflow_nwt").solve_s is None


def test_written_files_not_rewritten(tmp_path: Path) -> None:
    from dataclasses import replace

    built, solver = _built(tmp_path / "island")

    run_flow_model(replace(built, written=True), solver_name="modflow_nwt")

    assert solver.runs[0].write_model is False


def test_run_links_mt3dms(tmp_path: Path) -> None:
    built, solver = _built(tmp_path / "island")
    solver.link_mt3dms = True

    run_flow_model(built, solver_name="modflow_nwt")

    assert solver.runs[0].link_mt3dms is True


def test_run_reports_budget_error(tmp_path: Path) -> None:
    folder = tmp_path / "island"
    folder.mkdir()
    (folder / "a.list").write_text(
        "VOLUMETRIC BUDGET FOR ENTIRE MODEL\n   PERCENT DISCREPANCY = 0.01\n"
        "VOLUMETRIC BUDGET FOR ENTIRE MODEL\n   PERCENT DISCREPANCY = -2.50\n",
        encoding="utf-8",
    )
    built, _ = _built(folder)

    solved = run_flow_model(built, solver_name="modflow_nwt")

    assert solved.metrics[WATER_BUDGET_METRIC] == -2.5
    assert solved.metrics[WATER_BUDGET_WORST_METRIC] == -2.5


def test_run_keeps_build_metrics(tmp_path: Path) -> None:
    from dataclasses import replace

    built, _ = _built(tmp_path / "island")

    solved = run_flow_model(replace(built, metrics={"carried": 3.0}), solver_name="modflow_nwt")

    assert solved.metrics == {"carried": 3.0}
    assert solved.solve_s == 1.5


def test_failed_solve_names_slot(tmp_path: Path) -> None:
    built, _ = _built(tmp_path / "island", success=False)

    with pytest.raises(
        SolverDivergedError, match=r"'modflow_nwt' failed for run 'island'"
    ) as raised:
        run_flow_model(built, solver_name="modflow_nwt")

    assert raised.value.run_id is None, "the runner puts the run id on it"


def test_failed_mf6_solve_quotes_listing(tmp_path: Path) -> None:
    folder = tmp_path / "island"
    folder.mkdir()
    (folder / "mfsim.lst").write_text("  Solution did not converge\n", encoding="utf-8")
    (folder / "a.lst").write_text(
        "VOLUME BUDGET FOR ENTIRE MODEL\n   PERCENT DISCREPANCY = 7.5\n", encoding="utf-8"
    )
    built, _ = _built(folder, success=False)

    with pytest.raises(SolverDivergedError) as raised:
        run_flow_model(built, solver_name="modflow6")

    message = str(raised.value)
    assert "PERCENT DISCREPANCY = 7.5" in message
    assert "did not converge" in message
    assert "mfsim.lst" in message


def _solved(tmp_path: Path, solver_model: Any) -> SolverRun:
    return SolverRun(
        slot=RunSlot(tmp_path, "island"),
        solver_model=solver_model,
        output_dir=tmp_path / "island",
        written=True,
        solved=True,
    )


NAMES = [
    pytest.param(("model_name", "name"), "alpha", id="the first attribute that is set"),
    pytest.param(("model_output_name", "model_name"), "alpha", id="an attribute that is none"),
    pytest.param(("name", "model_name"), "beta", id="the order of the attributes"),
]


@pytest.mark.parametrize(("attributes", "expected"), NAMES)
def test_model_name_of_a_solved_run(tmp_path: Path, attributes, expected) -> None:
    solver_model = SimpleNamespace(model_output_name=None, model_name="alpha", name="beta")

    output_dir, got, name = resolve_solver_run_output(
        _solved(tmp_path, solver_model), name_attributes=attributes
    )

    assert (output_dir, got, name) == (tmp_path / "island", solver_model, expected)


REFUSED = [
    pytest.param(
        lambda tmp: SolverRun(slot=RunSlot(tmp, "island"), solver_model=object()), id="no folder"
    ),
    pytest.param(
        lambda tmp: SolverRun(slot=RunSlot(tmp, "island"), output_dir=tmp), id="no solver object"
    ),
    pytest.param(lambda tmp: _solved(tmp, SimpleNamespace()), id="no name on the solver object"),
]


@pytest.mark.parametrize("make", REFUSED)
def test_run_without_trace_refused(tmp_path: Path, make) -> None:
    with pytest.raises(ObservableNotAvailableError, match="'island'"):
        resolve_solver_run_output(make(tmp_path), name_attributes=("model_name",))


@pytest.mark.parametrize(
    ("name", "safe"),
    [("island", "island"), ("Example 12 launcher", "Example_12_launcher"), (" a  b\tc ", "a_b_c")],
)
def test_nwt_safe_name(name: str, safe: str) -> None:
    assert nwt_safe_name(name) == safe


FINAL_HEADS = [
    pytest.param([[1.0, 2.0], [3.0, 4.0]], (), [[1.0, 2.0], [3.0, 4.0]], id="no sentinel"),
    pytest.param(
        [[1.0, 1e30], [-1e30, 4.0]], (), [[1.0, np.nan], [np.nan, 4.0]], id="MF6 sentinels"
    ),
    pytest.param(
        [[1.0, -9999.0], [-100.2, 4.0]],
        (-100.0, -9999.0),
        [[1.0, np.nan], [np.nan, 4.0]],
        id="NWT sentinels within a metre",
    ),
    pytest.param([[1.0, -100.2]], (), [[1.0, -100.2]], id="near a sentinel no one configured"),
]


@pytest.mark.parametrize(("raw", "sentinels", "expected"), FINAL_HEADS)
def test_final_state_head(raw, sentinels, expected) -> None:
    raw = np.array(raw, dtype=np.float32 if sentinels else np.float64)
    shape = raw.shape

    head = final_state_head(
        raw.reshape(1, *shape), nlay=shape[0], n_cells=shape[1], sentinels=sentinels
    )

    assert head.dtype == np.float64 and head.shape == shape
    np.testing.assert_allclose(head, expected, rtol=1e-6)
    assert np.array_equal(np.isnan(head), np.isnan(np.array(expected)))


def test_final_state_head_is_a_copy() -> None:
    raw = np.array([[1.0, 1e30]])

    final_state_head(raw, nlay=1, n_cells=2)

    assert raw[0, 1] == 1e30


END_OF_LAST_PERIOD = [
    pytest.param("2020-01-01", 86400.0 * 31, pd.Timestamp("2020-02-01"), id="calendar start"),
    pytest.param(
        pd.Timestamp("2020-01-01 06:00"), 3600.0, pd.Timestamp("2020-01-01 07:00"), id="timestamp"
    ),
    pytest.param(None, 86400.0, None, id="no calendar"),
]


@pytest.mark.parametrize(("start", "seconds", "expected"), END_OF_LAST_PERIOD)
def test_end_of_the_last_period(start, seconds, expected) -> None:
    assert end_of_last_period(start, seconds) == expected
