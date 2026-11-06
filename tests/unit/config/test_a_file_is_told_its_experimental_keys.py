"""A run and ``hmp config check`` name the experimental keys a file wrote, and only those.

The mark is metadata on the field. The walker reads it through ``written_fields``,
so a key the file left at its default never counts. A loader sets some fields a
file never wrote (``calibration = None``), and a selector is stable for most of its
values, so both are pinned here on real files. The line informs: nothing refuses
and no warning is raised.
"""

from __future__ import annotations

import logging
import tomllib
import warnings
from pathlib import Path

import pytest

from hydromodpy.calibration.preflight import preflight_launch
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners.trial import prepare_trials
from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.config_kit.written import (
    experimental_keys_line,
    log_experimental_keys,
    written_experimental_keys,
)
from hydromodpy.core.console.progress import MILESTONE_KEY
from hydromodpy.physics.flow.sinks_sources.container import FlowSinksSourcesConfig
from hydromodpy.project import Project
from hydromodpy.project.check import check_project
from hydromodpy.project.dispatch.workflow import run_overview
from hydromodpy.solver.base.solver_config import CustomBackend, SolverConfig
from hydromodpy.workflow.steps import ResolveStep, ValidateStep
from tests._helpers.cli_runner import CliRunner
from tests.unit.project.launch.test_sites_plan import write_sites_project

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

ADAPT = "[flow.runtime]\nts_vi_adapt = true\n"

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


def test_only_the_marked_key_the_file_wrote_is_named(tmp_path: Path) -> None:
    # `partition_release_depth_m` is marked and written, `first_period_steady` is
    # written and not marked, `vi_substeps_per_period` is marked and left at its
    # default. The sections nobody wrote give nothing either: `calibration` is set
    # to None by its loader, and `transport.modpath` is built from its defaults.
    cfg = HydroModPyConfig.from_toml(
        _write(tmp_path, tables="[flow.runtime]\npartition_release_depth_m = 0.02")
    )

    assert cfg.flow.first_period_steady is False
    assert cfg.flow.runtime.vi_substeps_per_period == 1
    assert written_experimental_keys(cfg) == ("flow.runtime.partition_release_depth_m",)


def test_a_file_that_writes_no_marked_key_gets_no_line(tmp_path: Path, caplog) -> None:
    cfg = HydroModPyConfig.from_toml(_write(tmp_path))

    with caplog.at_level(logging.INFO, logger=WRITTEN_LOGGER):
        log_experimental_keys(cfg)

    assert written_experimental_keys(cfg) == ()
    assert not _said(caplog)


