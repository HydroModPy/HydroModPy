"""The helpers the two MODFLOW flow adapters share: options, build, run, output and start date.

``build_flow_model`` and ``run_flow_model`` are the two halves of the lifecycle
once a solver object exists. The name and the folder of a run come from the
``RunSlot`` the runner fills, so no helper derives a name.
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
from hydromodpy.solver.modflow_common.flow_adapter_helpers import (
    build_flow_model,
    build_preprocess_options,
    end_of_last_period,
    final_state_head,
    nwt_safe_name,
    resolve_solver_run_output,
    run_flow_model,
)
from tests._helpers.model_factory import make_model, small_geometry, time_grid


def test_build_preprocess_options_returns_defaults() -> None:
    """A model built with the defaults of ``[solver]`` gives the defaults of the options."""
    from hydromodpy.solver.base.solver_config import SolverConfig
    from hydromodpy.solver.modflow_nwt import ModflowPreprocessOptions

    options = build_preprocess_options(
        make_model(options=ModelOptions.from_settings(SolverConfig()))
    )

    defaults = ModflowPreprocessOptions()
    assert options.box is defaults.box
    assert options.sink_fill is defaults.sink_fill
    assert options.check_grid is defaults.check_grid


def test_build_preprocess_options_reads_the_time_grid_and_the_options_of_the_model() -> None:
    """The grid and the four ``[solver]`` settings come from the members of the model."""
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


def test_mf6_output_name_shortens_long_windows_paths(monkeypatch) -> None:
    import hydromodpy.solver.modflow6.build as build_module

    long_name = "natural_mesh_10km2_transient_pulse_mf6_vs_bouss__mf6_ref"
    safe_name = mf6_safe_name(long_name)
    long_root = "C:\\" + "\\".join(["hydromodpy_regression_outputs"] * 8)
    model = SimpleNamespace(
        full_path=long_root,
        model_name=long_name,
        model_name_mf6=safe_name,
    )

    monkeypatch.setattr(build_module.os, "name", "nt")

    assert mf6_output_name(model) == safe_name


def test_mf6_output_name_preserves_short_windows_paths(monkeypatch) -> None:
    import hydromodpy.solver.modflow6.build as build_module

    model = SimpleNamespace(
        full_path="C:\\hmp\\scratch",
        model_name="demo",
        model_name_mf6="demo",
    )

    monkeypatch.setattr(build_module.os, "name", "nt")

    assert mf6_output_name(model) == "demo"


def test_mf6_safe_name_replaces_whitespace() -> None:
    """MF6 rejects a space in a model name; whitespace runs collapse to '_'."""
    assert mf6_safe_name("lake e2e") == "lake_e2e"
    assert mf6_safe_name("  spaced  name ") == "spaced_name"
    assert mf6_safe_name("tab\tsep") == "tab_sep"


def test_mf6_safe_name_keeps_short_clean_names() -> None:
    assert mf6_safe_name("demo") == "demo"


def test_mf6_safe_name_hashes_long_names_within_limit() -> None:
    """A long name is hashed to stay within the identifier limit, still space-free."""
    safe = mf6_safe_name("a very long model name that exceeds the limit")
    assert len(safe) <= 16
    assert " " not in safe


# ---------------------------------------------------------------------------
# The two halves of the lifecycle
# ---------------------------------------------------------------------------


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


def test_a_build_hands_the_model_and_the_slot_to_the_solver_and_solves_nothing(
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


def test_a_model_without_the_cell_mesh_stops_the_build_before_the_solver(tmp_path: Path) -> None:
    from dataclasses import replace

    model = make_model(geometry=replace(small_geometry(), cells=None))
    solver = _Solver(tmp_path / "island")

    with pytest.raises(MeshError, match="planar cell mesh"):
        build_flow_model(solver, model, None, RunSlot(tmp_path, "island"), _OPTIONS)

    assert solver.pre == []


def test_a_run_writes_the_input_files_of_a_build_and_solves(tmp_path: Path) -> None:
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


def test_a_solver_that_measured_no_time_leaves_solve_s_unset(tmp_path: Path) -> None:
    built, solver = _built(tmp_path / "island")
    solver.last_flow_solve_time_seconds = None

    assert run_flow_model(built, solver_name="modflow_nwt").solve_s is None


def test_a_run_whose_files_are_written_does_not_write_them_again(tmp_path: Path) -> None:
    from dataclasses import replace

    built, solver = _built(tmp_path / "island")

    run_flow_model(replace(built, written=True), solver_name="modflow_nwt")

    assert solver.runs[0].write_model is False


def test_a_run_links_the_mt3dms_output_when_the_build_said_so(tmp_path: Path) -> None:
    built, solver = _built(tmp_path / "island")
    solver.link_mt3dms = True

    run_flow_model(built, solver_name="modflow_nwt")

    assert solver.runs[0].link_mt3dms is True


def test_a_run_reports_how_its_water_budget_closed(tmp_path: Path) -> None:
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


def test_a_run_keeps_the_metrics_the_build_carried(tmp_path: Path) -> None:
    from dataclasses import replace

    built, _ = _built(tmp_path / "island")

    solved = run_flow_model(replace(built, metrics={"carried": 3.0}), solver_name="modflow_nwt")

    assert solved.metrics == {"carried": 3.0}
    assert solved.solve_s == 1.5


def test_a_failed_solve_names_the_run_by_its_slot(tmp_path: Path) -> None:
    built, _ = _built(tmp_path / "island", success=False)

    with pytest.raises(
        SolverDivergedError, match=r"'modflow_nwt' failed for run 'island'"
    ) as raised:
        run_flow_model(built, solver_name="modflow_nwt")

    assert raised.value.run_id is None, "the runner puts the run id on it"


def test_a_failed_modflow6_solve_says_why_the_listing_stopped(tmp_path: Path) -> None:
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


# ---------------------------------------------------------------------------
# Reading a solved run back
# ---------------------------------------------------------------------------


def _solved(tmp_path: Path, solver_model: Any) -> SolverRun:
    return SolverRun(
        slot=RunSlot(tmp_path, "island"),
        solver_model=solver_model,
        output_dir=tmp_path / "island",
        written=True,
        solved=True,
    )


NAMES = (
    ("the first attribute that is set", ("model_name", "name"), "alpha"),
    ("an attribute that is none is skipped", ("model_output_name", "model_name"), "alpha"),
    ("the order of the attributes", ("name", "model_name"), "beta"),
)


@pytest.mark.parametrize(("case", "attributes", "expected"), NAMES, ids=[c[0] for c in NAMES])
def test_the_model_name_of_a_solved_run_is_the_first_attribute_that_is_set(
    tmp_path: Path, case: str, attributes: tuple[str, ...], expected: str
) -> None:
    del case
    solver_model = SimpleNamespace(model_output_name=None, model_name="alpha", name="beta")

    output_dir, got, name = resolve_solver_run_output(
        _solved(tmp_path, solver_model), name_attributes=attributes
    )

    assert (output_dir, got, name) == (tmp_path / "island", solver_model, expected)


REFUSED = (
    ("no output folder", lambda tmp: SolverRun(slot=RunSlot(tmp, "island"), solver_model=object())),
    ("no solver object", lambda tmp: SolverRun(slot=RunSlot(tmp, "island"), output_dir=tmp)),
    ("no name on the solver object", lambda tmp: _solved(tmp, SimpleNamespace())),
)


@pytest.mark.parametrize(("case", "make"), REFUSED, ids=[c[0] for c in REFUSED])
def test_a_run_with_no_trace_to_read_is_refused_by_its_slot_name(
    tmp_path: Path, case: str, make
) -> None:
    del case

    with pytest.raises(ObservableNotAvailableError, match="'island'"):
        resolve_solver_run_output(make(tmp_path), name_attributes=("model_name",))


@pytest.mark.parametrize(
    ("name", "safe"),
    [("island", "island"), ("Example 12 launcher", "Example_12_launcher"), (" a  b\tc ", "a_b_c")],
)
def test_nwt_collapses_whitespace_in_the_name_of_a_model(name: str, safe: str) -> None:
    assert nwt_safe_name(name) == safe


FINAL_HEADS = (
    ("a head without sentinel", [[1.0, 2.0], [3.0, 4.0]], (), [[1.0, 2.0], [3.0, 4.0]]),
    ("the MODFLOW 6 sentinels", [[1.0, 1e30], [-1e30, 4.0]], (), [[1.0, np.nan], [np.nan, 4.0]]),
    (
        "the NWT sentinels of the run, within a metre",
        [[1.0, -9999.0], [-100.2, 4.0]],
        (-100.0, -9999.0),
        [[1.0, np.nan], [np.nan, 4.0]],
    ),
    ("a head near a sentinel no one configured", [[1.0, -100.2]], (), [[1.0, -100.2]]),
)


@pytest.mark.parametrize(
    ("case", "raw", "sentinels", "expected"), FINAL_HEADS, ids=[c[0] for c in FINAL_HEADS]
)
def test_the_head_of_final_state_is_float64_with_the_sentinels_masked(
    case: str, raw: list, sentinels: tuple, expected: list
) -> None:
    del case
    raw = np.array(raw, dtype=np.float32 if sentinels else np.float64)
    shape = raw.shape

    head = final_state_head(
        raw.reshape(1, *shape), nlay=shape[0], n_cells=shape[1], sentinels=sentinels
    )

    assert head.dtype == np.float64 and head.shape == shape
    np.testing.assert_allclose(head, expected, rtol=1e-6)
    assert np.array_equal(np.isnan(head), np.isnan(np.array(expected)))


def test_the_head_of_final_state_does_not_alias_the_record() -> None:
    raw = np.array([[1.0, 1e30]])

    final_state_head(raw, nlay=1, n_cells=2)

    assert raw[0, 1] == 1e30


END_OF_LAST_PERIOD = (
    ("a calendar start", "2020-01-01", 86400.0 * 31, pd.Timestamp("2020-02-01")),
    (
        "a timestamp start",
        pd.Timestamp("2020-01-01 06:00"),
        3600.0,
        pd.Timestamp("2020-01-01 07:00"),
    ),
    ("no calendar", None, 86400.0, None),
)


@pytest.mark.parametrize(
    ("case", "start", "seconds", "expected"),
    END_OF_LAST_PERIOD,
    ids=[c[0] for c in END_OF_LAST_PERIOD],
)
def test_the_end_of_the_last_period_is_the_start_plus_the_elapsed_time(
    case: str, start: object, seconds: float, expected: pd.Timestamp | None
) -> None:
    del case

    assert end_of_last_period(start, seconds) == expected
