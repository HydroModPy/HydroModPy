"""The run record writes the seal without the index, in order, and reads it back."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime

import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

from hydromodpy.results.identity import read_identity_from
from hydromodpy.results.record import record as record_module
from hydromodpy.results.record.manifest import (
    RUN_RECORD_MANIFEST_VERSION,
    ManifestGeometry,
    ManifestRun,
    RunSeal,
    read_manifest,
    read_seal,
)
from hydromodpy.results.record.record import PROVENANCE_VERSION, RunRecord, sealed_artifacts
from hydromodpy.results.storage.contract import (
    RUN_INPUTS_FILENAME,
    RUN_MANIFEST_FILENAME,
    RUN_PROVENANCE_FILENAME,
    TABLES_DIRNAME,
)
from hydromodpy.results.storage.parquet_schemas import (
    CHECK_COLUMNS,
    PARAMETERS_SCHEMA,
    SIMULATION_SCHEMA,
)
from tests._helpers.run_records import SIM_ID, make_identity, make_record


@pytest.fixture
def run_dir(tmp_path):
    directory = tmp_path / "runs" / "J0014010-base.v2"
    directory.mkdir(parents=True)
    (directory / "config.toml").write_text("[flow]\n", encoding="utf-8")
    (directory / "outcome.json").write_text("{}", encoding="utf-8")
    (directory / "logs").mkdir()
    (directory / "logs" / "run.2.log").write_text("solved\n", encoding="utf-8")
    (directory / "figures").mkdir()
    (directory / "figures" / "heads.png").write_bytes(b"png")
    return directory


def test_a_record_round_trips_through_the_run_directory(run_dir):
    record = make_record()
    record.write(run_dir)

    assert RunRecord.read(run_dir) == record


def test_the_seal_files_land_where_the_contract_says(run_dir):
    make_record().write(run_dir)

    assert (run_dir / RUN_MANIFEST_FILENAME).is_file()
    assert (run_dir / RUN_PROVENANCE_FILENAME).is_file()
    assert (run_dir / RUN_INPUTS_FILENAME).is_file()
    assert (run_dir / TABLES_DIRNAME / "simulation.parquet").is_file()
    assert (run_dir / TABLES_DIRNAME / "parameters.parquet").is_file()
    assert not list(run_dir.glob("*.tmp-*"))


def test_the_manifest_is_written_last_and_a_crash_before_leaves_none(run_dir, monkeypatch):
    def refuse(target, seal):
        raise OSError("disk full")

    monkeypatch.setattr(record_module, "write_seal", refuse)

    with pytest.raises(OSError, match="disk full"):
        make_record().write(run_dir)

    assert not (run_dir / RUN_MANIFEST_FILENAME).exists()
    assert (run_dir / RUN_PROVENANCE_FILENAME).is_file()
    assert (run_dir / RUN_INPUTS_FILENAME).is_file()
    assert (run_dir / TABLES_DIRNAME / "simulation.parquet").is_file()


def test_the_manifest_is_flushed_to_the_disk(run_dir, monkeypatch):
    synced: list[int] = []
    real_fsync = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(fd), real_fsync(fd)))

    make_record().write(run_dir)

    # The staged manifest and its directory, at least.
    assert len(synced) >= 2


def test_the_manifest_is_version_four_and_typed(run_dir):
    make_record().write(run_dir)

    payload = read_manifest(run_dir)
    manifest = RunSeal.model_validate(payload)
    assert payload["manifest_version"] == RUN_RECORD_MANIFEST_VERSION == 4
    assert manifest.profile == "run"
    assert manifest.values is None
    assert manifest.site is not None and manifest.site.name == "J0014010"
    assert manifest.lineage.kind == "promoted"
    assert manifest.identity.sim_id == SIM_ID
    assert manifest.identity.label is None
    assert manifest.checks.calibrated_by is not None
    assert manifest.score is not None and manifest.score.n_samples == 1827
    assert [p.origin for p in manifest.parameters] == ["calibrated", "declared"]


def test_the_seal_inventories_the_raw_result_only(run_dir):
    make_record().write(run_dir)

    paths = {entry.path for entry in RunSeal.model_validate(read_manifest(run_dir)).artifacts}
    assert paths == {
        "manifest.json",
        "config.toml",
        "inputs.json",
        "provenance.json",
        "tables.parquet/parameters.parquet",
        "tables.parquet/simulation.parquet",
    }
    assert not any(p.startswith(("figures", "logs", "outcome")) for p in paths)


def test_sealed_artifacts_skip_every_unsealed_entry(run_dir):
    for name in ("README.md", "published.jsonl"):
        (run_dir / name).write_text("x", encoding="utf-8")
    for name in ("exports", "report", "attempts"):
        (run_dir / name).mkdir()
        (run_dir / name / "f").write_text("x", encoding="utf-8")

    paths = {entry.path for entry in sealed_artifacts(run_dir)}
    assert paths == {"manifest.json", "config.toml"}


def test_simulation_parquet_has_the_declared_columns_and_one_row(run_dir):
    record = make_record()
    record.write(run_dir)

    table = pq.read_table(run_dir / TABLES_DIRNAME / "simulation.parquet")
    assert table.num_rows == 1
    assert table.schema.names == SIMULATION_SCHEMA.names
    row = table.to_pylist()[0]
    assert row["site"] == "J0014010"
    assert row["case_id"] == "J0014010-base"
    assert row["rel_dir"] == "runs/J0014010-base.v2"
    assert row["attempt"] == 2
    assert row["nse"] == 0.81
    assert row["n_samples"] == 1827
    assert row["metric_rule_version"] == "1"
    assert str(row["score_window_start"]) == "2016-01-01"
    assert (row["calibrated_by_trial"], row["calibrated_by_metric"]) == (7, "nse")
    assert row["calibrated_by_cost"] == 0.84
    assert row["fatal_failed"] is False
    assert "label" not in row


def test_the_checks_land_flat_under_their_declared_columns():
    flat = make_record().checks.flatten()
    assert tuple(flat) == CHECK_COLUMNS
    assert set(CHECK_COLUMNS) <= set(SIMULATION_SCHEMA.names)


def test_parameters_parquet_carries_origin_and_calibrated(run_dir):
    make_record().write(run_dir)

    table = pq.read_table(run_dir / TABLES_DIRNAME / "parameters.parquet")
    assert table.schema.names == PARAMETERS_SCHEMA.names
    rows = {row["param_name"]: row for row in table.to_pylist()}
    assert rows["K"]["origin"] == "calibrated" and rows["K"]["calibrated"] is True
    assert rows["Sy"]["origin"] == "declared" and rows["Sy"]["calibrated"] is False


def test_a_run_without_parameters_writes_no_parameter_table(run_dir):
    make_record(parameters=[]).write(run_dir)
    assert not (run_dir / TABLES_DIRNAME / "parameters.parquet").exists()


def test_both_tables_carry_the_identity_block(run_dir):
    record = make_record()
    record.write(run_dir)

    for name in ("simulation.parquet", "parameters.parquet"):
        assert read_identity_from(run_dir / TABLES_DIRNAME / name) == record.identity


def test_provenance_keeps_host_and_user_in_the_tree_and_gains_environment(run_dir):
    make_record().write(run_dir)

    payload = json.loads((run_dir / RUN_PROVENANCE_FILENAME).read_text(encoding="utf-8"))
    assert payload["platform"]["hostname"] == "node12"
    assert payload["environment"]["binaries"]["mf6"] == "ef" * 32
    assert payload["provenance_version"] == PROVENANCE_VERSION == 2


def test_inputs_json_lists_every_loaded_input(run_dir):
    make_record().write(run_dir)

    payload = json.loads((run_dir / RUN_INPUTS_FILENAME).read_text(encoding="utf-8"))
    assert payload["schema"] == "hydromodpy.inputs.v1"
    assert payload["inputs"][0]["provider"] == "hubeau"
    assert payload["inputs"][0]["license"] == "etalab-2.0"


def test_a_seal_never_carries_a_label():
    with pytest.raises(ValidationError, match="carries no label"):
        make_record(identity=make_identity(label="calibrated", label_date="2026-10-15"))


def test_an_identity_naming_another_run_is_refused():
    with pytest.raises(ValidationError, match="identity names sim"):
        make_record(identity=make_identity(sim_id="other"))


def test_a_naive_instant_is_refused():
    record = make_record()
    run = record.run.model_copy(update={"created_at": datetime(2026, 1, 1)})
    with pytest.raises(ValidationError, match="naive instant"):
        make_record(run=run)


def test_an_unknown_key_is_refused_by_name():
    with pytest.raises(ValidationError, match="label"):
        RunRecord.model_validate({**make_record().model_dump(), "label": "calibrated"})


def test_the_headline_score_is_the_nse():
    record = make_record()
    other = record.score.model_copy(update={"metric": "kge"})
    with pytest.raises(ValidationError, match="headline score is the NSE"):
        make_record(score=other)


@pytest.mark.parametrize("status", ["failed", "aborted", "running"])
def test_only_a_completed_run_has_a_record(status):
    run = make_record().run.model_dump()
    with pytest.raises(ValidationError, match="never manifest.json"):
        make_record(run=ManifestRun.model_validate({**run, "status": status}))


def test_the_status_column_allows_completed_only():
    field = SIMULATION_SCHEMA.field("status")
    assert field.metadata[b"allowed"] == b"completed"


def test_the_site_fingerprint_is_the_only_fingerprint():
    assert "geographic_fingerprint" not in SIMULATION_SCHEMA.names
    assert "geographic_fingerprint" not in ManifestGeometry.model_fields
    assert "geographic_fingerprint" not in make_record().simulation_row()


def test_the_cost_of_the_case_rides_with_the_session_that_promoted_the_run(run_dir):
    make_record().write(run_dir)

    row = pq.read_table(run_dir / TABLES_DIRNAME / "simulation.parquet").to_pylist()[0]
    assert (row["calibrated_by_metric"], row["calibrated_by_cost"]) == ("nse", 0.84)
    by = RunRecord.read(run_dir).checks.calibrated_by
    assert by is not None and (by.metric, by.cost) == ("nse", 0.84)


@pytest.mark.parametrize(
    "column",
    ["nse_window_start", "nse_window_end", "nse_n", "nse_station", "nse_variable"]
    + ["objective_name", "objective_value", "objective_window_start", "objective_window_end"],
)
def test_the_simulation_table_keeps_no_column_of_a_retired_name(column):
    assert column not in SIMULATION_SCHEMA.names


@pytest.mark.parametrize("rel_dir", ["/abs/runs/x", "runs/../x", "outputs/x", "runs/x/y"])
def test_a_run_rel_dir_follows_the_one_grammar(rel_dir):
    run = make_record().run.model_dump()
    with pytest.raises(ValidationError, match="not a result directory"):
        ManifestRun.model_validate({**run, "rel_dir": rel_dir})


def test_a_sealed_file_carries_its_digest_and_a_change_is_reported(run_dir):
    from hydromodpy.results.record.manifest import seal_problems

    record = make_record()
    record.write(run_dir)
    by_path = {entry.path: entry for entry in sealed_artifacts(run_dir)}
    assert by_path["config.toml"].sha256 is not None
    assert by_path["manifest.json"].sha256 is None
    assert seal_problems(run_dir) == []

    (run_dir / "config.toml").write_text("changed", encoding="utf-8")
    assert any("config.toml" in problem for problem in seal_problems(run_dir))


def _field_store(run_dir):
    """Write a small field store with one array, and return a chunk file of it."""
    import numpy as np

    from hydromodpy.results.zarr_store import SimulationZarr

    store = SimulationZarr.create(run_dir / "fields.zarr", n_cells=4, n_layers=1)
    store.write_static_field("hydraulic_conductivity", np.full((1, 4), 1.0e-5), subgroup="derived")
    store.close()
    return next(
        path
        for path in sorted((run_dir / "fields.zarr").rglob("*"))
        if path.is_file() and path.suffix != ".json"
    )


def test_the_field_store_carries_the_digest_of_its_tree_and_a_rewritten_chunk_is_reported(
    run_dir,
):
    from hydromodpy.results.record.manifest import seal_problems
    from hydromodpy.results.storage.digests import sha256_directory

    chunk = _field_store(run_dir)
    make_record().write(run_dir)
    by_path = {entry.path: entry for entry in read_seal(run_dir).artifacts}
    assert by_path["fields.zarr"].sha256 == sha256_directory(run_dir / "fields.zarr")
    assert seal_problems(run_dir) == []

    # The same size with other bytes: a value changed in an array of fixed shape.
    data = chunk.read_bytes()
    chunk.write_bytes(bytes([data[0] ^ 0xFF]) + data[1:])
    assert seal_problems(run_dir) == ["fields.zarr does not hash to what the seal recorded"]

    shutil.rmtree(run_dir / "fields.zarr")
    assert seal_problems(run_dir) == ["fields.zarr is sealed and absent"]


def test_reading_the_field_store_of_a_sealed_run_leaves_its_seal_whole(run_dir):
    from hydromodpy.results.record.manifest import seal_problems
    from hydromodpy.results.zarr_store import SimulationZarr

    _field_store(run_dir)
    make_record().write(run_dir)

    store = SimulationZarr(run_dir / "fields.zarr")
    store.read_field("hydraulic_conductivity", 0, subgroup="derived")
    store.close()

    assert seal_problems(run_dir) == []


def test_a_seal_without_the_digest_of_the_field_store_still_reads(run_dir):
    from hydromodpy.results.record.manifest import seal_problems

    chunk = _field_store(run_dir)
    make_record().write(run_dir)
    payload = json.loads((run_dir / RUN_MANIFEST_FILENAME).read_text(encoding="utf-8"))
    for artifact in payload["artifacts"]:
        if artifact["path"] == "fields.zarr":
            artifact["sha256"] = None
    (run_dir / RUN_MANIFEST_FILENAME).write_text(json.dumps(payload), encoding="utf-8")
    chunk.write_bytes(b"other")

    by_path = {entry.path: entry for entry in read_seal(run_dir).artifacts}
    assert by_path["fields.zarr"].sha256 is None
    assert seal_problems(run_dir) == []


def test_the_certified_entries_close_the_inventory_of_a_run():
    from hydromodpy.results.storage.contract import (
        ALLOWED_RUN_ENTRIES,
        CERTIFIED_RUN_ENTRIES,
        MESH_DIRNAME,
        UNSEALED_RUN_ENTRIES,
    )

    named = CERTIFIED_RUN_ENTRIES | UNSEALED_RUN_ENTRIES | {RUN_MANIFEST_FILENAME}
    assert named == ALLOWED_RUN_ENTRIES
    assert not CERTIFIED_RUN_ENTRIES & UNSEALED_RUN_ENTRIES
    assert MESH_DIRNAME in CERTIFIED_RUN_ENTRIES


def test_an_unknown_entry_stays_inventoried_under_other(run_dir):
    (run_dir / "stray.bin").write_bytes(b"x")
    make_record().write(run_dir)

    entry = {item.path: item for item in sealed_artifacts(run_dir)}["stray.bin"]
    assert entry.role == "other"
    assert entry.sha256 is not None


def test_the_simulation_table_keeps_no_config_hash(run_dir):
    make_record().write(run_dir)

    assert "config_hash" not in SIMULATION_SCHEMA.names
    row = pq.read_table(run_dir / TABLES_DIRNAME / "simulation.parquet").to_pylist()[0]
    assert "config_hash" not in row


def test_the_values_handed_to_the_write_are_the_values_of_the_seal(run_dir):
    from hydromodpy.schema.seal import ValueDigests

    values = ValueDigests(digests={"fields/h": "ab" * 32})
    make_record().write(run_dir, values=values)

    assert read_seal(run_dir).values == values


def test_the_footer_carries_the_identity_without_a_config_hash(run_dir):
    make_record().write(run_dir)

    schema = pq.read_schema(run_dir / TABLES_DIRNAME / "simulation.parquet")
    block = json.loads(schema.metadata[b"hmp.identity"])
    assert "config_hash" not in block
    assert "hash" not in block
