"""The validate step."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.state import PipelineState
from hydromodpy.workflow.steps.validate import ValidateStep

# --- test_export_and_time_are_checked_before_the_solve ---
# Loading the file refuses an export or a date the run cannot honor, naming the
# line, so step 0 never meets one.
#
# ``refuse_an_export_that_cannot_be_written`` reads every ``[[export]]`` name
# against what a run can export and plans each block with the kind of each name.
# ``refuse_a_time_the_run_does_not_hold`` reads every date of ``[[export]]`` and
# ``[display]`` against the stress periods ``[simulation.time]`` resolves to. A
# date takes the period that holds it, so one date is right on a monthly and on
# a daily grid.

_HEAD = """\
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


_TRANSIENT = """\
[flow]
flow_regime = "transient"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2002-12-31"
step_value = "{step}"

"""


_STEADY = '[flow]\nflow_regime = "steady"\n\n'


def _write(tmp_path: Path, body: str, *, grid: str) -> Path:
    path = tmp_path / "project.toml"
    text = _HEAD.format(root=tmp_path.as_posix()) + grid + textwrap.dedent(body)
    path.write_text(text, encoding="utf-8")
    return path


def _load(tmp_path: Path, body: str, *, grid: str) -> HydroModPyConfig:
    return HydroModPyConfig.from_toml(_write(tmp_path, body, grid=grid))


MONTHLY = _TRANSIENT.format(step="1 month")


DAILY = _TRANSIENT.format(step="1 day")


class TestDates:
    def test_two_dates_on_one_period_are_refused_before_the_solve(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match=r"export\[0\]\.time: '2000-01-10' and '2000-02-01'"):
            _load(
                tmp_path,
                '[[export]]\nvariables = "head"\ntime = ["2000-01-10", "2000-02-01"]\n',
                grid=MONTHLY,
            )

    def test_a_period_outside_the_record(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match=r"export\[0\]\.period"):
            _load(
                tmp_path,
                '[[export]]\nvariables = "discharge"\nperiod = ["1990-01-01", "1995-12-31"]\n',
                grid=MONTHLY,
            )

    def test_the_display_time_and_a_figure_time_are_read(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError) as err:
            _load(
                tmp_path,
                """\
                [display]
                time = "1999-12-31"

                [display.overrides.seepage_map]
                time = "2004-01-01"
                """,
                grid=MONTHLY,
            )
        message = str(err.value)
        assert "display.time: 1999-12-31 is outside" in message
        assert "display.overrides.seepage_map.time: 2004-01-01 is outside" in message


class TestNames:
    def test_a_kind_the_format_cannot_hold_names_its_block(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match=r"export\[0\]: 'watershed' is a vector"):
            _load(
                tmp_path, '[[export]]\nvariables = "watershed"\nformat = "netcdf"\n', grid=MONTHLY
            )

    def test_crs_on_a_series_names_its_block(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match=r"export\[0\]: crs .*does not reproject"):
            _load(
                tmp_path, '[[export]]\nvariables = "discharge"\ncrs = "EPSG:4326"\n', grid=MONTHLY
            )

    def test_the_root_of_the_exports_named_is_the_default_folder(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match=r"both write head_last\.tif\."):
            _load(
                tmp_path,
                '[[export]]\nvariables = "head"\ntime = "last"\n\n'
                '[[export]]\nvariables = "head"\ntime = "last"\nfolder = "."\n',
                grid=MONTHLY,
            )


def test_the_validate_step_meets_the_refusals_of_the_loader(tmp_path: Path) -> None:
    path = _write(tmp_path, '[[export]]\nvariables = "head"\ntime = "2010-01-01"\n', grid=MONTHLY)
    state = PipelineState(run_id="r", data={"config_path": path})

    with pytest.raises(ConfigError, match=r"export\[0\]\.time"):
        ValidateStep().run(state)

    path.write_text(path.read_text().replace('"head"', '"hed"'), encoding="utf-8")
    with pytest.raises(ConfigError, match=r"export\[0\]: 'hed'"):
        ValidateStep().run(state)


def test_the_validate_step_refuses_a_built_config_whose_window_moved(tmp_path: Path) -> None:
    cfg = _load(tmp_path, '[[export]]\nvariables = "head"\ntime = "2002-10-15"\n', grid=MONTHLY)
    # An assignment validates its own section, never the rules between sections.
    cfg.simulation.time.end_datetime = "2001-12-31"

    with pytest.raises(ConfigError, match=r"export\[0\]\.time: 2002-10-15 is outside"):
        ValidateStep().run(PipelineState(run_id="r", data={"cfg": cfg}))
