"""``hmp doctor --fix-config`` carries a file across the keys the loader now refuses.

The loader refuses a retired key with the line to delete or write. The doctor
does that edit for the keys whose replacement is mechanical, so a config of an
earlier schema loads again after one pass. ``[site]`` is not one of them: it
names the catchment, which only the user knows.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from hydromodpy.config.config_migration import (
    fix_config_file,
    migrate_config_doc,
    migrate_config_doc_on_load,
)


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "project.toml"
    path.write_text(body, encoding="utf-8")
    return path


def _fix(tmp_path: Path, body: str) -> tuple[dict, list[str]]:
    path = _write(tmp_path, body)
    changes = fix_config_file(path)
    return tomllib.loads(path.read_text(encoding="utf-8")), changes


def test_the_project_root_line_is_dropped_and_its_neighbours_kept(tmp_path: Path) -> None:
    parsed, changes = _fix(tmp_path, '[workspace]\nproject_root = "."\ndata_dir = "../../data"\n')
    assert parsed["workspace"] == {"data_dir": "../../data"}
    assert any("workspace.project_root" in change for change in changes)


def test_an_empty_workspace_table_goes_with_its_project_root(tmp_path: Path) -> None:
    parsed, _ = _fix(tmp_path, '[workspace]\nproject_root = "."\n\n[simulation]\nname = "a"\n')
    assert "workspace" not in parsed
    assert parsed["simulation"]["name"] == "a"


def test_if_exists_replace_becomes_version(tmp_path: Path) -> None:
    parsed, changes = _fix(tmp_path, '[simulation]\nname = "a"\nif_exists = "replace"\n')
    assert parsed["simulation"]["if_exists"] == "version"
    assert any("if_exists" in change and "replace" in change for change in changes)


def test_if_exists_fail_is_left_alone(tmp_path: Path) -> None:
    parsed, changes = _fix(tmp_path, '[simulation]\nname = "a"\nif_exists = "fail"\n')
    assert parsed["simulation"]["if_exists"] == "fail"
    assert changes == []


def test_the_display_output_dir_is_dropped(tmp_path: Path) -> None:
    parsed, changes = _fix(tmp_path, '[display]\nenabled = true\noutput_dir = "figures"\n')
    assert parsed["display"] == {"enabled": True}
    assert any("display.output_dir" in change for change in changes)


@pytest.mark.parametrize("value", ["true", "false"])
def test_rerun_best_with_outputs_is_dropped_whatever_it_said(tmp_path: Path, value: str) -> None:
    parsed, changes = _fix(
        tmp_path,
        f'[calibration]\nsave_runs = "best_n"\nrerun_best_with_outputs = {value}\n',
    )
    assert parsed["calibration"] == {"save_runs": "best_n"}
    assert any("rerun_best_with_outputs" in change for change in changes)


def test_the_keys_a_calibration_phase_writes_as_overrides_are_dropped(
    tmp_path: Path,
) -> None:
    parsed, _ = _fix(
        tmp_path,
        '[[calibration.phases]]\nname = "p"\n[calibration.phases.overrides]\n'
        '"display.output_dir" = "x"\n"calibration.rerun_best_with_outputs" = true\n'
        '"simulation.if_exists" = "replace"\n',
    )
    overrides = parsed["calibration"]["phases"][0]["overrides"]
    assert overrides == {"simulation.if_exists": "version"}


def test_a_second_pass_changes_nothing(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '[workspace]\nproject_root = "."\n[simulation]\nif_exists = "replace"\n'
        '[display]\noutput_dir = "f"\n[calibration]\nrerun_best_with_outputs = true\n',
    )
    assert fix_config_file(path)
    assert fix_config_file(path) == []


def test_a_file_without_these_keys_is_left_alone(tmp_path: Path) -> None:
    path = _write(tmp_path, '[simulation]\nname = "a"\n[display]\nenabled = true\n')
    before = path.read_text(encoding="utf-8")
    assert fix_config_file(path) == []
    assert path.read_text(encoding="utf-8") == before


def test_the_read_path_still_leaves_the_refused_keys_for_the_loader() -> None:
    """Only the doctor edits these: a load must keep refusing them, with the line to delete."""
    raw = {
        "workspace": {"project_root": "."},
        "simulation": {"if_exists": "replace"},
        "display": {"output_dir": "figures"},
        "calibration": {"rerun_best_with_outputs": True},
    }
    snapshot = tomllib.loads(
        '[workspace]\nproject_root = "."\n[simulation]\nif_exists = "replace"\n'
        '[display]\noutput_dir = "figures"\n[calibration]\nrerun_best_with_outputs = true\n'
    )
    assert migrate_config_doc(raw) == []
    assert migrate_config_doc_on_load(raw) == []
    assert raw == snapshot


_LEGACY_PROJECT = """
[workspace]
project_root = "."

[geographic]
source_mode = "synthetic"
crs_project = "EPSG:2154"

[simulation]
name = "legacy"
if_exists = "replace"

[simulation.time]
start_datetime = "2015-01-01"
end_datetime = "2015-12-31"
step_value = "1 day"

[[simulation.process]]
id = "flow_main"
kind = "flow"
solvers = ["modflow6"]

[display]
output_dir = "figures"
"""


def test_a_legacy_file_is_refused_then_loads_after_the_doctor(tmp_path: Path) -> None:
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.core.exceptions import ConfigValidationError

    path = _write(tmp_path, _LEGACY_PROJECT)
    with pytest.raises(ConfigValidationError, match="project_root"):
        HydroModPyConfig.from_toml(path)

    fix_config_file(path)

    config = HydroModPyConfig.from_toml(path)
    assert config.simulation.if_exists == "version"


def test_a_real_catchment_without_a_site_is_still_refused_by_name() -> None:
    """[site] stays manual: the loader's message tells what to write."""
    from hydromodpy.config.hydromodpy_config import require_site_for_real_catchment
    from hydromodpy.core.exceptions import ConfigError

    class _Geographic:
        catch_def = "from_outlet_coord"

    class _Config:
        geographic = _Geographic()
        site = None
        sites = None

    with pytest.raises(ConfigError, match=r"Add \[site\] with name"):
        require_site_for_real_catchment(_Config())
