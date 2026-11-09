"""``hmp calibrate`` takes ``--set``, ``--overlay`` and ``--case`` as ``hmp run`` does.

A variant of a calibration (another seed, another budget, another name) needs
no copy of the file, and the command writes none: the verbs that only read take
the ``[calibration]`` section of the changed document. The case is named after
the file the user named, or after ``--case``.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.cli.helpers import EXIT_CONFIG
from tests._helpers.cli_runner import CliRunner

_CAL = """\
[calibration]
seed = 3
save_runs = "best_n"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
path = "flow.param.K.field.value"
"""


def _config(tmp_path: Path) -> Path:
    config = tmp_path / "cal.toml"
    config.write_text(_CAL, encoding="utf-8")
    return config


def _leftovers(tmp_path: Path) -> list[str]:
    return sorted(path.name for path in tmp_path.iterdir() if ".effective." in path.name)


def test_set_changes_what_the_calibration_would_do(tmp_path: Path) -> None:
    config = _config(tmp_path)

    plain = CliRunner().invoke(["calibrate", str(config), "--dry-run"])
    varied = CliRunner().invoke(
        ["calibrate", str(config), "--dry-run", "--set", 'calibration.save_runs="all"']
    )

    assert "save_runs = best_n" in plain.stderr
    assert "save_runs = all" in varied.stderr
    assert "case: cal\n" in varied.stderr
    assert _leftovers(tmp_path) == []


def test_set_reaches_the_section_expand_prints(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        ["calibrate", str(_config(tmp_path)), "--expand", "--set", "calibration.seed=5"]
    )

    assert result.exit_code == 0
    assert "seed = 5" in result.stdout
    assert "cal.toml declares no protocol" in result.stdout


def test_an_overlay_applies(tmp_path: Path) -> None:
    config = _config(tmp_path)
    overlay = tmp_path / "all.toml"
    overlay.write_text('[calibration]\nsave_runs = "all"\n', encoding="utf-8")

    result = CliRunner().invoke(["calibrate", str(config), "--dry-run", "--overlay", str(overlay)])

    assert "save_runs = all" in result.stderr
    assert "case: cal\n" in result.stderr
    assert _leftovers(tmp_path) == []


def test_case_names_the_session(tmp_path: Path) -> None:
    result = CliRunner().invoke(["calibrate", str(_config(tmp_path)), "--dry-run", "--case", "x"])

    assert result.exit_code == 0
    assert "case: x\n" in result.stderr
    assert "session: sessions/x" in result.stderr
    assert "calibrated run: runs/x " in result.stderr
    assert _leftovers(tmp_path) == []


def test_set_without_a_case_keeps_the_name_of_the_file(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        ["calibrate", str(_config(tmp_path)), "--dry-run", "--set", "calibration.seed=5"]
    )

    assert "case: cal\n" in result.stderr
    assert "session: sessions/cal" in result.stderr


def test_a_malformed_override_is_a_config_error(tmp_path: Path) -> None:
    result = CliRunner().invoke(["calibrate", str(_config(tmp_path)), "--set", "oops"])

    assert result.exit_code == EXIT_CONFIG
    assert "Invalid override" in result.stderr
    assert _leftovers(tmp_path) == []
