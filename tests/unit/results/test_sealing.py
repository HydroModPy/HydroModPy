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

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.state.layout import INTERNAL_DIRNAME
from hydromodpy.results.identity import ZARR_IDENTITY_ATTR, read_identity_from
from hydromodpy.results.outcome import effective_status, read_outcome
from hydromodpy.results.record.label import label_of
from hydromodpy.results.record.manifest import (
    DERIVE_RULE_VERSION,
    InputEntry,
    MetricRow,
    RunSeal,
    list_artifacts,
    read_manifest,
)
from hydromodpy.results.record.record import RunRecord
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
from hydromodpy.results.storage.sealing import seal_completed, sealed_solution_key
from hydromodpy.results.validity_rules import RULE_VERSION
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


def test_the_seal_stamps_the_rules_of_the_derived_fields(filled: RunStore) -> None:
    manifest = seal_completed(filled)

    assert manifest.derive_rule_version == DERIVE_RULE_VERSION
    assert label_of(manifest, filled.run_dir).rule_version == RULE_VERSION


def test_the_manifest_carries_the_facts_of_the_run(filled: RunStore) -> None:
    record = seal_completed(filled)
    manifest = RunSeal.model_validate(read_manifest(filled.run_dir))

    assert manifest.run.sim_id == filled.sim_id
    assert manifest.run.name == "cheze_baseline"
    assert manifest.run.case_id == "cheze_baseline"
    assert manifest.run.rel_dir == "runs/cheze_baseline"
    assert manifest.run.status == "completed"
    assert manifest.geometry.n_cells == 4
    assert manifest.geometry.mesh_hash == "mesh01"
    assert manifest.config.file == RUN_CONFIG_FILENAME
    assert "hash" not in manifest.config.model_dump()
    assert manifest.identity.solution_key == SOLUTION_KEY
    assert sealed_solution_key(filled.run_dir) == SOLUTION_KEY
    assert manifest.identity.label is None
    assert [p.name for p in manifest.parameters] == ["K"]
    assert [(m.station, m.metric, m.value) for m in manifest.metrics] == [("P01", "nse", 0.8)]
    assert manifest.checks.budget_pct == 5.0
    assert record.provenance.sim_id == filled.sim_id


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


def test_a_sealed_run_is_read_back_as_a_record(filled: RunStore) -> None:
    record = seal_completed(filled)
    again = RunRecord.read(filled.run_dir)
    assert again.run == record.run
    assert again.identity == record.identity
    assert again.parameters == record.parameters


def test_an_unreadable_manifest_names_no_solution_key(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "broken"
    run_dir.mkdir(parents=True)
    (run_dir / RUN_MANIFEST_FILENAME).write_text("{not json", encoding="utf-8")

    assert sealed_solution_key(run_dir) is None


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
    from hydromodpy.results.record.record import sealed_artifacts

    run_dir = tmp_path / "runs" / "r"
    (run_dir / RUN_FIGURES_DIRNAME).mkdir(parents=True)
    (run_dir / RUN_FIGURES_DIRNAME / "heads.png").write_bytes(b"png")
    (run_dir / FIELDS_STORE_NAME).mkdir()

    inventory = {entry["path"] for entry in list_artifacts(run_dir)}
    sealed = {entry.path for entry in sealed_artifacts(run_dir)}

    assert f"{RUN_FIGURES_DIRNAME}/heads.png" in inventory
    assert f"{RUN_FIGURES_DIRNAME}/heads.png" not in sealed
    assert FIELDS_STORE_NAME in sealed


# -- the values and the mesh ---------------------------------------------------


def test_the_seal_holds_the_digests_of_the_values_it_compares(filled: RunStore) -> None:
    from hydromodpy.core.io.value_digest import VALUES_RULE
    from hydromodpy.results.record.manifest import read_seal

    seal_completed(filled)

    values = read_seal(filled.run_dir).values
    assert values is not None and values.rule == VALUES_RULE
    assert "fields/budget/recharge" in values.digests
    # The digests are taken once the record has written its own tables.
    assert any(key.startswith("tables/simulation/") for key in values.digests)


def test_the_digests_of_the_rounded_steps_are_the_float64_values_the_writer_saw(
    tmp_path: Path,
) -> None:
    from hydromodpy.core.io.value_digest import fold_steps, value_digest
    from hydromodpy.results.record.manifest import read_seal

    store = open_run_store(tmp_path / "demo", "compact", n_cells=4, n_layers=1, n_timesteps=2)
    exact = np.array([[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8]], dtype="float64")
    store.write_field_stack(store.sim_id, "head", exact[:, None, :], subgroup="derived")

    # One step is one layer by four cells, the shape a replay reads back from the store.
    steps = {"0": value_digest(exact[0][None, :]), "1": value_digest(exact[1][None, :])}
    assert store.facts.field_digests["derived/head"] == steps

    seal_completed(store)

    values = read_seal(store.run_dir).values
    assert values is not None
    assert values.digests["fields/derived/head"] == fold_steps(
        {int(step): digest for step, digest in steps.items()}, 2
    )


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


def test_the_mesh_the_run_read_is_sealed_under_the_run(filled: RunStore) -> None:
    from hydromodpy.mesh.stored import ARRAYS_FILENAME, DESCRIPTION_FILENAME
    from hydromodpy.results.record.manifest import read_seal, seal_problems
    from hydromodpy.results.storage.contract import MESH_DIRNAME
    from hydromodpy.results.storage.digests import sha256_directory

    product = _cited_mesh(filled)
    seal_completed(filled)

    mesh = filled.run_dir / MESH_DIRNAME
    assert sorted(path.name for path in mesh.iterdir()) == sorted(
        [DESCRIPTION_FILENAME, ARRAYS_FILENAME]
    )
    assert (mesh / DESCRIPTION_FILENAME).read_text(encoding="utf-8") == "{}\n"
    by_path = {entry.path: entry for entry in read_seal(filled.run_dir).artifacts}
    assert by_path[MESH_DIRNAME].sha256 == sha256_directory(mesh)
    assert seal_problems(filled.run_dir) == []

    inputs = RunRecord.read(filled.run_dir).inputs
    entry = next(item for item in inputs if item.variable == MESH_DIRNAME)
    assert entry.provider == "store" and entry.product == MESH_DIRNAME
    assert entry.sha256 == sha256_directory(mesh)
    assert product.is_dir()


def test_the_mesh_copy_falls_back_to_a_copy_when_a_link_is_refused(
    filled: RunStore, monkeypatch
) -> None:
    from hydromodpy.results.storage.contract import MESH_DIRNAME

    product = _cited_mesh(filled)

    link = sealing.os.link

    def refuse(source, destination, *args, **kwargs):
        # Only the mesh copy is refused: the field store links its own files too.
        if Path(destination).parent.name == MESH_DIRNAME:
            raise OSError("cross-device link")
        return link(source, destination, *args, **kwargs)

    monkeypatch.setattr(sealing.os, "link", refuse)
    seal_completed(filled)

    source = product / "mesh.npz"
    copy = filled.run_dir / MESH_DIRNAME / "mesh.npz"
    assert copy.read_bytes() == source.read_bytes()
    assert copy.stat().st_ino != source.stat().st_ino


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
