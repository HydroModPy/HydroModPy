"""The seal of a completed run: from the store of the run, manifest last, index never.

A completed run writes its record from the facts its store accumulated and
its README from the record and the label of the day. The attempt protocol
then flips its outcome to ``completed`` and drops ``<run>/.hmp/``
(:func:`close_sealed_attempt`), once nothing writes there any more. The
inventory of the manifest names the raw result only; the field store carries
the identity and the ACDD attributes; the whole thing is read back by
``RunRecord.read``.
"""

from __future__ import annotations

import errno
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.state.layout import INTERNAL_DIRNAME
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.record.manifest import InputEntry, MetricRow, read_manifest
from hydromodpy.results.record.record import RunRecord
from hydromodpy.results.storage import sealing
from hydromodpy.results.storage.attempt import close_sealed_attempt
from hydromodpy.results.storage.contract import (
    README_FILENAME,
    RUN_CONFIG_FILENAME,
    RUN_MANIFEST_FILENAME,
)
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store

SOLUTION_KEY = "c0ffee" * 10 + "c0ff"

CATCHMENT = {
    "catch_area": 29.7,
    "x_outlet": 301.5,
    "y_outlet": 402.5,
    "dem_res": 5.0,
    "nrow": 120,
    "ncol": 240,
    "crs_proj": "EPSG:2154",
    "epsg": 2154,
    "kind": "from_outlet_coord",
}

DEM_INPUT = InputEntry(
    variable="dem:dem",
    provider="ign_geoplateforme_dem",
    request={"bbox": [10.0, 20.0, 110.0, 220.0]},
    fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
    path="data/dem/dem_abcd.tif",
    sha256="ab" * 32,
    bytes=4096,
    license="etalab-2.0",
)


@pytest.fixture
def filled(tmp_path: Path) -> RunStore:
    """A run store with a field, tables, parameters, a metric, an input and a frozen config."""
    store = open_run_store(
        tmp_path / "demo",
        "cheze_baseline",
        n_cells=4,
        n_layers=1,
        n_timesteps=3,
        crs_wkt="EPSG:2154",
        crs_epsg=2154,
        bbox=(10.0, 20.0, 110.0, 220.0),
        solution_key=SOLUTION_KEY,
    )
    sid = store.sim_id
    (store.run_dir / RUN_CONFIG_FILENAME).write_text("[flow]\nhk = 1e-5\n", encoding="utf-8")
    store.write_parameters(sid, [{"param_name": "K", "value": 1e-5, "unit": "m/s"}])
    index = pd.date_range("2020-01-01", periods=3, freq="D")
    store.write_timeseries(sid, "P01", "head", pd.Series(np.ones(3), index=index))
    store.write_budget(sid, 0, "z1", "recharge", 10.0, 0.0)
    store.write_field_stack(sid, "recharge", np.ones((3, 1, 4)), subgroup="budget")
    sz = store.open_zarr(sid)
    try:
        sz.write_budget_policy(BudgetKeep.everything(), ["recharge"])
    finally:
        sz.close()
    store.write_mass_balance(sid, 0, 10.0, 9.5, 5.0)
    store.write_metric(sid, MetricRow(station="P01", metric="nse", value=0.8))
    store.write_provenance(sid, "dem", "ign_geoplateforme_dem", np.ones(4))
    store.record_input(sid, DEM_INPUT)
    store.write_geographic_metadata(sid, CATCHMENT)
    store.update_simulation_grid_metadata(sid, mesh_hash="mesh01", mesh_topology="structured_2d")
    return store


def test_an_unsealed_attempt_is_never_closed_as_completed(filled: RunStore) -> None:
    with pytest.raises(FileNotFoundError, match=RUN_MANIFEST_FILENAME):
        close_sealed_attempt(filled.run_dir)
    assert read_outcome(filled.run_dir).status == "running"
    assert (filled.run_dir / INTERNAL_DIRNAME).is_dir()


def test_the_manifest_keeps_the_catchment_area_the_outlet_and_the_grid(filled: RunStore) -> None:
    """Losing these turns a derived discharge into a silently wrong series."""
    seal_completed(filled)
    catchment = read_manifest(filled.run_dir)["geometry"]["catchment"]

    assert catchment["catch_area"] == pytest.approx(29.7)
    assert catchment["x_outlet"] == pytest.approx(301.5)
    assert catchment["y_outlet"] == pytest.approx(402.5)
    assert catchment["dem_res"] == pytest.approx(5.0)
    assert (catchment["nrow"], catchment["ncol"]) == (120, 240)
    assert catchment["crs_proj"] == "EPSG:2154"
    assert catchment["kind"] == "from_outlet_coord"


# -- kept budget ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("keep", "written", "expected"),
    [
        (BudgetKeep.everything(), ["storage_sy", "recharge"], ["recharge", "storage_sy"]),
        (BudgetKeep.of_terms({"recharge", "lake"}), ["recharge"], ["lake", "recharge"]),
        (BudgetKeep.of_terms(()), [], []),
    ],
    ids=["all", "consumers", "lumped"],
)
def test_the_manifest_repeats_what_the_store_kept_of_the_budget(
    tmp_path: Path, keep, written, expected
) -> None:
    store = open_run_store(tmp_path / "demo", "budget", n_cells=4, n_layers=1)
    sz = store.open_zarr(store.sim_id)
    try:
        sz.write_budget_policy(keep, written)
    finally:
        sz.close()

    seal_completed(store)

    manifest = read_manifest(store.run_dir)
    assert manifest["budget"] == {"policy": keep.policy, "kept_terms": expected}


