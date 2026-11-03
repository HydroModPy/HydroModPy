"""The preflight runs at the start of every launch, on the document the launch runs.

``hmp config check`` was the only caller of the preflight. ``hmp calibrate``,
``hmp run``, ``--dry-run`` and the API went straight to the preparation of the
model, so a file the check refused was launched anyway, and refused only when
the faulty part was reached, sometimes after hours of solves. Every launch now
passes one gate first, on the effective document (``--set``, ``--overlay`` and
``HMP_SET_*`` written in, the protocol expanded) and phase by phase, with the
overrides of each phase. Its errors stop the launch on the config code before
anything is prepared, its warnings print once.
"""

from __future__ import annotations

import logging
import textwrap
import warnings
from pathlib import Path

import pytest

import hydromodpy as hmp
from hydromodpy.calibration.preflight import preflight_calibration
from hydromodpy.calibration.runners import cli_runner, programmatic_runner, staged_runner
from hydromodpy.cli.helpers import EXIT_CONFIG
from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigError
from tests._helpers.cli_runner import CliRunner

_REPO = Path(__file__).resolve().parents[3]
_EXAMPLE_21 = _REPO / "examples/projects/21_nancon_network_calibration/auto_sfr_drn.toml"

_BASE = """
[workspace]

[workflow]
mode = "calibration"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-12-31"
step_value = 1
step_unit = "day"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[geographic]
source_mode = "synthetic"

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

_PARAMETERS = """
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

# A block reading an output nobody declared: the file loads, the preflight refuses it.
_GHOST_BLOCK = """
[[calibration.objective_blocks]]
name = "gap"
metric = "rmse"
uses_outputs = ["ghost"]
"""

_PHASE = """
[[calibration.phases]]
name = "only"
method = "grid"
parameters = ["K"]
method_options = { points_per_dim = 2 }
max_trials = 4
"""

# A network output whose geometry is there: the file passes the preflight.
_NETWORK = """
[calibration.parameters.Sy]
bounds = [1e-3, 0.3]
path = "flow.param.Sy.field.value"
units = "-"

[calibration.outputs.net]
support = "network"
stream_geometry_path = "here.gpkg"

[[calibration.objective_blocks]]
name = "gap"
metric = "distance_gap"
uses_outputs = ["net"]
"""


class _Prepared(RuntimeError):
    """Raised in place of the preparation of the model: the launch got past the gate."""


@pytest.fixture
def prepared(monkeypatch) -> list[str]:
    """Record every preparation the launch reaches, and stop there."""
    reached: list[str] = []

    def _prepare(cfg_path, **_kwargs):
        reached.append(Path(cfg_path).name)
        raise _Prepared("the launch reached the preparation of the model")

    for module in (cli_runner, staged_runner, programmatic_runner):
        monkeypatch.setattr(module, "prepare_trials", _prepare)
    return reached


def _write(tmp_path: Path, *sections: str, name: str = "calib.toml") -> Path:
    path = tmp_path / name
    body = _BASE + "".join(textwrap.dedent(section) for section in sections)
    path.write_text(body, encoding="utf-8")
    (tmp_path / "here.gpkg").write_text("", encoding="utf-8")
    return path


def _refused(tmp_path: Path, *, phased: bool = False) -> Path:
    return _write(tmp_path, _PARAMETERS, _GHOST_BLOCK, *((_PHASE,) if phased else ()))


class TestEveryLaunchPathRunsIt:
    """Each launch refuses the ghost block before the model is prepared."""

    @pytest.mark.parametrize("phased", [False, True], ids=["one_search", "phases"])
    def test_hmp_calibrate(self, tmp_path, prepared, phased: bool) -> None:
        result = CliRunner().invoke(["calibrate", str(_refused(tmp_path, phased=phased))])

        assert result.exit_code == EXIT_CONFIG, result.output
        assert "ghost" in result.stderr
        assert prepared == []

    @pytest.mark.parametrize("phased", [False, True], ids=["one_search", "phases"])
    def test_hmp_calibrate_dry_run(self, tmp_path, prepared, phased: bool) -> None:
        result = CliRunner().invoke(
            ["calibrate", str(_refused(tmp_path, phased=phased)), "--dry-run"]
        )

        assert result.exit_code == EXIT_CONFIG, result.output
        assert "ghost" in result.stderr
        assert "session:" not in result.stderr

    def test_hmp_run_in_calibration_mode(self, tmp_path, prepared) -> None:
        result = CliRunner().invoke(["run", str(_refused(tmp_path))])

        assert result.exit_code == EXIT_CONFIG, result.output
        assert "ghost" in result.stderr
        assert prepared == []

    def test_hmp_run_dry_run_in_calibration_mode(self, tmp_path, prepared) -> None:
        result = CliRunner().invoke(["run", str(_refused(tmp_path)), "--dry-run"])

        assert result.exit_code == EXIT_CONFIG, result.output
        assert "ghost" in result.stderr

    @pytest.mark.parametrize("phased", [False, True], ids=["one_search", "phases"])
    def test_hmp_calibrate_from_python(self, tmp_path, prepared, phased: bool) -> None:
        with pytest.raises(ConfigError, match="ghost"):
            hmp.calibrate(_refused(tmp_path, phased=phased))
        assert prepared == []

    def test_project_calibrate_on_a_file(self, tmp_path, prepared) -> None:
        from hydromodpy.project import Project

        path = _refused(tmp_path)
        with Project(path, headless=True) as project, pytest.raises(ConfigError, match="ghost"):
            project.calibrate(config_path=path)
        assert prepared == []

    def test_project_calibrate_on_its_own_configuration(self, tmp_path, prepared) -> None:
        config = HydroModPyConfig.from_toml(_refused(tmp_path))

        with pytest.raises(ConfigError, match="ghost"):
            hmp.calibrate(config)
        assert prepared == []

    def test_project_calibrate_in_python_mode(self, tmp_path, prepared) -> None:
        from hydromodpy.project import Project

        with Project(_write(tmp_path), headless=True) as project:
            with pytest.raises(ConfigError, match="ghost"):
                project.calibrate(
                    parameters={"K": {"bounds": [1e-7, 1e-3]}},
                    objective_blocks=[{"name": "gap", "metric": "rmse", "uses_outputs": ["ghost"]}],
                )
        assert prepared == []

    def test_a_file_that_passes_reaches_the_preparation(self, tmp_path, prepared) -> None:
        with pytest.raises(_Prepared):
            hmp.calibrate(_write(tmp_path, _PARAMETERS, _NETWORK))
        assert prepared == ["calib.toml"]


