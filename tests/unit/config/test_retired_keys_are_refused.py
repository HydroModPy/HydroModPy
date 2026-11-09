"""A key retired by the outputs and orchestration target is refused by name.

A section that only a pre-release of 2.0 wrote is refused in a file by the list of
``prerelease_forms.txt``, with the way out. The model still says what replaces it, which
a Python caller and a sealed snapshot read.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
import tomlkit
from pydantic import ValidationError

from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.config_migration import PRERELEASE_FORMS, fix_config_file
from hydromodpy.config.section_loader import RETIRED_SECTIONS
from hydromodpy.core.exceptions import ConfigValidationError
from hydromodpy.solver.base.simulation_config import SimulationConfig

SYNTHETIC = {"geographic": {"source_mode": "synthetic"}}


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "project.toml"
    path.write_text('[geographic]\nsource_mode = "synthetic"\n\n' + text, encoding="utf-8")
    return path


def test_if_exists_replace_names_what_to_write() -> None:
    with pytest.raises(ValidationError, match="Write 'version'"):
        SimulationConfig(if_exists="replace")
    assert SimulationConfig(if_exists="fail").if_exists == "fail"


@pytest.mark.parametrize(
    ("key", "advice"),
    [
        ("study_area_name", r"\[site\] name"),
        ("outlet_x", "geographic.catchment.x_outlet"),
        ("outlet_y", "geographic.catchment.y_outlet"),
    ],
)
def test_a_retired_simulation_key_names_its_replacement(key: str, advice: str) -> None:
    with pytest.raises(ValidationError, match=advice):
        SimulationConfig.model_validate({key: 1.0 if key != "study_area_name" else "x"})


@pytest.mark.parametrize(
    ("mode", "advice"),
    [
        ("testbed", r"\[sites.recipes\]"),
        ("comparison", "hmp report compare"),
    ],
)
def test_a_retired_workflow_mode_names_its_replacement(mode: str, advice: str) -> None:
    with pytest.raises(ValidationError, match=advice):
        HydroModPyConfig.model_validate({**SYNTHETIC, "workflow": {"mode": mode}})


def test_the_testbed_section_is_refused_in_a_file(tmp_path: Path) -> None:
    path = _write(tmp_path, '[testbed]\nprofile = "generic"\n')
    with pytest.raises(ConfigValidationError, match=r"\[testbed\] is no longer supported"):
        HydroModPyConfig.from_toml(path)


def test_the_testbed_section_is_refused_in_python() -> None:
    with pytest.raises(ValidationError, match=r"\[sites.recipes\]"):
        HydroModPyConfig.model_validate({**SYNTHETIC, "testbed": {}})


def test_a_project_root_written_in_a_file_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, '[workspace]\nproject_root = "."\n')
    with pytest.raises(ConfigValidationError, match="Delete the line"):
        HydroModPyConfig.from_toml(path)


def test_the_doctor_leaves_a_project_root_and_the_loader_refuses_it(tmp_path: Path) -> None:
    """The line names a folder only the user knows, so the doctor writes nothing on it."""
    path = _write(tmp_path, '[workspace]\nproject_root = "."\ndata_dir = "../../data"\n')
    written = path.read_text(encoding="utf-8")

    assert fix_config_file(path) == []

    assert path.read_text(encoding="utf-8") == written
    with pytest.raises(ConfigValidationError, match="Delete the line"):
        HydroModPyConfig.from_toml(path)


def test_if_exists_replace_is_refused_in_a_file_with_what_to_write(tmp_path: Path) -> None:
    """No run is replaced. Only a pre-release wrote ``replace``: a file is told the doctor
    of 2.0.x, which wrote ``version``, and the doctor of this version writes nothing."""
    path = tmp_path / "project.toml"
    path.write_text(
        tomlkit.dumps({**SYNTHETIC, "simulation": {"if_exists": "replace"}}), encoding="utf-8"
    )
    written = path.read_text(encoding="utf-8")

    with pytest.raises(ConfigValidationError, match="holds simulation.if_exists, written by"):
        HydroModPyConfig.from_toml(path)
    with pytest.raises(ConfigValidationError, match="hydromodpy~=2.0.0"):
        fix_config_file(path)
    assert path.read_text(encoding="utf-8") == written


def test_a_real_catchment_without_a_site_is_still_refused_by_name() -> None:
    """``[site]`` names the catchment, which only its author knows: the loader says what to write."""
    from hydromodpy.config.cross_checks import require_site_for_real_catchment
    from hydromodpy.core.exceptions import ConfigError

    class _Geographic:
        catch_def = "from_outlet_coord"

    class _Config:
        geographic = _Geographic()
        site = None
        sites = None

    with pytest.raises(ConfigError, match=r"Add \[site\] with name"):
        require_site_for_real_catchment(_Config())


def test_the_project_root_is_the_folder_holding_project_toml(tmp_path: Path) -> None:
    (tmp_path / "project.toml").write_text(
        '[geographic]\nsource_mode = "synthetic"\n', encoding="utf-8"
    )
    nested = tmp_path / "variants"
    nested.mkdir()
    variant = nested / "run_a.toml"
    variant.write_text('base_config = "../project.toml"\n', encoding="utf-8")
    cfg = HydroModPyConfig.from_toml(variant)
    assert cfg.workspace.project_root == tmp_path.resolve()


def test_a_python_caller_gives_the_project_root_as_the_base(tmp_path: Path) -> None:
    cfg = HydroModPyConfig.from_dict(SYNTHETIC, base_dir=tmp_path)
    assert cfg.workspace.project_root == tmp_path.resolve()


def test_a_document_in_memory_never_writes_the_project_root(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match="project_root is not a key of a file"):
        HydroModPyConfig.from_dict(
            {**SYNTHETIC, "workspace": {"project_root": str(tmp_path)}}, base_dir=tmp_path
        )


def test_the_project_root_is_never_written_back_to_toml(tmp_path: Path) -> None:
    source = tmp_path / "project.toml"
    source.write_text('[geographic]\nsource_mode = "synthetic"\n', encoding="utf-8")
    cfg = HydroModPyConfig.from_toml(source)
    frozen = cfg.to_toml(tmp_path / "frozen.toml", profile="expert")
    written = tomllib.loads(frozen.read_text(encoding="utf-8"))
    assert "project_root" not in written.get("workspace", {})
    # The frozen copy reloads: its project root comes from where it sits.
    assert HydroModPyConfig.from_toml(frozen).workspace.project_root == tmp_path.resolve()


def test_the_project_root_is_out_of_the_request_id(tmp_path: Path) -> None:
    from hydromodpy.results.request_identity import request_id

    config = HydroModPyConfig.model_validate(SYNTHETIC).model_dump(mode="json")
    moved = {**config, "workspace": {**config["workspace"], "project_root": "/elsewhere"}}
    assert request_id(config, {}, edition="2.1") == request_id(moved, {}, edition="2.1")


def test_the_mesh_catchment_batch_section_stays_refused() -> None:
    with pytest.raises(ValidationError, match="no replacement"):
        HydroModPyConfig.model_validate({**SYNTHETIC, "mesh_catchment_batch": {}})


@pytest.mark.parametrize(
    ("section", "advice"),
    [
        ("analysis", "hmp report compare over sealed runs"),
        ("hydrometry", r"\[data.hydrometry\]"),
    ],
)
def test_a_retired_root_section_names_its_replacement(
    tmp_path: Path, section: str, advice: str
) -> None:
    path = _write(tmp_path, f"[{section}]\nx = 1\n")
    with pytest.raises(ConfigValidationError, match=advice):
        HydroModPyConfig.from_toml(path)
    with pytest.raises(ValidationError, match=advice):
        HydroModPyConfig.model_validate({**SYNTHETIC, section: {}})


@pytest.mark.parametrize("section", sorted(RETIRED_SECTIONS))
def test_every_retired_root_section_is_refused_with_its_sentence(
    tmp_path: Path, section: str
) -> None:
    ending = re.escape(RETIRED_SECTIONS[section][-40:])
    path = _write(tmp_path, f"[{section}]\nx = 1\n")
    pre_release = section in {form.path for form in PRERELEASE_FORMS}
    with pytest.raises(
        ConfigValidationError, match="written by a pre-release" if pre_release else ending
    ):
        HydroModPyConfig.from_toml(path)
    with pytest.raises(ValidationError, match=ending):
        HydroModPyConfig.model_validate({**SYNTHETIC, section: {}})


@pytest.mark.parametrize(
    ("key", "advice"),
    [
        ("output_root", r"runs/<run>/"),
        ("solver_scratch_folder", "HMP_SCRATCH_ROOT"),
        ("share_folder", r"runs/<run>/"),
        ("catch_name", r"\[site\] name"),
    ],
)
def test_a_retired_workspace_key_names_its_replacement(
    tmp_path: Path, key: str, advice: str
) -> None:
    path = _write(tmp_path, f'[workspace]\n{key} = "x"\n')
    with pytest.raises(ConfigValidationError, match=advice):
        HydroModPyConfig.from_toml(path)
