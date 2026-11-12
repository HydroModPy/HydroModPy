"""``hmp show --point`` reads one cell of a finished run: a value of a field (head, in m) per time step.

The test project holds two runs on a mesh of two square cells, 1 m wide, side by side
(x from 0 to 2, y from 0 to 1) and two time steps. Head is 1 and 2 m at step 0, then 2 and 3 m.
The ``scenario`` run is 10 m higher.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store

from ._hmp import run_main as _run

VERTICES = np.array(
    [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [0.0, 1.0], [1.0, 1.0], [2.0, 1.0]],
    dtype="float64",
)
CONNECTIVITY = np.array([[0, 1, 4, 3], [1, 2, 5, 4]], dtype="int32")
N_CELLS = 2
N_STEPS = 2

# (words after "show base --point", message in stderr)
REFUSED = [
    pytest.param(["--var", "head", "--xy", "99", "99"], "outside the mesh", id="outside the mesh"),
    pytest.param(["--var", "nosuchfield", "--cell", "0"], "", id="unknown field"),
]


def seal_two_cell_run(project: Path, name: str, *, offset: float = 0.0) -> None:
    """Write a two-cell head run under ``runs/<name>`` and seal it."""
    store = open_run_store(
        project,
        name,
        n_cells=N_CELLS,
        n_layers=1,
        n_timesteps=N_STEPS,
        flow_regime="transient",
        bbox=(0.0, 0.0, 2.0, 1.0),
        crs_wkt="EPSG:2154",
        crs_epsg=2154,
    )
    sid = store.sim_id
    (store.run_dir / RUN_CONFIG_FILENAME).write_text("[flow]\nhk = 1e-5\n", encoding="utf-8")
    store_zarr = store.open_zarr(sid)
    try:
        store_zarr.write_mesh(
            VERTICES, CONNECTIVITY, np.array([10.0, 0.0]), topography=np.full(N_CELLS, 10.0)
        )
    finally:
        store_zarr.close()
    for step in range(N_STEPS):
        values = np.array([[1.0 + step + offset, 2.0 + step + offset]], dtype="float64")
        store.write_field(sid, "head", step, values, n_timesteps=N_STEPS if step == 0 else None)
    seal_completed(store)


@pytest.fixture
def project(tmp_path) -> Path:
    root = tmp_path / "demo"
    seal_two_cell_run(root, "base")
    seal_two_cell_run(root, "scenario", offset=10.0)
    rebuild_index(root)
    return root


def test_coordinates_read_the_containing_cell(monkeypatch, project, capsys) -> None:
    argv = ["hmp", "show", "@last", "--point", "--var", "head", "--xy", "1.5", "0.5"]

    assert _run(monkeypatch, [*argv, "--workspace", str(project)]) == 0
    assert "head" in capsys.readouterr().out


def test_several_runs_stack_their_answers(monkeypatch, project, capsys) -> None:
    argv = ["hmp", "show", "base", "scenario", "--point", "--var", "head", "--cell", "0"]

    code = _run(
        monkeypatch,
        [*argv, "--timestep", "-1", "--format", "json", "--workspace", str(project)],
    )

    assert code == 0
    rows = json.loads(capsys.readouterr().out)["data"]
    assert {row["run"]: row["value"] for row in rows} == {"base": 2.0, "scenario": 12.0}


def test_the_table_is_written_to_csv(monkeypatch, project, tmp_path) -> None:
    dest = tmp_path / "probe.csv"
    argv = ["hmp", "show", "base", "--point", "--var", "head", "--cell", "1", "--to", str(dest)]

    assert _run(monkeypatch, [*argv, "--workspace", str(project)]) == 0
    assert pd.read_csv(dest)["value"].tolist() == [2.0, 3.0]


@pytest.mark.parametrize(("words", "message"), REFUSED)
def test_a_point_that_cannot_be_read_exits_non_zero(
    monkeypatch, project, capsys, words, message
) -> None:
    argv = ["hmp", "show", "base", "--point", *words, "--workspace", str(project)]

    assert _run(monkeypatch, argv) != 0
    assert message in capsys.readouterr().err


def test_a_location_is_required(monkeypatch, project) -> None:
    argv = ["hmp", "show", "base", "--point", "--var", "head", "--workspace", str(project)]

    assert _run(monkeypatch, argv) == 2
