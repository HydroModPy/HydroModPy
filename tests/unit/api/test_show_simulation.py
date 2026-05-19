"""Tests for :func:`hydromodpy.show_simulation`."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

import hydromodpy as hmp


def _seed_project(tmp_path: Path) -> tuple[Path, str]:
    project_dir = tmp_path / "ws" / "projects" / "demo"
    project_dir.mkdir(parents=True)
    (project_dir / "simulations").mkdir()
    sim_id = str(uuid4())
    with hmp.open(project_dir) as catalog:
        catalog.register_simulation(
            sim_id=sim_id,
            project="demo",
            solver="modflow_nwt",
            name="baseline",
            flow_regime="steady",
            n_cells=4,
            n_layers=1,
        )
        catalog.finalize(sim_id, status="completed", duration_s=0.5)
    return project_dir, sim_id


def test_show_simulation_returns_metadata(tmp_path: Path) -> None:
    project_dir, sim_id = _seed_project(tmp_path)
    payload = hmp.show_simulation(sim_id, workspace=project_dir)
    assert payload["sim_id"] == sim_id
    assert payload["name"] == "baseline"
    assert payload["solver"] == "modflow_nwt"
    assert payload["status"] == "completed"


def test_show_simulation_detail_adds_zarr_info(tmp_path: Path) -> None:
    project_dir, sim_id = _seed_project(tmp_path)
    payload = hmp.show_simulation(sim_id, workspace=project_dir, detail=True)
    assert "zarr_path" in payload
    assert "zarr_exists" in payload
    assert "zarr_groups" in payload


def test_show_simulation_missing_catalog_raises(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        hmp.show_simulation("deadbeef", workspace=empty)
