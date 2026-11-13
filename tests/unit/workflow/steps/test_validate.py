"""The validate step meets the refusals of the config loader.

Loading a file refuses an export or a date the run cannot honor, naming the line,
so step 0 never meets one. A date takes the stress period that holds it, so one
date is right on a monthly and on a daily grid.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.validate import ValidateStep

HEAD = """\
[workspace]

[workflow]
mode = "simulation"

[geographic]
source_mode = "synthetic"

[simulation]
name = "nancon"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

"""


TRANSIENT = """\
[flow]
flow_regime = "transient"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2002-12-31"
step_value = "{step}"

"""


def _write(tmp_path: Path, body: str, *, grid: str) -> Path:
    path = tmp_path / "project.toml"
    text = HEAD.format(root=tmp_path.as_posix()) + grid + textwrap.dedent(body)
    path.write_text(text, encoding="utf-8")
    return path


def _load(tmp_path: Path, body: str, *, grid: str) -> HydroModPyConfig:
    return HydroModPyConfig.from_toml(_write(tmp_path, body, grid=grid))


MONTHLY = TRANSIENT.format(step="1 month")


REFUSALS = [
    pytest.param(
        '[[export]]\nvariables = "head"\ntime = ["2000-01-10", "2000-02-01"]\n',
        r"export\[0\]\.time: '2000-01-10' and '2000-02-01'",
        id="two dates on one period",
    ),
    pytest.param(
        '[[export]]\nvariables = "discharge"\nperiod = ["1990-01-01", "1995-12-31"]\n',
        r"export\[0\]\.period",
        id="period outside the record",
    ),
    pytest.param(
        '[[export]]\nvariables = "watershed"\nformat = "netcdf"\n',
        r"export\[0\]: 'watershed' is a vector",
        id="kind the format cannot hold",
    ),
    pytest.param(
        '[[export]]\nvariables = "discharge"\ncrs = "EPSG:4326"\n',
        r"export\[0\]: crs .*does not reproject",
        id="crs on a series",
    ),
    pytest.param(
        '[[export]]\nvariables = "head"\ntime = "last"\n\n'
        '[[export]]\nvariables = "head"\ntime = "last"\nfolder = "."\n',
        r"both write head_last\.tif\.",
        id="root folder is the default folder",
    ),
]


@pytest.mark.parametrize(("body", "match"), REFUSALS)
def test_loader_refusals(tmp_path: Path, body: str, match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        _load(tmp_path, body, grid=MONTHLY)


def test_display_times_are_read(tmp_path: Path) -> None:
    body = """\
        [[display.figure]]
        variable = "head"
        time = "1999-12-31"
        """
    with pytest.raises(ConfigError) as err:
        _load(tmp_path, body, grid=MONTHLY)

    assert "display.figure[0].time: 1999-12-31 is outside" in str(err.value)


def test_step_meets_loader_refusals(tmp_path: Path) -> None:
    path = _write(tmp_path, '[[export]]\nvariables = "head"\ntime = "2010-01-01"\n', grid=MONTHLY)
    state = PipelineState(run_id="r", data={"config_path": path})

    with pytest.raises(ConfigError, match=r"export\[0\]\.time"):
        ValidateStep().run(state)

    path.write_text(path.read_text().replace('"head"', '"hed"'), encoding="utf-8")
    with pytest.raises(ConfigError, match=r"export\[0\]: 'hed'"):
        ValidateStep().run(state)


def test_step_refuses_a_window_that_moved(tmp_path: Path) -> None:
    cfg = _load(tmp_path, '[[export]]\nvariables = "head"\ntime = "2002-10-15"\n', grid=MONTHLY)
    # An assignment validates its own section, never the rules between sections.
    cfg.simulation.time.end_datetime = "2001-12-31"

    with pytest.raises(ConfigError, match=r"export\[0\]\.time: 2002-10-15 is outside"):
        ValidateStep().run(PipelineState(run_id="r", data={"cfg": cfg}))
