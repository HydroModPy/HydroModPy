"""Step 0 refuses an export or a date the run cannot honour, naming the line.

``check_export_variables`` reads every ``[[export]]`` name against what a run
can export and plans each block with the kind of each name.
``check_time_selectors`` reads every date of ``[[export]]`` and ``[display]``
against the stress periods ``[simulation.time]`` resolves to. A date takes the
period that holds it, so one date is right on a monthly and on a daily grid.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.steps.validate import (
    ValidateStep,
    check_export_variables,
    check_time_selectors,
)

_HEAD = """\
[workspace]
project_root = "{root}"

[workflow]
mode = "simulation"

[geographic]
source_mode = "synthetic"

[simulation]
name = "nancon"

[[simulation.process]]
id = "flow_main"
type = "flow"
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
    @pytest.mark.parametrize("grid", [MONTHLY, DAILY], ids=["monthly", "daily"])
    def test_one_date_is_right_on_every_grid(self, tmp_path: Path, grid: str) -> None:
        cfg = _load(
            tmp_path,
            """\
            [[export]]
            variables = "head"
            time = ["2002-10-15", "first", "last"]

            [[export]]
            variables = "discharge"
            period = ["2001-01-01", "2002-12-31"]

            [display]
            time = "2002-10-15"
            """,
            grid=grid,
        )

        check_time_selectors(cfg)

    @pytest.mark.parametrize("grid", [MONTHLY, DAILY], ids=["monthly", "daily"])
    def test_a_date_outside_the_record_names_its_block(self, tmp_path: Path, grid: str) -> None:
        cfg = _load(
            tmp_path,
            '[[export]]\nvariables = "head"\n\n[[export]]\nvariables = "head"\n'
            'time = "2003-06-01"\n',
            grid=grid,
        )

        with pytest.raises(ConfigError, match=r"export\[1\]\.time: 2003-06-01 is outside") as err:
            check_time_selectors(cfg)
        assert "2000-01-01 to 2003-01-01" in str(err.value)

    def test_a_period_outside_the_record(self, tmp_path: Path) -> None:
        cfg = _load(
            tmp_path,
            '[[export]]\nvariables = "discharge"\nperiod = ["1990-01-01", "1995-12-31"]\n',
            grid=MONTHLY,
        )

        with pytest.raises(ConfigError, match=r"export\[0\]\.period"):
            check_time_selectors(cfg)

    def test_a_step_index_counts_the_periods_of_the_grid(self, tmp_path: Path) -> None:
        body = '[[export]]\nvariables = "head"\ntime = 1018\n'
        check_time_selectors(_load(tmp_path, body, grid=DAILY))

        with pytest.raises(ConfigError, match=r"export\[0\]\.time: period index 1018"):
            check_time_selectors(_load(tmp_path, body, grid=MONTHLY))

    def test_the_display_time_and_a_figure_time_are_read(self, tmp_path: Path) -> None:
        cfg = _load(
            tmp_path,
            """\
            [display]
            time = "1999-12-31"

            [display.overrides.seepage_map]
            time = "2004-01-01"
            """,
            grid=MONTHLY,
        )

        with pytest.raises(ConfigError) as err:
            check_time_selectors(cfg)
        message = str(err.value)
        assert "display.time: 1999-12-31 is outside" in message
        assert "display.overrides.seepage_map.time: 2004-01-01 is outside" in message

    def test_a_steady_run_without_a_window_has_no_dates(self, tmp_path: Path) -> None:
        cfg = _load(
            tmp_path,
            '[[export]]\nvariables = "head"\ntime = "last"\n\n'
            '[[export]]\nvariables = "head"\ntime = "2002-10-15"\n',
            grid=_STEADY,
        )

        with pytest.raises(ConfigError, match=r'export\[1\]\.time: .*no dates; write "last"'):
            check_time_selectors(cfg)


class TestNames:
    def test_the_names_of_every_kind_are_known(self, tmp_path: Path) -> None:
        cfg = _load(
            tmp_path,
            """\
            [[export]]
            variables = ["watershed", "hydrographic_network_reference"]

            [[export]]
            variables = ["watershed_dem", "watershed_fill"]

            [[export]]
            variables = ["head", "watertable_depth", "simulated_active_network"]
            time = "2002-10-15"

            [[export]]
            variables = ["discharge", "discharge_obs", "budget"]

            [[export]]
            variables = "all"
            format = "package"
            """,
            grid=MONTHLY,
        )

        check_export_variables(cfg)

    def test_an_unknown_name_names_its_block_and_prints_the_vocabulary(
        self, tmp_path: Path
    ) -> None:
        cfg = _load(
            tmp_path,
            '[[export]]\nvariables = "head"\n\n[[export]]\nvariables = ["hed"]\n',
            grid=MONTHLY,
        )

        with pytest.raises(ConfigError) as err:
            check_export_variables(cfg)
        message = str(err.value)
        assert "export[1]: 'hed'" in message
        assert "fields: " in message
        assert "vector layers: watershed" in message
        assert "tables: budget" in message

    def test_a_kind_the_format_cannot_hold_names_its_block(self, tmp_path: Path) -> None:
        cfg = _load(
            tmp_path, '[[export]]\nvariables = "watershed"\nformat = "netcdf"\n', grid=MONTHLY
        )

        with pytest.raises(ConfigError, match=r"export\[0\]: 'watershed' is a vector"):
            check_export_variables(cfg)

    def test_crs_on_a_series_names_its_block(self, tmp_path: Path) -> None:
        cfg = _load(
            tmp_path, '[[export]]\nvariables = "discharge"\ncrs = "EPSG:4326"\n', grid=MONTHLY
        )

        with pytest.raises(ConfigError, match=r"export\[0\]: crs .*does not reproject"):
            check_export_variables(cfg)

    def test_two_blocks_that_write_one_file_are_refused(self, tmp_path: Path) -> None:
        cfg = _load(
            tmp_path,
            """\
            [[export]]
            variables = "head"
            time = "2002-10-15"

            [[export]]
            variables = "discharge"

            [[export]]
            variables = ["head", "watertable_depth"]
            time = "2002-10-15"
            """,
            grid=MONTHLY,
        )

        with pytest.raises(
            ConfigError, match=r"export\[0\] and export\[2\] both write nancon/head_2002-10-15"
        ):
            check_export_variables(cfg)

    def test_a_folder_keeps_two_blocks_apart(self, tmp_path: Path) -> None:
        cfg = _load(
            tmp_path,
            '[[export]]\nvariables = "head"\ntime = "last"\n\n'
            '[[export]]\nvariables = "head"\ntime = "last"\nfolder = "deliver"\n',
            grid=MONTHLY,
        )

        check_export_variables(cfg)


def test_the_validate_step_runs_both_checks(tmp_path: Path) -> None:
    path = _write(tmp_path, '[[export]]\nvariables = "head"\ntime = "2010-01-01"\n', grid=MONTHLY)
    state = PipelineState(run_id="r", data={"config_path": path})

    with pytest.raises(ConfigError, match=r"export\[0\]\.time"):
        ValidateStep().run(state)

    path.write_text(path.read_text().replace('"head"', '"hed"'), encoding="utf-8")
    with pytest.raises(ConfigError, match=r"export\[0\]: 'hed'"):
        ValidateStep().run(state)
