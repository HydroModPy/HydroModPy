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

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import zarr

from hydromodpy.core.budget_terms import BudgetKeep
from hydromodpy.core.state.paths import INTERNAL_DIRNAME
from hydromodpy.results.identity import ZARR_IDENTITY_ATTR, read_identity_from
from hydromodpy.results.manifest import (
    InputEntry,
    Manifest,
    MetricRow,
    list_artifacts,
    read_manifest,
)
from hydromodpy.results.outcome import effective_status, read_outcome
from hydromodpy.results.record import RunRecord
from hydromodpy.results.storage import sealing
from hydromodpy.results.storage.attempt import close_sealed_attempt
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    README_FILENAME,
    RUN_CONFIG_FILENAME,
    RUN_FIGURES_DIRNAME,
    RUN_INPUTS_FILENAME,
    RUN_MANIFEST_FILENAME,
    RUN_PROVENANCE_FILENAME,
    RUN_SCRATCH_ENTRIES,
    TABLES_DIRNAME,
)
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed, sealed_config_hash
from tests._helpers.run_stores import open_run_store

CATCHMENT = {
    "catch_area": 29.7,
    "x_outlet": 301.5,
    "y_outlet": 402.5,
    "dem_res": 5.0,
    "nrow": 120,
    "ncol": 240,
    "crs_proj": "EPSG:2154",
    "epsg": 2154,
    "catch_def": "from_outlet_coord",
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
        config_hash="c0ffee" * 10 + "c0ff",
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


def test_the_seal_writes_the_record_and_the_readme_and_leaves_the_outcome(
    filled: RunStore,
) -> None:
    run_dir = filled.run_dir

    record = seal_completed(filled)

    assert (run_dir / RUN_MANIFEST_FILENAME).is_file()
    assert (run_dir / RUN_PROVENANCE_FILENAME).is_file()
    assert (run_dir / RUN_INPUTS_FILENAME).is_file()
    assert (run_dir / README_FILENAME).is_file()
    assert (run_dir / TABLES_DIRNAME / f"simulation{PARQUET_FILE_SUFFIX}").is_file()
    assert (run_dir / TABLES_DIRNAME / f"parameters{PARQUET_FILE_SUFFIX}").is_file()
    # The seal is a step: the outcome and the attempt state are the bracket's.
    assert read_outcome(run_dir).status == "running"
    assert (run_dir / INTERNAL_DIRNAME).is_dir()
    assert effective_status(run_dir) == "completed", "the manifest wins over the outcome"
    assert RunRecord.read(run_dir) == record


def test_closing_the_sealed_attempt_flips_the_outcome_and_drops_the_state(
    filled: RunStore,
) -> None:
    run_dir = filled.run_dir
    seal_completed(filled)

    outcome = close_sealed_attempt(run_dir)

    assert outcome.status == "completed" and outcome.exit_code == 0
    assert read_outcome(run_dir).status == "completed"
    assert not (run_dir / INTERNAL_DIRNAME).exists(), "the attempt state is consumed by the seal"
    assert effective_status(run_dir) == "completed"


def test_an_unsealed_attempt_is_never_closed_as_completed(filled: RunStore) -> None:
    with pytest.raises(FileNotFoundError, match=RUN_MANIFEST_FILENAME):
        close_sealed_attempt(filled.run_dir)
    assert read_outcome(filled.run_dir).status == "running"
    assert (filled.run_dir / INTERNAL_DIRNAME).is_dir()


def test_the_manifest_carries_the_facts_of_the_run(filled: RunStore) -> None:
    record = seal_completed(filled)
    manifest = Manifest.model_validate(read_manifest(filled.run_dir))

    assert manifest.run.sim_id == filled.sim_id
    assert manifest.run.name == "cheze_baseline"
    assert manifest.run.case_id == "cheze_baseline"
    assert manifest.run.rel_dir == "runs/cheze_baseline"
    assert manifest.run.status == "completed"
    assert manifest.geometry.n_cells == 4
    assert manifest.geometry.mesh_hash == "mesh01"
    assert manifest.config.file == RUN_CONFIG_FILENAME
    assert manifest.config.hash == "c0ffee" * 10 + "c0ff"
    assert manifest.identity.config_hash == manifest.config.hash
    assert manifest.identity.label is None
    assert [p.name for p in manifest.parameters] == ["K"]
    assert [(m.station, m.metric, m.value) for m in manifest.metrics] == [("P01", "nse", 0.8)]
    assert manifest.checks.budget_pct == 5.0
    assert record.provenance.sim_id == filled.sim_id
    assert sealed_config_hash(filled.run_dir) == manifest.config.hash


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
    assert catchment["catch_def"] == "from_outlet_coord"


def test_the_inputs_the_run_loaded_are_sealed_with_their_provider_and_licence(
    filled: RunStore,
) -> None:
    record = seal_completed(filled)

    assert record.inputs == [DEM_INPUT]
    again = RunRecord.read(filled.run_dir)
    assert again.inputs == [DEM_INPUT]
    sealed = again.inputs[0]
    assert sealed.provider == "ign_geoplateforme_dem"
    assert sealed.sha256 == "ab" * 32
    assert sealed.license == "etalab-2.0"
    assert sealed.path == "data/dem/dem_abcd.tif"


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


def test_the_field_store_carries_the_identity_and_the_acdd_attributes(filled: RunStore) -> None:
    seal_completed(filled)

    root = zarr.open_group(str(filled.fields_path), mode="r")
    attrs = dict(root.attrs)
    assert attrs[ZARR_IDENTITY_ATTR]["sim_id"] == filled.sim_id
    assert attrs["id"] == filled.sim_id
    assert attrs["title"] == "cheze_baseline"
    assert "license" in attrs
    identity = read_identity_from(filled.fields_path)
    assert identity is not None and identity.case_id == "cheze_baseline"


def test_the_readme_summarises_the_run_and_signs_the_manifest(filled: RunStore) -> None:
    from hydromodpy.results.ledger import sha256_of

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


def test_a_sealed_run_is_read_back_as_a_record(filled: RunStore) -> None:
    record = seal_completed(filled)
    again = RunRecord.read(filled.run_dir)
    assert again.run == record.run
    assert again.identity == record.identity
    assert again.parameters == record.parameters


def test_an_unreadable_manifest_hashes_to_nothing(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "broken"
    run_dir.mkdir(parents=True)
    (run_dir / RUN_MANIFEST_FILENAME).write_text("{not json", encoding="utf-8")

    assert sealed_config_hash(run_dir) is None


# -- the inventory -------------------------------------------------------------


def test_the_field_store_is_weighed_like_any_other_artefact(filled: RunStore) -> None:
    """``fields.zarr`` is a directory; the manifest must still say what it weighs."""
    seal_completed(filled)
    run_dir = filled.run_dir
    entry = next(e for e in read_manifest(run_dir)["artifacts"] if e["role"] == "fields")

    on_disk = sum(p.stat().st_size for p in (run_dir / FIELDS_STORE_NAME).rglob("*") if p.is_file())
    assert on_disk > 0
    assert entry["bytes"] == on_disk


def test_the_inventory_accounts_for_the_whole_sealed_result(filled: RunStore) -> None:
    """Every byte of the result is inventoried, bar the unsized manifest and the unsealed entries."""
    from hydromodpy.results.storage.contract import UNSEALED_RUN_ENTRIES

    seal_completed(filled)
    run_dir = filled.run_dir
    manifest = read_manifest(run_dir)
    inventoried = sum(entry.get("bytes") or 0 for entry in manifest["artifacts"])

    excluded = set(UNSEALED_RUN_ENTRIES) | set(RUN_SCRATCH_ENTRIES) | {RUN_MANIFEST_FILENAME}
    on_disk = sum(
        p.stat().st_size
        for p in run_dir.rglob("*")
        if p.is_file() and p.relative_to(run_dir).parts[0] not in excluded
    )
    assert inventoried == on_disk


def test_the_lock_directory_is_not_an_artefact_of_the_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r"
    (run_dir / INTERNAL_DIRNAME / "locks").mkdir(parents=True)
    (run_dir / INTERNAL_DIRNAME / "locks" / "fields.zarr.lock").write_text("")
    (run_dir / RUN_CONFIG_FILENAME).write_text("[flow]\n")

    paths = {entry["path"] for entry in list_artifacts(run_dir)}

    assert INTERNAL_DIRNAME in RUN_SCRATCH_ENTRIES
    assert paths == {RUN_MANIFEST_FILENAME, RUN_CONFIG_FILENAME}


def test_an_unexpected_directory_is_inventoried_rather_than_dropped(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r"
    (run_dir / "mystery").mkdir(parents=True)
    (run_dir / "mystery" / "file.bin").write_bytes(b"xyz")

    entries = {entry["path"]: entry for entry in list_artifacts(run_dir)}

    assert entries["mystery"]["role"] == "other"
    assert entries["mystery"]["format"] == "directory"
    assert entries["mystery"]["bytes"] == 3


def test_figures_are_inventoried_but_never_sealed(tmp_path: Path) -> None:
    from hydromodpy.results.record import sealed_artifacts

    run_dir = tmp_path / "runs" / "r"
    (run_dir / RUN_FIGURES_DIRNAME).mkdir(parents=True)
    (run_dir / RUN_FIGURES_DIRNAME / "heads.png").write_bytes(b"png")
    (run_dir / FIELDS_STORE_NAME).mkdir()

    inventory = {entry["path"] for entry in list_artifacts(run_dir)}
    sealed = {entry.path for entry in sealed_artifacts(run_dir)}

    assert f"{RUN_FIGURES_DIRNAME}/heads.png" in inventory
    assert f"{RUN_FIGURES_DIRNAME}/heads.png" not in sealed
    assert FIELDS_STORE_NAME in sealed
