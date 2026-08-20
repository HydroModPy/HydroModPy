"""Tests for ``hmp catalog point``: read one cell of a finished run."""

from __future__ import annotations

import importlib
import json
import sys
import uuid
from pathlib import Path

import numpy as np
import pytest

VERTICES = np.array(
    [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [0.0, 1.0], [1.0, 1.0], [2.0, 1.0]],
    dtype="float64",
)
CONNECTIVITY = np.array([[0, 1, 4, 3], [1, 2, 5, 4]], dtype="int32")
N_CELLS = 2
N_STEPS = 2


def _run_cli(monkeypatch, argv: list[str]) -> int:
    module = importlib.import_module("hydromodpy.cli.main")
    monkeypatch.setattr(sys, "argv", argv)
    try:
        module.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _seal(catalog, name: str, *, offset: float = 0.0) -> str:
    sid = str(uuid.uuid4())
    registration = catalog.register_simulation(
        sid,
        project="demo",
        solver="modflow6",
        name=name,
        flow_regime="transient",
        n_cells=N_CELLS,
        n_layers=1,
        n_timesteps=N_STEPS,
        bbox=[0.0, 0.0, 2.0, 1.0],
        crs="EPSG:2154",
        config={"flow": {"hk": 1e-5}},
    )
    if registration.zarr is not None:
        registration.zarr.close()
    store_zarr = catalog.open_zarr(sid)
    try:
        store_zarr.write_mesh(
            VERTICES,
            CONNECTIVITY,
            np.array([10.0, 0.0]),
            topography=np.full(N_CELLS, 10.0),
        )
    finally:
        store_zarr.close()
    for step in range(N_STEPS):
        values = np.array([[1.0 + step + offset, 2.0 + step + offset]], dtype="float64")
        catalog.write_field(sid, "head", step, values, n_timesteps=N_STEPS if step == 0 else None)
    catalog.finalize(sid, status="completed", duration_s=1.0)
    return sid


@pytest.fixture
def project(tmp_path) -> Path:
    from hydromodpy.results.catalog import Catalog

    root = tmp_path / "demo"
    (root).mkdir(parents=True)
    (root / "project.toml").write_text("[workspace]\nproject_root = '.'\n")
    with Catalog(root) as catalog:
        _seal(catalog, "base")
        _seal(catalog, "scenario", offset=10.0)
    return root


def test_coordinates_read_the_containing_cell(monkeypatch, project, capsys) -> None:
    code = _run_cli(
        monkeypatch,
        [
            "hmp",
            "catalog",
            "point",
            "@last",
            "--var",
            "head",
            "--xy",
            "1.5",
            "0.5",
            "--workspace",
            str(project),
        ],
    )
    assert code == 0
    assert "head" in capsys.readouterr().out


def test_a_cell_index_reads_the_same_values(monkeypatch, project, capsys) -> None:
    code = _run_cli(
        monkeypatch,
        [
            "hmp",
            "catalog",
            "point",
            "base",
            "--var",
            "head",
            "--cell",
            "1",
            "--format",
            "json",
            "--workspace",
            str(project),
        ],
    )
    assert code == 0
    rows = json.loads(capsys.readouterr().out)
    assert [row["value"] for row in rows] == [2.0, 3.0]


def test_several_runs_stack_their_answers(monkeypatch, project, capsys) -> None:
    code = _run_cli(
        monkeypatch,
        [
            "hmp",
            "catalog",
            "point",
            "base",
            "scenario",
            "--var",
            "head",
            "--cell",
            "0",
            "--timestep",
            "-1",
            "--format",
            "json",
            "--workspace",
            str(project),
        ],
    )
    assert code == 0
    rows = json.loads(capsys.readouterr().out)
    assert {row["run"]: row["value"] for row in rows} == {"base": 2.0, "scenario": 12.0}


def test_the_table_is_written_to_csv(monkeypatch, project, tmp_path, capsys) -> None:
    import pandas as pd

    dest = tmp_path / "probe.csv"
    code = _run_cli(
        monkeypatch,
        [
            "hmp",
            "catalog",
            "point",
            "base",
            "--var",
            "head",
            "--cell",
            "1",
            "-o",
            str(dest),
            "--workspace",
            str(project),
        ],
    )
    assert code == 0
    assert pd.read_csv(dest)["value"].tolist() == [2.0, 3.0]


def test_a_point_outside_the_mesh_exits_non_zero(monkeypatch, project, capsys) -> None:
    code = _run_cli(
        monkeypatch,
        [
            "hmp",
            "catalog",
            "point",
            "base",
            "--var",
            "head",
            "--xy",
            "99",
            "99",
            "--workspace",
            str(project),
        ],
    )
    assert code != 0
    assert "outside the mesh" in capsys.readouterr().err


def test_an_unknown_field_exits_non_zero(monkeypatch, project, capsys) -> None:
    code = _run_cli(
        monkeypatch,
        [
            "hmp",
            "catalog",
            "point",
            "base",
            "--var",
            "nosuchfield",
            "--cell",
            "0",
            "--workspace",
            str(project),
        ],
    )
    assert code != 0


def test_coordinates_and_cell_are_mutually_exclusive(monkeypatch, project) -> None:
    code = _run_cli(
        monkeypatch,
        [
            "hmp",
            "catalog",
            "point",
            "base",
            "--var",
            "head",
            "--cell",
            "0",
            "--xy",
            "1.5",
            "0.5",
            "--workspace",
            str(project),
        ],
    )
    assert code == 2


def test_a_location_is_required(monkeypatch, project) -> None:
    code = _run_cli(
        monkeypatch,
        ["hmp", "catalog", "point", "base", "--var", "head", "--workspace", str(project)],
    )
    assert code == 2


def test_the_action_is_listed_in_the_family_help(monkeypatch, capsys) -> None:
    code = _run_cli(monkeypatch, ["hmp", "catalog", "--help"])
    assert code == 0
    assert "point" in capsys.readouterr().out
