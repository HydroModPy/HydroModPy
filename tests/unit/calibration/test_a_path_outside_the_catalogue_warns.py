"""A ``path`` outside the catalogue warns, since it is the documented way out.

``hmp config targets`` lists what a project exposes, and a parameter that
writes its own ``path`` reaches any value the configuration carries: the
resolution lets it through and the trial writes it. The preflight refused
every such path all the same, so ``hmp config check`` refused what the
launch accepted, and now that every launch runs the preflight it would have
refused the launch too. It warns instead. A path that names no field of the
configuration is still refused, naming the segment that is wrong.
"""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path

import pytest

import hydromodpy as hmp
from hydromodpy.calibration.preflight import preflight_calibration
from hydromodpy.calibration.runners import cli_runner
from hydromodpy.config import HydroModPyConfig

_FILE = """
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

[calibration]
method = "grid"
max_trials = 2
method_options = {{ points_per_dim = 2 }}

[calibration.parameters.dvclose]
bounds = [1e-5, 1e-2]
path = "{path}"
"""

_OUTSIDE = "modflow6.runtime.mf6_outer_dvclose"


def _write(tmp_path: Path, path: str) -> Path:
    target = tmp_path / "calib.toml"
    target.write_text(textwrap.dedent(_FILE.format(path=path)), encoding="utf-8")
    return target


def _findings(target: Path):
    return preflight_calibration(HydroModPyConfig.from_toml(target), source=target)


def test_a_value_the_configuration_carries_outside_the_catalogue_warns(tmp_path) -> None:
    (finding,) = _findings(_write(tmp_path, _OUTSIDE))

    assert finding.severity == "warning"
    assert finding.where == "[calibration.parameters.dvclose]"
    assert _OUTSIDE in finding.detail
    assert "hmp config targets" in finding.detail


def test_the_launch_goes_on_and_says_it_once(tmp_path, monkeypatch, caplog) -> None:
    class _Prepared(RuntimeError):
        pass

    def _prepare(*_args, **_kwargs):
        raise _Prepared

    monkeypatch.setattr(cli_runner, "prepare_trials", _prepare)

    with caplog.at_level(logging.WARNING), pytest.raises(_Prepared):
        hmp.calibrate(_write(tmp_path, _OUTSIDE))

    said = [record for record in caplog.records if _OUTSIDE in record.getMessage()]
    assert len(said) == 1


def test_a_path_that_names_no_field_is_still_refused(tmp_path) -> None:
    (finding,) = _findings(_write(tmp_path, "modflow6.runtime.no_such_option"))

    assert finding.severity == "error"
    assert "no_such_option" in finding.detail
