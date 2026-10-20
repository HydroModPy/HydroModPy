"""A calibration run from an effective copy is named after the file the user named.

``--set`` and ``--overlay`` write a temporary copy beside the file, and the
calibration reads its case from the stem of the file that carries
``[calibration]``. The session came out named ``.cal.effective.<random>``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from hydromodpy.calibration.runners.session import calibration_case_name
from hydromodpy.cli.effective_toml import materialize_effective_toml
from tests._helpers.cli_runner import CliRunner

_CAL = """\
[calibration]
seed = 3

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
path = "flow.param.K.field.value"
"""


def _args(**fields) -> argparse.Namespace:
    given = {"overlay": [], "set_overrides": [], "case": None, **fields}
    return argparse.Namespace(**given)


def _case_of_the_copy(config: Path, args: argparse.Namespace) -> str:
    temp, _raw, _lineage = materialize_effective_toml(config, args=args)
    assert temp is not None
    try:
        return calibration_case_name(temp)
    finally:
        temp.unlink()


def test_the_copy_of_a_file_without_a_name_is_named_after_the_file(tmp_path: Path) -> None:
    config = tmp_path / "cal.toml"
    config.write_text(_CAL, encoding="utf-8")

    assert _case_of_the_copy(config, _args(set_overrides=["calibration.seed=5"])) == "cal"


def test_the_copy_of_a_file_with_a_name_keeps_that_name(tmp_path: Path) -> None:
    config = tmp_path / "cal.toml"
    config.write_text('[simulation]\nname = "declared"\n' + _CAL, encoding="utf-8")

    assert _case_of_the_copy(config, _args(set_overrides=["calibration.seed=5"])) == "declared"


def test_a_name_inherited_from_the_base_config_does_not_name_the_copy(tmp_path: Path) -> None:
    (tmp_path / "project.toml").write_text('[simulation]\nname = "base"\n', encoding="utf-8")
    config = tmp_path / "cal.toml"
    config.write_text('base_config = "project.toml"\n' + _CAL, encoding="utf-8")

    assert _case_of_the_copy(config, _args(set_overrides=["calibration.seed=5"])) == "cal"


def test_case_names_the_copy_before_anything_else(tmp_path: Path) -> None:
    config = tmp_path / "cal.toml"
    config.write_text('[simulation]\nname = "declared"\n' + _CAL, encoding="utf-8")

    assert _case_of_the_copy(config, _args(set_overrides=["calibration.seed=5"], case="x")) == "x"


def test_hmp_run_with_set_hands_the_calibration_a_file_that_names_the_case(
    tmp_path: Path, monkeypatch
) -> None:
    import hydromodpy as hmp

    config = tmp_path / "cal.toml"
    config.write_text('[workflow]\nmode = "calibration"\n' + _CAL, encoding="utf-8")
    seen: list[str] = []

    def fake_run(path, **_kwargs):
        seen.append(calibration_case_name(Path(path)))

    monkeypatch.setattr(hmp, "run", fake_run)
    CliRunner().invoke(["run", str(config), "--set", "calibration.seed=5"])

    assert seen == ["cal"]
