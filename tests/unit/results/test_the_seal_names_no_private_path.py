"""The inputs of a seal are named relative to the workspace, never by a path of the machine.

``manifest.inputs`` records each declared file relative to the workspace root
(``data/dem/...``), and its ``declared_path`` in the form the frozen
``config.toml`` writes (a bare name found in ``data/``). ``inputs.json`` lists
every loaded file and every declared file the loads did not name, the DEM a
catchment is cut from among them, with the provider and licence of its sidecar.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from hydromodpy.results.record import RunRecord
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store


@dataclass
class _Entry:
    role: str
    category: str
    original_path: str
    canonical_path: Path
    portable: bool = True


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "ws"
    (workspace / "workspace.toml").parent.mkdir(parents=True)
    (workspace / "workspace.toml").write_text("[workspace]\n", encoding="utf-8")
    project = workspace / "projects" / "nancon"
    project.mkdir(parents=True)
    (project / "project.toml").write_text("", encoding="utf-8")
    return workspace, project


def test_the_seal_names_its_inputs_relative_to_the_workspace(tmp_path: Path) -> None:
    workspace, project = _workspace(tmp_path)
    dem = workspace / "data" / "dem" / "DEM_armorican_massif.tif"
    dem.parent.mkdir(parents=True)
    dem.write_bytes(b"a regional DEM")
    dem.with_name(dem.name + ".json").write_text(
        json.dumps({"source": "ign_geoplateforme_dem", "sha256": "x", "license": "etalab-2.0"}),
        encoding="utf-8",
    )
    folder = workspace / "data" / "hydrometry"
    folder.mkdir(parents=True)
    store = open_run_store(project, "run", create_zarr=False)
    (store.run_dir / RUN_CONFIG_FILENAME).write_text("[flow]\n", encoding="utf-8")
    store.register_tracked_files(
        store.sim_id,
        [
            _Entry("dem", "data", str(dem), dem.resolve()),
            _Entry("hydrometry", "data", str(folder), folder.resolve()),
        ],
    )

    record = seal_completed(store)

    tracked = {entry.role: entry for entry in record.tracked_inputs}
    assert tracked["dem"].path == "data/dem/DEM_armorican_massif.tif"
    assert tracked["dem"].declared_path == "DEM_armorican_massif.tif"
    assert tracked["hydrometry"].path == "data/hydrometry"
    assert tracked["hydrometry"].declared_path == "hydrometry"
    (declared,) = record.inputs
    assert declared.variable == "dem"
    assert declared.path == "data/dem/DEM_armorican_massif.tif"
    assert declared.provider == "ign_geoplateforme_dem"
    assert declared.license == "etalab-2.0"
    manifest = (store.run_dir / "manifest.json").read_text(encoding="utf-8")
    assert str(tmp_path) not in manifest
    assert str(tmp_path) not in (store.run_dir / "inputs.json").read_text(encoding="utf-8")
    assert RunRecord.read(store.run_dir).inputs == record.inputs
