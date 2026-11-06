"""The effective TOML that ``hmp run`` and ``hmp calibrate`` build from a file, overlays and ``--set``."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from hydromodpy.calibration.runners.session import calibration_case_name
from hydromodpy.cli.effective_toml import ConfigFileError, materialize_effective_toml
from tests._helpers.cli_runner import CliRunner


def test_the_trace_names_the_key_the_override_set(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "project.toml"
    config.write_text('[simulation]\nname = "case"\n', encoding="utf-8")
    monkeypatch.setenv("HMP_SET_flow__param__K__field__value", "1e-5")

    temp, raw, lineage = materialize_effective_toml(config, args=_args())
    if temp is not None:
        temp.unlink()

    assert raw["flow"]["param"]["K"]["field"]["value"] == 1e-5
    assert lineage == {"flow.param.K.field.value": 1e-5}


def test_a_syntax_error_in_a_base_file_names_that_file(tmp_path: Path) -> None:
    (tmp_path / "base.toml").write_text("[workflow\nmode = 'simulation'\n", encoding="utf-8")
    child = tmp_path / "child.toml"
    child.write_text('base_config = "base.toml"\n', encoding="utf-8")

    with pytest.raises(ConfigFileError, match=r"Invalid TOML in .*base\.toml: Expected"):
        materialize_effective_toml(child, args=_args())


def test_a_circular_chain_is_a_file_error(tmp_path: Path) -> None:
    (tmp_path / "a.toml").write_text('base_config = "b.toml"\n', encoding="utf-8")
    (tmp_path / "b.toml").write_text('base_config = "a.toml"\n', encoding="utf-8")

    with pytest.raises(ConfigFileError, match="circular base_config chain"):
        materialize_effective_toml(tmp_path / "a.toml", args=_args())


def test_a_bad_set_item_is_still_an_override_error(tmp_path: Path) -> None:
    config = tmp_path / "ok.toml"
    config.write_text("[workflow]\nmode = 'simulation'\n", encoding="utf-8")

    with pytest.raises(ValueError, match="--set expects PATH=VALUE") as caught:
        materialize_effective_toml(config, args=_args(set_overrides=["foo"]))
    assert not isinstance(caught.value, ConfigFileError)


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
    config = tmp_path / "cal.toml"
    config.write_text('[workflow]\nmode = "calibration"\n' + _CAL, encoding="utf-8")
    seen: list[str] = []

    def fake_dispatch(_workflow, path, **_kwargs):
        seen.append(calibration_case_name(Path(path)))
        return {}

    monkeypatch.setattr("hydromodpy.project.dispatch.workflow.dispatch_workflow", fake_dispatch)
    monkeypatch.setattr("hydromodpy.calibration.preflight.preflight_launch", lambda *a, **k: None)
    CliRunner().invoke(["run", str(config), "--set", "calibration.seed=5"])

    assert seen == ["cal"]
