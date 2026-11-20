"""Experimental keys that a file wrote, named by a run and by ``hmp check``, and only those.

The mark is metadata on the field. The walker reads it through ``written_fields``,
so a key the file left at its default never counts. A loader sets some fields a
file never wrote (``calibration = None``), and a selector is stable for most of its
values, so both are pinned here on real files. The line informs: nothing refuses
and no warning is raised.
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path

import pytest

from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.config_kit.written import experimental_keys_line, written_experimental_keys
from hydromodpy.core.state.result_dirs import resolve_project_root
from hydromodpy.project.api import check
from hydromodpy.project.facade import Project
from hydromodpy.project.launch.plan import expand_plan
from tests._helpers.cli_runner import CliRunner
from tests.unit.project.launch.test_plan import write_sites_project

WRITTEN_LOGGER = "hydromodpy.core.config_kit.written"

BASE = """
[workspace]

[workflow]
mode = "simulation"

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"
{geographic}

[simulation]
name = "marks"

[simulation.time]
start_datetime = "2015-01-01"
end_datetime = "2020-12-31"
step_value = "1 day"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]
{process}

[flow]
first_period_steady = false
{flow}

[flow.ic]
kind = "steady_state"
{tables}
"""

SOIL = """
[data]
types = ["precipitation", "etp"]

[[data.precipitation.sources]]
source = "sim2"
extent = "watershed"

[[data.etp.sources]]
source = "sim2"
extent = "watershed"

[flow.bc.drainage]

[flow.sinks_sources.etp]

[flow.sinks_sources.recharge.soil]
ru = "150 mm"
"""

ADAPT = "[solver.boussinesq]\nts_vi_adapt = true\n"

TRANSPORT_PROCESS = """
[[simulation.process]]
id = "transport_main"
kind = "transport"
solvers = ["modflow6_prt"]
"""

CALIBRATION = """
[calibration]
method = "grid"
max_trials = 4
method_options = { points_per_dim = 2 }

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
search_space = "log"
path = "flow.param.K.field.value"
units = "m/s"
"""

K_FIELD = """
[flow.param.K.field]
id = "K"
kind = "homogeneous"
unit = "m/s"
value = 6.4e-5

[flow.param.Sy.field]
id = "Sy"
kind = "homogeneous"
unit = "-"
value = 0.05
"""


def _write(
    tmp_path: Path, *, flow: str = "", tables: str = "", geographic: str = "", process: str = ""
) -> Path:
    path = tmp_path / "project.toml"
    path.write_text(
        BASE.format(flow=flow, tables=tables, geographic=geographic, process=process),
        encoding="utf-8",
    )
    return path


def _said(caplog) -> list[str]:
    """What the walker's logger said, other loggers aside."""
    return [record.getMessage() for record in caplog.records if record.name == WRITTEN_LOGGER]


def _keys(tmp_path: Path, **sections: str) -> tuple[str, ...]:
    return written_experimental_keys(HydroModPyConfig.from_toml(_write(tmp_path, **sections)))


