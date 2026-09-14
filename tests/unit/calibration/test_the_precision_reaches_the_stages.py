"""The precision has to travel from the TOML to the engine that stops on it.

Two routes reach an optimizer, the protocol writing stages and a file writing
them by hand, and both funnel through one build site. What is gated here is the
journey: a precision declared on a protocol stage has to arrive on the phase, and
one that no engine can honour has to be refused before the first solve rather
than when that phase finally starts.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from hydromodpy.calibration.preflight import preflight_calibration
from hydromodpy.calibration.runners.cli_runner import load_toml_calibration
from hydromodpy.core.exceptions import ConfigError

_HEAD = """
[workspace]
name = "precision_probe"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-12-31"
step_value = 1
step_unit = "day"
"""

_PARAMETERS = """
[calibration.parameters.K]
bounds = [1e-8, 1e-2]
transform = "log"
path = "flow.param.K.field.value"
units = "m/s"

[calibration.parameters.Sy]
bounds = [1e-4, 0.5]
transform = "log"
path = "flow.param.Sy.field.value"
units = "-"

"""

_NETWORK_OUTPUT = """
[calibration.outputs.seepage_network]
support = "network"
stream_geometry_path = "network.gpkg"
"""


def _loaded(tmp_path: Path, calibration: str, *, network: bool = True):
    path = tmp_path / "precision.toml"
    tail = _PARAMETERS + (_NETWORK_OUTPUT if network else "")
    path.write_text(textwrap.dedent(_HEAD + calibration + tail), encoding="utf-8")
    (tmp_path / "network.gpkg").write_bytes(b"")
    return load_toml_calibration(path)


def test_a_stage_precision_arrives_on_the_phase(tmp_path: Path) -> None:
    cfg, _raw = _loaded(
        tmp_path,
        """
        [calibration.protocol]
        name = "matching_hydrographic_network"
        steady_tolerance = 0.02
        transient_tolerance = 0.05
        """,
    )
    assert [phase.tolerance for phase in cfg.phases] == [0.02, 0.05]


def test_an_unstated_precision_leaves_the_engine_its_own_default(tmp_path: Path) -> None:
    cfg, _raw = _loaded(
        tmp_path,
        """
        [calibration.protocol]
        name = "matching_hydrographic_network"
        """,
    )
    assert [phase.tolerance for phase in cfg.phases] == [None, None]


def test_a_precision_an_engine_cannot_stop_on_is_refused_before_the_first_solve(
    tmp_path: Path,
) -> None:
    cfg, _raw = _loaded(
        tmp_path,
        """
        [calibration]
        method = "grid"

        [[calibration.phases]]
        name = "sweep_k"
        method = "grid"
        parameters = ["K"]
        tolerance = 0.01
        variable = "discharge"
        objective = "nse"
        """,
        network=False,
    )
    findings = _findings_for(cfg, tmp_path)
    assert any("stops on its evaluation budget" in finding.detail for finding in findings)


def test_saying_the_precision_twice_is_refused_before_the_first_solve(tmp_path: Path) -> None:
    cfg, _raw = _loaded(
        tmp_path,
        """
        [calibration]
        method = "grid"

        [[calibration.phases]]
        name = "steady_k"
        method = "scipy_nelder_mead"
        parameters = ["K"]
        tolerance = 0.01
        variable = "discharge"
        objective = "nse"

        [calibration.phases.optimizer_kwargs]
        xatol = 0.3
        """,
        network=False,
    )
    findings = _findings_for(cfg, tmp_path)
    assert any("both set the stopping rule" in finding.detail for finding in findings)


def _findings_for(calibration, tmp_path: Path):
    class _Config:
        pass

    config = _Config()
    config.calibration = calibration
    return preflight_calibration(config, source=tmp_path / "precision.toml")


def test_a_precision_a_nelder_mead_stage_can_honour_passes_the_preflight(tmp_path: Path) -> None:
    cfg, _raw = _loaded(
        tmp_path,
        """
        [calibration.protocol]
        name = "matching_hydrographic_network"
        steady_method = "scipy_nelder_mead"
        steady_tolerance = 0.02
        """,
    )
    findings = _findings_for(cfg, tmp_path)
    assert not [finding for finding in findings if "tolerance" in finding.detail]


@pytest.mark.parametrize("tolerance", [0.0, -0.1])
def test_a_precision_that_is_not_positive_is_refused_at_load(
    tmp_path: Path, tolerance: float
) -> None:
    with pytest.raises(ConfigError, match="greater than 0"):
        _loaded(
            tmp_path,
            f"""
            [calibration.protocol]
            name = "matching_hydrographic_network"
            steady_tolerance = {tolerance}
            """,
        )
