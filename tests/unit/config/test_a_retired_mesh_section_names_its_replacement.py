"""Each retired mesh key is refused, and the message names what to write instead."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.exceptions import ConfigValidationError

_HEAD = '[workspace]\n\n[workflow]\nmode = "simulation"\n\n'
_SYNTHETIC = '[geographic]\nsource_mode = "synthetic"\n\n'


def _load(tmp_path: Path, body: str) -> HydroModPyConfig:
    path = tmp_path / "project.toml"
    path.write_text(_HEAD + _SYNTHETIC + body, encoding="utf-8")
    return HydroModPyConfig.from_toml(path)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ('[mesh_catchment]\nconstraints_mode = "rivers_only"\n', ["[mesh]", "cell_size", "engine"]),
        ("[mesh_catchment_batch]\n", ["no replacement"]),
        ('[mesh_input]\nmesh_path = "a.msh"\n', ["[mesh.triangle] path", "engine"]),
        (
            "[modflow6.sgrid.planar]\nmode = 'keep_native'\n",
            ["sgrid.planar", "[mesh]", "cell_size"],
        ),
        ("[modflownwt.sgrid.planar]\nmode = 'keep_native'\n", ["sgrid.planar", "[mesh]", "shape"]),
        ('[modflow6.sgrid]\ngrid_dual = "voronoi"\n', ["sgrid.grid_dual", "[mesh] engine"]),
        ('[modflownwt.sgrid]\ngrid_dual = "triangle"\n', ["sgrid.grid_dual", "[mesh] engine"]),
    ],
)
def test_a_retired_key_in_a_file_is_refused_with_its_replacement(
    tmp_path: Path, body: str, expected: list[str]
) -> None:
    with pytest.raises(ConfigValidationError) as excinfo:
        _load(tmp_path, body)
    message = str(excinfo.value)
    for fragment in expected:
        assert fragment in message


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        ({"mesh_catchment": {}}, "[mesh]"),
        ({"mesh_catchment_batch": {}}, "no replacement"),
        ({"mesh_input": {"mesh_path": "a.msh"}}, "[mesh.triangle] path"),
        ({"mesh_catchment": None}, "[mesh]"),
    ],
)
def test_a_retired_section_in_python_is_refused(payload: dict, fragment: str) -> None:
    with pytest.raises(ValueError, match=r"\[mesh") as excinfo:
        HydroModPyConfig.model_validate(payload)
    assert fragment in str(excinfo.value)


@pytest.mark.parametrize("solver", ["modflow6", "modflownwt"])
@pytest.mark.parametrize("key", ["planar", "grid_dual"])
def test_a_retired_sgrid_key_in_python_is_refused(solver: str, key: str) -> None:
    value = {} if key == "planar" else "voronoi"
    with pytest.raises(ValueError, match=rf"sgrid\.{key} is replaced by \[mesh\]"):
        HydroModPyConfig.model_validate({solver: {"sgrid": {key: value}}})


def test_the_mesh_section_replaces_them_and_resolves_its_file(tmp_path: Path) -> None:
    cfg = _load(
        tmp_path,
        '[mesh]\nengine = "voronoi"\ncell_size = 150.0\nriver_cell_size = 25.0\n'
        '[mesh.triangle]\npath = "meshes/catchment.msh"\n'
        '[mesh.voronoi]\nseeds = "triangulation"\n',
    )
    assert cfg.mesh is not None
    assert cfg.mesh.engine == "voronoi"
    assert cfg.mesh.triangle is not None
    assert cfg.mesh.triangle.path == (tmp_path / "meshes" / "catchment.msh").resolve()


def test_the_root_model_declares_the_mesh_in_place_of_the_retired_sections() -> None:
    fields = HydroModPyConfig.model_fields
    assert "mesh" in fields
    assert "mesh_catchment" not in fields
    assert "mesh_input" not in fields
    renamed = fields["mesh"].json_schema_extra
    assert "mesh_catchment" in str(renamed)
    assert "modflow6.sgrid.grid_dual" in str(renamed)