@pytest.mark.parametrize(
    ("sections", "expected"),
    [
        pytest.param(
            {"tables": "[solver.boussinesq]\npartition_release_depth_m = 0.05"},
            ("solver.boussinesq.partition_release_depth_m",),
            id="written-at-the-value-of-its-default",
        ),
        pytest.param(
            {"tables": '[solver.boussinesq]\nsurface_interaction_model = "vi_obstacle"'},
            ('solver.boussinesq.surface_interaction_model = "vi_obstacle"',),
            id="marked-value-of-a-selector",
        ),
        pytest.param(
            {"tables": '[solver.boussinesq]\nsurface_interaction_model = "regularized_partition"'},
            (),
            id="stable-value-of-the-same-selector",
        ),
        pytest.param(
            {"tables": "[solver.boussinesq]\nts_vi_adapt = true\nmax_iterations = 40"},
            ("solver.boussinesq.max_iterations", "solver.boussinesq.ts_vi_adapt"),
            id="runtime-knobs",
        ),
        pytest.param(
            {"geographic": 'domain_extent = "watershed"'},
            ("geographic.domain_extent",),
            id="domain-extent",
        ),
        pytest.param(
            {"tables": "[transport.modflow6_prt]\nwrite_track_binary = false"},
            ("transport.modflow6_prt",),
            id="a-marked-section-is-one-entry",
        ),
        pytest.param(
            {"tables": "[transport.modpath]\ntrack_dir = 'forward'"},
            ("transport.modpath",),
            id="modpath-block",
        ),
        pytest.param(
            {"process": TRANSPORT_PROCESS},
            ('simulation.process[1].solvers = "modflow6_prt"',),
            id="a-solver-chosen-without-its-block",
        ),
        pytest.param(
            {
                "tables": (
                    "[flow.sinks_sources.flow_barriers.wall]\n"
                    "line = [[0.0, 0.0], [10.0, 0.0]]\ndepths = [5.0]\nhydchr = 1e-9"
                )
            },
            ("flow.sinks_sources.flow_barriers",),
            id="flow-barrier",
        ),
        pytest.param({"tables": SOIL}, (), id="soil-with-its-mass-balance-only"),
        pytest.param(
            {"tables": SOIL + 'alpha = 0.5\nspinup = "none"'},
            (
                "flow.sinks_sources.recharge.soil.alpha",
                "flow.sinks_sources.recharge.soil.spinup",
            ),
            id="soil-beyond-the-mass-balance",
        ),
        pytest.param(
            {"tables": K_FIELD + CALIBRATION}, ("calibration",), id="the-whole-of-calibration"
        ),
    ],
)
def test_written_keys(tmp_path: Path, sections: dict[str, str], expected: tuple[str, ...]) -> None:
    assert sorted(_keys(tmp_path, **sections)) == sorted(expected)


def test_frozen_copy_names_the_same_keys(tmp_path: Path) -> None:
    cfg = HydroModPyConfig.from_toml(
        _write(
            tmp_path,
            tables="[solver.boussinesq]\npartition_release_depth_m = 0.02\n" + SOIL + "kc = 0.9",
        )
    )
    frozen = tmp_path / "frozen.toml"
    cfg.to_toml(frozen, profile="expert", written_only=True)

    again = HydroModPyConfig.from_snapshot(tomllib.loads(frozen.read_text(encoding="utf-8")))

    assert written_experimental_keys(again) == written_experimental_keys(cfg)
    assert written_experimental_keys(again)


def test_run_says_it_once_loading_says_nothing(tmp_path: Path, caplog) -> None:
    path = _write(tmp_path, tables=ADAPT)

    with caplog.at_level(logging.INFO, logger=WRITTEN_LOGGER):
        project = Project(path)
        assert not _said(caplog)
        project._execute(until_step="validate", no_display=True)

    assert _said(caplog) == [experimental_keys_line(("solver.boussinesq.ts_vi_adapt",))]


def test_check_prints_the_same_line(tmp_path: Path) -> None:
    path = _write(tmp_path, tables=ADAPT)

    result = CliRunner().invoke(["check", str(path)])

    assert result.exit_code == 0, result.stderr
    assert experimental_keys_line(("solver.boussinesq.ts_vi_adapt",)) in result.stderr
    assert "warning:" not in result.stderr


def test_quiet_check_is_silent(tmp_path: Path) -> None:
    path = _write(tmp_path, tables=ADAPT)

    result = CliRunner().invoke(["check", str(path), "--quiet"])

    assert result.exit_code == 0, result.stderr
    assert result.stderr == ""


def test_sites_check_lists_keys_once(tmp_path: Path) -> None:
    wall = (
        "[flow.sinks_sources.flow_barriers.wall]\n"
        "line = [[0.0, 0.0], [10.0, 0.0]]\ndepths = [5.0]\nhydchr = 1e-9\n"
    )
    project = write_sites_project(tmp_path, extra=wall)

    diagnostics = check(project / "project.toml")

    assert len(expand_plan(resolve_project_root(project), project / "project.toml").cases) == 4
    assert [item.path for item in diagnostics if item.code == "experimental_key"] == [
        "flow.sinks_sources.flow_barriers"
    ]


def test_report_says_it_is_experimental() -> None:
    assert "experimental" in (CalibrationReport.__doc__ or "")
    calibration = HydroModPyConfig.model_fields["calibration"]
    assert "experimental" in (calibration.description or "")
