from __future__ import annotations

import uuid
from pathlib import Path

from hydromodpy.results.catalog import CatalogIndex, SimulationCatalog


def _seed_project(project_root: Path, *, project: str, k_value: float) -> str:
    project_root.mkdir(parents=True, exist_ok=True)
    catalog = SimulationCatalog(project_root)
    try:
        sim_id = str(uuid.uuid4())
        reg = catalog.register_simulation(
            sim_id,
            project=project,
            solver="modflow6",
            name=f"{project}_run",
            n_cells=1,
            n_layers=1,
        )
        if reg.zarr is not None:
            reg.zarr.close()
        catalog.write_parameters(
            sim_id,
            [{"param_name": "K", "value": k_value, "unit": "m/s"}],
        )
        catalog.finalize(sim_id, "completed")
        return sim_id
    finally:
        catalog.close()


def test_catalog_index_queries_parameters_across_projects(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    p1 = workspace / "projects" / "a"
    p2 = workspace / "projects" / "b"
    sid_a = _seed_project(p1, project="a", k_value=1e-5)
    sid_b = _seed_project(p2, project="b", k_value=2e-5)

    with CatalogIndex(tmp_path / "index.duckdb") as index:
        assert index.register_workspace(workspace) == 2
        df = index.query(
            """
            SELECT project_slug, sim_id, param_name, value
            FROM all_parameters
            WHERE param_name = 'K'
            ORDER BY project_slug
            """
        )

    assert df["project_slug"].tolist() == ["a", "b"]
    assert df["sim_id"].astype(str).tolist() == [sid_a, sid_b]
    assert df["value"].tolist() == [1e-5, 2e-5]