class TestTheEffectiveDocument:
    """What the launch runs is what is checked: overrides and overlays included."""

    def test_a_set_that_breaks_the_file_is_refused(self, tmp_path, prepared) -> None:
        path = _write(tmp_path, _PARAMETERS, _NETWORK)

        result = CliRunner().invoke(
            [
                "calibrate",
                str(path),
                "--set",
                'calibration.outputs.net.stream_geometry_path="nowhere.gpkg"',
            ]
        )

        assert result.exit_code == EXIT_CONFIG, result.output
        assert "nowhere.gpkg" in result.stderr
        assert prepared == []

    def test_an_environment_override_is_checked(self, tmp_path, prepared, monkeypatch) -> None:
        path = _write(tmp_path, _PARAMETERS, _NETWORK)
        monkeypatch.setenv(
            "HMP_SET_calibration__outputs__net__stream_geometry_path", "nowhere.gpkg"
        )

        result = CliRunner().invoke(["calibrate", str(path), "--dry-run"])

        assert result.exit_code == EXIT_CONFIG, result.output
        assert "nowhere.gpkg" in result.stderr

    def test_an_overlay_is_checked(self, tmp_path, prepared) -> None:
        path = _write(tmp_path, _PARAMETERS, _NETWORK)
        overlay = tmp_path / "broken.toml"
        overlay.write_text(
            '[calibration.outputs.net]\nstream_geometry_path = "nowhere.gpkg"\n', encoding="utf-8"
        )

        result = CliRunner().invoke(["run", str(path), "--overlay", str(overlay)])

        assert result.exit_code == EXIT_CONFIG, result.output
        assert "nowhere.gpkg" in result.stderr
        assert prepared == []


class TestWarnings:
    def test_a_warning_prints_once_and_the_launch_goes_on(self, tmp_path, prepared, caplog) -> None:
        path = _write(tmp_path, _PARAMETERS, _NETWORK)

        with caplog.at_level(logging.WARNING), pytest.raises(_Prepared):
            hmp.calibrate(path)

        ridge = [record for record in caplog.records if "form a ridge" in record.getMessage()]
        assert len(ridge) == 1
        assert prepared == ["calib.toml"]


@pytest.fixture(scope="module")
def config() -> HydroModPyConfig:
    """Example 21 as the run loads it."""
    if not _EXAMPLE_21.is_file():
        pytest.skip("example 21 is not in this checkout")
    with warnings.catch_warnings():
        # A renamed key it still spells the old way is not what this file tests.
        warnings.simplefilter("ignore")
        return HydroModPyConfig.from_toml(_EXAMPLE_21)


class TestExample21:
    """Its first phase turns the SFR reaches off in its own overrides.

    The preflight read the project's base ``flow.active_bc``, where SFR is on,
    and refused the K-moving network search of that phase, which runs without
    it. Each phase is now checked with its overrides written in.
    """

    def test_it_is_not_refused(self, config) -> None:
        errors = [
            finding
            for finding in preflight_calibration(config, source=_EXAMPLE_21)
            if finding.severity == "error"
        ]

        assert errors == []

    def test_the_same_phase_without_its_overrides_is_refused(self, config) -> None:
        stripped = config.model_copy(deep=True)
        stripped.calibration.phases[0].overrides = {}

        details = " ".join(
            finding.detail
            for finding in preflight_calibration(stripped, source=_EXAMPLE_21)
            if finding.severity == "error"
        )

        assert "SFR (routed stream reaches) is active" in details
