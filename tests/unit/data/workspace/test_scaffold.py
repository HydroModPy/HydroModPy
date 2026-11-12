"""The scaffold of a data workspace: folders, example files and project creation.

A scaffold never overwrites a file the user edited. A project name is a short
lowercase word that is valid on Windows too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.io import filesystem
from hydromodpy.data.workspace.scaffold import DEFAULT_ROOT, create_project, scaffold
from tests._helpers.windows_os import WindowsOs


@pytest.fixture(scope="module")
def ws(tmp_path_factory):
    return scaffold(tmp_path_factory.mktemp("hmp"))


SHIPPED = [
    pytest.param(
        [
            f"data/geology/geology_custom_EXAMPLE.{ext}"
            for ext in ("gpkg", "shp", "geojson", "tif", "csv")
        ],
        id="geology, one example per format",
    ),
    pytest.param(
        [f"data/dem/dem_custom_EXAMPLE.{ext}" for ext in ("tif", "asc", "nc")],
        id="dem, one example per format",
    ),
    pytest.param(
        [
            "data/precipitation/precipitation_custom_LOC.csv",
            "data/precipitation/precipitation_custom_EXAMPLE.nc",
            "data/precipitation/precipitation_custom_EXAMPLE.tif",
        ],
        id="precipitation grids in nc and tif",
    ),
    pytest.param(
        [
            "projects/README.md",
            "projects/example/project.toml",
            "projects/example/run_demo.toml",
        ],
        id="example project and projects readme",
    ),
]


@pytest.mark.parametrize("files", SHIPPED)
def test_files_shipped_with_the_scaffold(ws, files):
    assert [name for name in files if not (ws / name).exists()] == []


def test_projects_and_data_folders(ws):
    assert (ws / "projects").is_dir()
    assert (ws / "data").is_dir()


def test_default_root():
    assert DEFAULT_ROOT == Path.home() / "hydromodpy"


EDITED_LOCS = [
    pytest.param(
        True,
        "data/hydrometry/hydrometry_custom_LOC.csv",
        "id,x,y,crs,unit\nST01,-1.5,48.0,EPSG:4326,m3/s\n",
        "ST01",
        id="with examples",
    ),
    pytest.param(
        False,
        "data/recharge/recharge_custom_LOC.csv",
        "id,x,y,crs,unit\nMYROW,1.0,2.0,EPSG:4326,mm/day\n",
        "MYROW",
        id="without examples",
    ),
]


@pytest.mark.parametrize(("with_examples", "name", "text", "marker"), EDITED_LOCS)
def test_scaffold_keeps_user_edits(tmp_path, with_examples, name, text, marker):
    root = scaffold(tmp_path / "hmp", with_examples=with_examples)
    (root / name).write_text(text)

    scaffold(tmp_path / "hmp", with_examples=with_examples)

    assert marker in (root / name).read_text()


def test_create_project_keeps_user_edits(tmp_path):
    root = scaffold(tmp_path / "hydromodpy", with_examples=False)
    project_dir = create_project(root, "my_project")
    (project_dir / "project.toml").write_text("# custom\n")

    create_project(root, "my_project")

    assert (project_dir / "project.toml").read_text() == "# custom\n"


def projects_in(root):
    return [path.name for path in (root / "projects").iterdir()]


BAD_NAMES = [
    pytest.param("My Project", "Write 'my_project'", id="capitals and space"),
    pytest.param("Canut", "Write 'canut'", id="capital"),
    pytest.param("a" * 41, "41 characters", id="too long"),
    pytest.param("con", "Windows reserves", id="reserved con"),
    pytest.param("COM1", "is refused", id="reserved COM1"),
    pytest.param("nul", "Windows reserves", id="reserved nul"),
    pytest.param("", "cannot be empty", id="empty"),
    pytest.param("a/b", "is refused", id="slash"),
    pytest.param("é", "is refused", id="accent"),
]


@pytest.mark.parametrize(("name", "said"), BAD_NAMES)
def test_a_bad_name_is_refused_and_creates_nothing(tmp_path, name, said):
    root = scaffold(tmp_path / "hydromodpy", with_examples=False)

    with pytest.raises(ConfigError, match=said):
        create_project(root, name)

    assert projects_in(root) == ["README.md"]


def test_a_folder_too_long_for_windows_is_refused(tmp_path, monkeypatch):
    root = scaffold(tmp_path / ("w" * 90), with_examples=False)
    monkeypatch.setattr(filesystem, "os", WindowsOs())

    with pytest.raises(ConfigError, match="may hold 99 characters at most"):
        create_project(root, "my_project")

    assert projects_in(root) == ["README.md"]
