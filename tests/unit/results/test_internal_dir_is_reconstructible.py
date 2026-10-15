"""The project ``.hmp/`` is strictly rebuildable: delete it, reindex, nothing is missing.

``rm -rf <project>/.hmp`` followed by ``hmp catalog reindex`` must give back
the same project: the same runs under the same directories, with the same
status, parameters and metrics, and not one file outside ``.hmp/`` touched.
State that cannot be rebuilt (the trash, the attempts, the launch journals,
the plans) lives in visible folders, never under ``.hmp/``.
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.state.paths import (
    INTERNAL_DIRNAME,
    PROJECT_MARKER_FILENAME,
    catalog_path_for,
    internal_dir,
)
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.reindex import rebuild_index
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME

_RUN_STATE_SQL = (
    "SELECT s.storage_basename, s.name, s.name_stem, s.version_int, "
    "CAST(s.sim_id AS VARCHAR), st.code, s.project, s.config_hash, "
    "s.n_cells, s.n_layers, s.n_timesteps, s.zarr_path "
    "FROM simulations s JOIN statuses st ON s.status_id = st.id"
)
_PARAMETER_STATE_SQL = (
    "SELECT s.storage_basename, p.param_name, COALESCE(p.zone_id, ''), p.value "
    "FROM parameters p JOIN simulations s ON s.sim_id = p.sim_id"
)
_METRIC_STATE_SQL = (
    "SELECT s.storage_basename, m.station_id, m.variable, m.metric_name, m.value, m.n_samples "
    "FROM metrics m JOIN simulations s ON s.sim_id = m.sim_id"
)


def _seal_run(catalog: Catalog, name: str, *, nse: float, k: float) -> str:
    sim_id = str(uuid.uuid4())
    registration = catalog.register_simulation(
        sim_id,
        project="demo",
        solver="modflow6",
        name=name,
        n_cells=4,
        n_layers=1,
        n_timesteps=3,
        config={"flow": {"k": k}},
    )
    if registration.zarr is not None:
        registration.zarr.close()
    catalog.write_parameters(
        sim_id,
        [
            {"param_name": "K", "value": k, "unit": "m/s"},
            {"param_name": "sy", "value": 0.02, "unit": "1", "zone_id": "upper"},
        ],
    )
    index = pd.date_range("2020-01-01", periods=3, freq="D")
    catalog.write_timeseries(sim_id, "P01", "head", pd.Series(np.ones(3), index=index))
    catalog.write_metric(sim_id, "P01", "nse", nse, variable="discharge", n_samples=3)
    (catalog.run_dir_for(sim_id) / RUN_CONFIG_FILENAME).write_text(
        f"[flow]\nk = {k}\n", encoding="utf-8"
    )
    catalog.finalize(sim_id, status="completed")
    return sim_id


def _index_state(project: Path) -> dict[str, list[tuple]]:
    """What the index answers about the project: runs, statuses, parameters, metrics."""
    with Catalog(project, read_only=True) as catalog:
        return {
            query: sorted(tuple(row) for row in catalog.backend.fetch_all(query))
            for query in (_RUN_STATE_SQL, _PARAMETER_STATE_SQL, _METRIC_STATE_SQL)
        }


def _files_outside_internal(project: Path) -> dict[str, str]:
    """Relative path -> sha256 of every file outside the project ``.hmp/``."""
    return {
        path.relative_to(project).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(project.rglob("*"))
        if path.is_file() and path.relative_to(project).parts[0] != INTERNAL_DIRNAME
    }


@pytest.fixture
def project(tmp_path):
    """A project with two sealed runs, one of them versioned."""
    root = tmp_path / "demo"
    root.mkdir()
    (root / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    with Catalog(root) as catalog:
        _seal_run(catalog, "nancon_monthly", nse=0.71, k=1e-5)
        _seal_run(catalog, "nancon_monthly", nse=0.64, k=2e-5)
    return root


def test_deleting_the_internal_directory_loses_nothing(project):
    state = _index_state(project)
    files = _files_outside_internal(project)
    assert len(state[_RUN_STATE_SQL]) == 2

    shutil.rmtree(internal_dir(project))
    rebuild_index(project)

    assert catalog_path_for(project).is_file()
    assert _index_state(project) == state
    assert _files_outside_internal(project) == files


def test_the_rebuilt_index_names_each_run_by_its_directory(project):
    shutil.rmtree(internal_dir(project))

    rebuild_index(project)

    with Catalog(project, read_only=True) as catalog:
        names = sorted(row[0] for row in catalog.backend.fetch_all(_RUN_STATE_SQL))
    assert names == ["nancon_monthly", "nancon_monthly.v2"]
