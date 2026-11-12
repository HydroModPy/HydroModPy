"""The input files a run tracks reach its seal and the index, one row each."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.fixtures_catalog import simulation_catalog
from tests._helpers.run_stores import open_run_store


@dataclass
class _Entry:
    role: str
    category: str
    original_path: str
    canonical_path: Path
    portable: bool = True


def _track(project: Path, *batches: list[_Entry]) -> tuple[list[int], str]:
    """Record each batch on one run, seal it; return the counts and the run id."""
    store = open_run_store(project, "run", solver="modflow_nwt", create_zarr=False)
    sim_id = store.sim_id
    counts = [store.register_tracked_files(sim_id, batch) for batch in batches]
    seal_completed(store)
    return counts, sim_id


def _listed(project: Path, sim_id: str) -> pd.DataFrame:
    with simulation_catalog(project) as catalog:
        return catalog.list_tracked_files(sim_id)


def test_register_tracked_files_writes_directory_rows(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    src = ws / "hydrometry"
    src.mkdir()
    (src / "hydrometry_custom_LOC.csv").write_text("id,x,y\nA,0,0\n")
    (src / "hydrometry_custom_A_20200101_20200101_D.csv").write_text(
        "datetime,value\n2020-01-01,1.0\n"
    )
    entry = _Entry(
        role="hydrometry",
        category="data",
        original_path="hydrometry",
        canonical_path=src.resolve(),
    )

    (n,), sid = _track(ws, [entry])
    df = _listed(ws, sid)

    assert n == 1
    assert len(df) == 1
    row = df.iloc[0]
    assert row["role"] == "hydrometry"
    assert row["size_bytes"] > 0
    assert isinstance(row["sha256"], str) and len(row["sha256"]) == 64


def test_register_tracked_files_is_idempotent(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    src = ws / "dem.tif"
    src.write_bytes(b"x")
    entry = _Entry(
        role="dem", category="data", original_path="dem.tif", canonical_path=src.resolve()
    )

    _, sid = _track(ws, [entry], [entry])

    assert len(_listed(ws, sid)) == 1


def test_register_tracked_files_skips_missing(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    entry = _Entry(
        role="dem",
        category="data",
        original_path="missing.tif",
        canonical_path=ws / "does-not-exist.tif",
    )

    (n,), sid = _track(ws, [entry])

    assert n == 0
    assert _listed(ws, sid).empty