def test_a_store_without_budget_attributes_writes_no_budget_block(tmp_path: Path) -> None:
    store = open_run_store(tmp_path / "demo", "no_budget", n_cells=4, n_layers=1)

    seal_completed(store)

    assert read_manifest(store.run_dir).get("budget") is None


# -- the field store -----------------------------------------------------------


def test_the_readme_summarises_the_run_and_signs_the_manifest(filled: RunStore) -> None:
    from hydromodpy.core.io.file_digest import sha256_of

    seal_completed(filled)

    text = (filled.run_dir / README_FILENAME).read_text(encoding="utf-8")
    assert text.startswith("# cheze_baseline")
    assert "status **completed**" in text
    assert f"sha256({RUN_MANIFEST_FILENAME}) = " in text
    assert text.rstrip().endswith(sha256_of(filled.run_dir / RUN_MANIFEST_FILENAME))


def test_a_run_without_a_solver_cannot_seal(tmp_path: Path) -> None:
    store = open_run_store(tmp_path / "demo", solver=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="solver"):
        seal_completed(store)


def test_a_failing_seal_leaves_no_manifest(filled: RunStore, monkeypatch) -> None:
    def refuse(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(sealing, "write_readme", refuse)
    with pytest.raises(OSError, match="disk full"):
        seal_completed(filled)
    # The manifest landed before the README; the outcome never flipped.
    assert (filled.run_dir / RUN_MANIFEST_FILENAME).is_file()
    assert read_outcome(filled.run_dir).status == "running"


# -- the inventory -------------------------------------------------------------


# -- the values and the mesh ---------------------------------------------------


def _cited_mesh(store: RunStore, key: str = "a" * 64) -> Path:
    """Put a two-file mesh product in the store and cite it from the run."""
    from hydromodpy.mesh.stored import ARRAYS_FILENAME, DESCRIPTION_FILENAME
    from hydromodpy.results.products.cited import CitedProduct, write_cited
    from hydromodpy.results.products.store import ProductStore, products_root

    def write(product: Path) -> None:
        (product / DESCRIPTION_FILENAME).write_text("{}\n", encoding="utf-8")
        (product / ARRAYS_FILENAME).write_bytes(b"npz")

    workspace = store.workspace_path
    assert workspace is not None
    product = ProductStore(products_root(workspace)).put(key, "mesh", write)
    write_cited(store.run_dir, [CitedProduct(kind="mesh", key=key)])
    return product


LINK_REFUSALS = [
    pytest.param(OSError(errno.EXDEV, "cross-device link"), id="EXDEV"),
    pytest.param(PermissionError(1, "not permitted"), id="PermissionError (Windows)"),
    pytest.param(OSError(errno.ENOTSUP, "not supported"), id="ENOTSUP"),
]


def test_a_cited_mesh_the_store_no_longer_holds_leaves_the_run_sealed(filled: RunStore) -> None:
    from hydromodpy.results.products.cited import CitedProduct, write_cited
    from hydromodpy.results.storage.contract import MESH_DIRNAME

    write_cited(filled.run_dir, [CitedProduct(kind="mesh", key="b" * 64)])

    seal_completed(filled)

    assert (filled.run_dir / RUN_MANIFEST_FILENAME).is_file()
    assert not (filled.run_dir / MESH_DIRNAME).exists()
    assert all(item.variable != MESH_DIRNAME for item in RunRecord.read(filled.run_dir).inputs)


def test_a_replay_that_read_the_sealed_mesh_seals_it_from_its_source(
    filled: RunStore, tmp_path: Path
) -> None:
    from datetime import UTC, datetime

    from hydromodpy.mesh.stored import ARRAYS_FILENAME, DESCRIPTION_FILENAME
    from hydromodpy.results.products.cited import CitedProduct, write_cited
    from hydromodpy.results.storage.contract import MESH_DIRNAME
    from hydromodpy.results.storage.run_profile import Profile, ProfileLine, write_profile

    source = tmp_path / "source"
    (source / MESH_DIRNAME).mkdir(parents=True)
    (source / MESH_DIRNAME / DESCRIPTION_FILENAME).write_text("{}\n", encoding="utf-8")
    (source / MESH_DIRNAME / ARRAYS_FILENAME).write_bytes(b"sealed npz")
    # The key the replay cites is gone from the store: only the source holds the bytes.
    write_cited(filled.run_dir, [CitedProduct(kind="mesh", key="c" * 64)])
    line = ProfileLine(
        kind="step",
        name="mesh",
        attempt=1,
        started_at=datetime.now(UTC),
        duration_s=0.1,
        reused="sealed",
    )
    write_profile(filled.run_dir, Profile(lines=(line,)))

    sealing._seal_mesh(filled, source)

    copied = filled.run_dir / MESH_DIRNAME / ARRAYS_FILENAME
    assert copied.read_bytes() == b"sealed npz"
    assert any(item.variable == MESH_DIRNAME for item in filled.facts.inputs)
