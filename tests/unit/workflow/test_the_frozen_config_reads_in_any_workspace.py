"""The frozen ``config.toml`` of a run names its inputs so that any copy of the workspace reads it.

A file of ``data/<variable>/`` is written by its bare name, a declared folder
by its name, a file of the project relative to it: no path of the machine.
Read back from the project root, in the workspace it was frozen in or in
another one holding the same data, the configuration points at the same files.
"""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

from hydromodpy.config import HydroModPyConfig
from hydromodpy.workflow.steps.prepare_solver.dispatch import portable_config_document

PROJECT = """\
[site]
name = "nancon"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
catch_def = "from_outlet_coord"
dem_init_path = "DEM_armorican_massif.tif"
x_outlet = 389285.9
y_outlet = 6816518.7
snap_dist = "150 m"
buff_area = "10%"

[data]
types = ["hydrography", "hydrometry"]

[[data.hydrography.sources]]
source = "custom"
path = "nancon_stream_network.gpkg"

[[data.hydrometry.sources]]
source = "custom"
path = "hydrometry"
station_ids = ["NANCON"]
"""


def _workspace(root: Path) -> Path:
    for relative in (
        "data/dem/DEM_armorican_massif.tif",
        "data/hydrography/nancon_stream_network.gpkg",
    ):
        (root / relative).parent.mkdir(parents=True, exist_ok=True)
        (root / relative).write_bytes(b"x")
    (root / "data" / "hydrometry").mkdir(parents=True)
    project = root / "projects" / "nancon"
    project.mkdir(parents=True)
    (project / "project.toml").write_text(PROJECT, encoding="utf-8")
    return project


def _frozen(project: Path) -> Path:
    cfg = HydroModPyConfig.from_toml(project / "project.toml")
    run_dir = project / "runs" / "nancon"
    run_dir.mkdir(parents=True)
    path = run_dir / "config.toml"
    path.write_text(portable_config_document(cfg, run_dir, project), encoding="utf-8")
    return path


def test_the_frozen_config_names_its_inputs_by_their_portable_form(tmp_path: Path) -> None:
    project = _workspace(tmp_path / "laptop")

    frozen = _frozen(project)

    text = frozen.read_text(encoding="utf-8")
    assert str(tmp_path) not in text
    payload = tomllib.loads(text)
    assert payload["geographic"]["catchment"]["dem_init_path"] == "DEM_armorican_massif.tif"
    sources = payload["data"]
    assert sources["hydrography"]["sources"][0]["path"] == "nancon_stream_network.gpkg"
    assert sources["hydrometry"]["sources"][0]["path"] == "hydrometry"


def test_another_workspace_reads_the_frozen_config_on_its_own_data(
    tmp_path: Path, monkeypatch
) -> None:
    frozen = _frozen(_workspace(tmp_path / "laptop"))
    other = _workspace(tmp_path / "cluster" / "ws")
    copied = other / "runs" / "nancon" / "config.toml"
    copied.parent.mkdir(parents=True)
    shutil.copy2(frozen, copied)
    monkeypatch.chdir(tmp_path)

    from_file = HydroModPyConfig.from_toml(copied)
    snapshot = tomllib.loads(copied.read_text(encoding="utf-8"))
    snapshot.setdefault("workspace", {})["project_root"] = str(other)
    from_snapshot = HydroModPyConfig.from_snapshot(snapshot)

    data = (tmp_path / "cluster" / "ws" / "data").resolve()
    for cfg in (from_file, from_snapshot):
        assert Path(cfg.geographic.catchment.dem_init_path) == data / "dem" / (
            "DEM_armorican_massif.tif"
        )
        assert Path(cfg.data.hydrometry.sources[0].path) == data / "hydrometry"
        assert Path(cfg.data.hydrography.sources[0].path) == data / "hydrography" / (
            "nancon_stream_network.gpkg"
        )
