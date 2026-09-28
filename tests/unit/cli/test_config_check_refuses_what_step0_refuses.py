"""``hmp config check`` refuses what step 0 of ``hmp run`` refuses.

A date outside ``[simulation.time]`` and an export name no run can hold used
to pass ``hmp config check`` and fail at step 0. The check now runs the same
two functions, so the promise "refused at hmp config check" holds.
"""

from __future__ import annotations

from pathlib import Path

from tests._helpers.cli_runner import CliRunner

_BODY = """\
[workspace]
project_root = "{root}"

[workflow]
mode = "simulation"

[geographic]
source_mode = "synthetic"

[simulation]
name = "nancon"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2002-12-31"
step_value = "1 month"

[[simulation.process]]
id = "flow_main"
type = "flow"
solvers = ["modflow6"]

[flow]
flow_regime = "transient"

"""


def _check(tmp_path: Path, extra: str):
    path = tmp_path / "project.toml"
    path.write_text(_BODY.format(root=tmp_path.as_posix()) + extra, encoding="utf-8")
    return CliRunner().invoke(["config", "check", str(path)])


def test_a_config_whose_requests_hold_passes(tmp_path: Path) -> None:
    result = _check(
        tmp_path,
        '[[export]]\nvariables = ["head", "watertable_depth"]\ntime = "2002-10-15"\n\n'
        '[display]\ntime = "2002-10-15"\n',
    )

    assert result.exit_code == 0, result.stderr
    assert "OK:" in result.stdout


def test_a_date_outside_the_record_is_refused(tmp_path: Path) -> None:
    result = _check(tmp_path, '[display]\ntime = "2005-01-01"\n')

    assert result.exit_code == 14
    assert "display.time: 2005-01-01 is outside the record" in result.stderr


def test_an_export_name_no_run_holds_is_refused(tmp_path: Path) -> None:
    result = _check(tmp_path, '[[export]]\nvariables = "hed"\n')

    assert result.exit_code == 14
    assert "export[0]: 'hed'" in result.stderr


def test_two_blocks_writing_one_file_are_refused(tmp_path: Path) -> None:
    result = _check(
        tmp_path,
        '[[export]]\nvariables = "discharge"\n\n[[export]]\nvariables = ["discharge"]\n',
    )

    assert result.exit_code == 14
    assert "export[0] and export[1] both write nancon/discharge.csv" in result.stderr