@pytest.mark.parametrize(
    ("sections", "expected"),
    [
        pytest.param(
            {"tables": "[flow.runtime]\npartition_release_depth_m = 0.05"},
            ("flow.runtime.partition_release_depth_m",),
            id="written-at-the-value-of-its-default",
        ),
        pytest.param(
            {"tables": '[flow.runtime]\nsurface_interaction_model = "vi_obstacle"'},
            ('flow.runtime.surface_interaction_model = "vi_obstacle"',),
            id="marked-value-of-a-selector",
        ),
        pytest.param(
            {"tables": '[flow.runtime]\nsurface_interaction_model = "regularized_partition"'},
            (),
            id="stable-value-of-the-same-selector",
        ),
        pytest.param(
            {"tables": "[flow.runtime]\nts_vi_adapt = true\nmax_iterations = 40"},
            ("flow.runtime.max_iterations", "flow.runtime.ts_vi_adapt"),
            id="runtime-knobs",
        ),
        pytest.param(
            {"geographic": 'domain_extent = "watershed"'},
            ("geographic.domain_extent",),
            id="domain-extent",
        ),
        pytest.param(
            {"tables": "[transport.modflow6prt.parameters]\nwrite_track_binary = false"},
            ("transport.modflow6prt",),
            id="a-marked-section-is-one-entry",
        ),
        pytest.param(
            {"tables": "[transport.modpath.parameters]\ntrack_dir = 'forward'"},
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
def test_what_a_file_wrote_is_named(
    tmp_path: Path, sections: dict[str, str], expected: tuple[str, ...]
) -> None:
    assert sorted(_keys(tmp_path, **sections)) == sorted(expected)


def test_a_mapping_below_a_section_is_walked() -> None:
    wall = {"line": [[0.0, 0.0], [1.0, 0.0]], "depths": [1.0], "hydchr": 1e-9}
    sinks = FlowSinksSourcesConfig.model_validate(
        {"lakes": {"dam": {"bedleak": 1e-6, "initial_stage": "81.82 m", "cutoff_wall": wall}}}
    )

    assert written_experimental_keys(sinks) == ("lakes.dam.cutoff_wall",)


def test_a_custom_solver_is_named_and_a_built_in_one_is_not() -> None:
    assert written_experimental_keys(SolverConfig(backend=CustomBackend(name="mine"))) == (
        "backend.name",
    )
    assert written_experimental_keys(SolverConfig()) == ()


def test_the_copy_a_run_freezes_names_the_same_keys(tmp_path: Path) -> None:
    cfg = HydroModPyConfig.from_toml(
        _write(
            tmp_path,
            tables="[flow.runtime]\npartition_release_depth_m = 0.02\n" + SOIL + "kc = 0.9",
        )
    )
    frozen = tmp_path / "frozen.toml"
    cfg.to_toml(frozen, profile="expert", written_only=True)

    again = HydroModPyConfig.from_snapshot(tomllib.loads(frozen.read_text(encoding="utf-8")))

    assert written_experimental_keys(again) == written_experimental_keys(cfg)
    assert written_experimental_keys(again)


def test_the_line_is_a_milestone_and_not_a_warning(tmp_path: Path, caplog) -> None:
    cfg = HydroModPyConfig.from_toml(_write(tmp_path, tables=ADAPT))

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with caplog.at_level(logging.INFO, logger=WRITTEN_LOGGER):
            log_experimental_keys(cfg)

    [record] = caplog.records
    assert record.levelno == logging.INFO
    assert getattr(record, MILESTONE_KEY) is True
    assert record.getMessage() == experimental_keys_line(("flow.runtime.ts_vi_adapt",))


def test_a_run_says_it_once_and_loading_says_nothing(tmp_path: Path, caplog) -> None:
    path = _write(tmp_path, tables=ADAPT)

    with caplog.at_level(logging.INFO, logger=WRITTEN_LOGGER):
        project = Project(path)
        assert not _said(caplog)
        project._execute(until_step="validate", no_display=True)

    assert _said(caplog) == [experimental_keys_line(("flow.runtime.ts_vi_adapt",))]


def test_an_overview_says_it_once(tmp_path: Path, caplog, monkeypatch) -> None:
    path = _write(
        tmp_path, geographic='domain_extent = "watershed"', tables='[site]\nname = "marks"'
    )
    cfg = HydroModPyConfig.from_toml(path)

    class _Launcher:
        """The overview without its downloads and its report."""

        def __init__(self, config_path: Path) -> None:
            self.cfg = cfg

        def run(self, claim: object, *, config_hash: str) -> dict[str, str]:
            return {"mode": "data_overview"}

    monkeypatch.setattr("hydromodpy.workflow.overview.DataOverviewLauncher", _Launcher)
    with caplog.at_level(logging.INFO, logger=WRITTEN_LOGGER):
        run_overview(path)

    assert _said(caplog) == [experimental_keys_line(("geographic.domain_extent",))]


def test_a_calibration_says_it_at_its_gate_and_its_trials_say_nothing(
    tmp_path: Path, caplog
) -> None:
    path = _write(tmp_path, tables=ADAPT + K_FIELD + CALIBRATION)

    class _Flow:
        """The first step a trial runs: everything before it is the prepared prefix."""

        name = "flow"
        config_sections = ("flow",)

    with caplog.at_level(logging.INFO, logger=WRITTEN_LOGGER):
        preflight_launch(path)
        said_at_the_gate = _said(caplog)
        caplog.clear()
        prepare_trials(
            path,
            override_paths={"K": "flow.param.K.field.value"},
            steps=(ValidateStep(), ResolveStep(), _Flow()),
        )

    assert said_at_the_gate == [experimental_keys_line(("flow.runtime.ts_vi_adapt", "calibration"))]
    assert not _said(caplog)


def test_config_check_prints_the_same_line(tmp_path: Path) -> None:
    path = _write(tmp_path, tables=ADAPT)

    result = CliRunner().invoke(["config", "check", str(path)])

    assert result.exit_code == 0, result.stderr
    assert experimental_keys_line(("flow.runtime.ts_vi_adapt",)) in result.stderr
    assert "warning:" not in result.stderr


def test_quiet_keeps_config_check_silent_on_a_sound_file(tmp_path: Path) -> None:
    path = _write(tmp_path, tables=ADAPT)

    result = CliRunner().invoke(["config", "check", str(path), "--quiet"])

    assert result.exit_code == 0, result.stderr
    assert result.stderr == ""


def test_a_calibration_check_lists_its_section_without_a_verdict_change(tmp_path: Path) -> None:
    report = check_project(_write(tmp_path, tables=K_FIELD + CALIBRATION))

    assert report.ok
    assert report.experimental_keys == ("calibration",)
    assert not report.lines()


def test_a_sites_check_lists_the_keys_of_its_cases_once(tmp_path: Path) -> None:
    wall = (
        "[flow.sinks_sources.flow_barriers.wall]\n"
        "line = [[0.0, 0.0], [10.0, 0.0]]\ndepths = [5.0]\nhydchr = 1e-9\n"
    )
    project = write_sites_project(tmp_path, extra=wall)

    report = check_project(project / "project.toml")

    assert report.n_cases == 4
    assert report.experimental_keys == ("flow.sinks_sources.flow_barriers",)


def test_the_report_says_its_shape_is_experimental() -> None:
    assert "experimental" in (CalibrationReport.__doc__ or "")
    calibration = HydroModPyConfig.model_fields["calibration"]
    assert "experimental" in (calibration.description or "")
