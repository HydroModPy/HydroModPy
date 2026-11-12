"""The run record writes the seal without the index, in order, and reads it back."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from hydromodpy.results.record.manifest import ManifestRun
from hydromodpy.results.storage.contract import RUN_MANIFEST_FILENAME
from hydromodpy.results.storage.parquet_schemas import SIMULATION_SCHEMA
from tests._helpers.run_records import make_identity, make_record


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


@pytest.mark.parametrize(
    "column",
    ["nse_window_start", "nse_window_end", "nse_n", "nse_station", "nse_variable"]
    + ["objective_name", "objective_value", "objective_window_start", "objective_window_end"],
)
def test_the_simulation_table_keeps_no_column_of_a_retired_name(column):
    assert column not in SIMULATION_SCHEMA.names


def _field_store(run_dir):
    """Write a small field store with one array, and return a chunk file of it."""
    import numpy as np

    from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr

    store = SimulationZarr.create(run_dir / "fields.zarr", n_cells=4, n_layers=1)
    store.write_static_field("hydraulic_conductivity", np.full((1, 4), 1.0e-5), subgroup="derived")
    store.close()
    return next(
        path
        for path in sorted((run_dir / "fields.zarr").rglob("*"))
        if path.is_file() and path.suffix != ".json"
    )


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
