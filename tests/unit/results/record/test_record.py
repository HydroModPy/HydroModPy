"""The run record writes the seal without the index, in order, and reads it back.

A record is validated when built: it carries no label, names its own run, holds aware instants
and a headline NSE score, and exists for a completed run only.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from hydromodpy.results.record.manifest import ManifestRun
from hydromodpy.results.storage.contract import (
    ALLOWED_RUN_ENTRIES,
    CERTIFIED_RUN_ENTRIES,
    MESH_DIRNAME,
    RUN_MANIFEST_FILENAME,
    UNSEALED_RUN_ENTRIES,
)
from hydromodpy.results.storage.parquet_schemas import SIMULATION_SCHEMA
from tests._helpers.run_records import make_identity, make_record

BASE = make_record()

# (overrides of make_record, the part of the message that names the fix)
REFUSALS = [
    pytest.param(
        {"identity": make_identity(label="calibrated", label_date="2026-10-15")},
        "carries no label",
        id="a label in the seal",
    ),
    pytest.param(
        {"identity": make_identity(sim_id="other")},
        "identity names sim",
        id="identity of another run",
    ),
    pytest.param(
        {"run": BASE.run.model_copy(update={"created_at": datetime(2026, 1, 1)})},
        "naive instant",
        id="naive instant",
    ),
    pytest.param(
        {"score": BASE.score.model_copy(update={"metric": "kge"})},
        "headline score is the NSE",
        id="headline score not the nse",
    ),
]

RETIRED_COLUMNS = [
    "nse_window_start",
    "nse_window_end",
    "nse_n",
    "nse_station",
    "nse_variable",
    "objective_name",
    "objective_value",
    "objective_window_start",
    "objective_window_end",
]


@pytest.mark.parametrize(("overrides", "message"), REFUSALS)
def test_refusals(overrides, message):
    with pytest.raises(ValidationError, match=message):
        make_record(**overrides)


@pytest.mark.parametrize("status", ["failed", "aborted", "running"])
def test_only_a_completed_run_has_a_record(status):
    with pytest.raises(ValidationError, match="never manifest.json"):
        ManifestRun.model_validate({**BASE.run.model_dump(), "status": status})


def test_the_status_column_allows_completed_only():
    field = SIMULATION_SCHEMA.field("status")
    assert field.metadata[b"allowed"] == b"completed"


@pytest.mark.parametrize("column", RETIRED_COLUMNS)
def test_the_simulation_table_keeps_no_column_of_a_retired_name(column):
    assert column not in SIMULATION_SCHEMA.names


def test_the_certified_entries_close_the_inventory_of_a_run():
    named = CERTIFIED_RUN_ENTRIES | UNSEALED_RUN_ENTRIES | {RUN_MANIFEST_FILENAME}
    assert named == ALLOWED_RUN_ENTRIES
    assert not CERTIFIED_RUN_ENTRIES & UNSEALED_RUN_ENTRIES
    assert MESH_DIRNAME in CERTIFIED_RUN_ENTRIES
