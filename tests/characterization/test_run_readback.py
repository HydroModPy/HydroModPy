"""What a finished run offers a reader today, and must keep offering tomorrow.

These are the green half of the tier: they pin behaviour that already works and
that no redesign is allowed to lose. They read the run directory the way an
outsider would, through the file formats, never through a HydroModPy object.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
import zarr

from hydromodpy.core.state.paths import INTERNAL_DIRNAME
from hydromodpy.results.manifest import RUN_MANIFEST_FILENAME
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    RUN_ANNOTATIONS_FILENAME,
    RUN_CONFIG_FILENAME,
    RUN_FIGURES_DIRNAME,
    RUN_PROVENANCE_FILENAME,
    RUN_TRASH_FILENAME,
    TABLES_DIRNAME,
)
from tests.characterization.conftest import ProducedRun

ALLOWED_RUN_ENTRIES = frozenset(
    {
        FIELDS_STORE_NAME,
        TABLES_DIRNAME,
        RUN_CONFIG_FILENAME,
        RUN_PROVENANCE_FILENAME,
        RUN_MANIFEST_FILENAME,
        RUN_ANNOTATIONS_FILENAME,
        RUN_TRASH_FILENAME,
        RUN_FIGURES_DIRNAME,
    }
)


def test_the_run_directory_holds_only_declared_entries(produced_run: ProducedRun) -> None:
    """A run leaves behind the contract's names, plus the lock directory."""
    entries = {path.name for path in produced_run.run_dir.iterdir()}
    assert FIELDS_STORE_NAME in entries
    assert TABLES_DIRNAME in entries
    undeclared = entries - ALLOWED_RUN_ENTRIES
    # A real run also leaves `.hmp/locks/`, which the storage contract does not
    # name. `tests/unit/results/test_run_layout_contract.py` never sees it
    # because its fixture writes the run directory by hand; bounding it here
    # keeps the gap visible instead of filtering hidden names away.
    assert undeclared <= {INTERNAL_DIRNAME}, f"undeclared entries: {sorted(undeclared)}"


def test_the_field_store_opens_with_the_zarr_package(produced_run: ProducedRun) -> None:
    """The head field is readable, finite and shaped (time, layer, cell)."""
    group = zarr.open_group(str(produced_run.field_store), mode="r")
    head = group["head"][...]
    assert head.ndim == 3, f"head is {head.shape}, expected (time, layer, cell)"
    assert head.shape[0] >= 1
    finite = head[np.isfinite(head)]
    assert finite.size > 0, "head holds no finite value"
    assert float(finite.min()) > -1e6


def test_the_field_store_declares_its_conventions(produced_run: ProducedRun) -> None:
    """The store carries the attribute block a metadata reader looks for."""
    attrs = dict(zarr.open_group(str(produced_run.field_store), mode="r").attrs)
    for key in ("Conventions", "title", "summary", "source", "history", "license", "creator_name"):
        assert key in attrs, f"root attribute {key} absent from the field store"


def test_the_tables_open_with_pandas(produced_run: ProducedRun) -> None:
    """Every tabular payload is a readable Parquet file with rows in it."""
    payloads = sorted(produced_run.tables.glob("*.parquet"))
    assert payloads, "no Parquet payload in the run"
    names = {path.name for path in payloads}
    assert {"simulation.parquet", "budgets.parquet", "mass_balance.parquet"} <= names
    for path in payloads:
        frame = pd.read_parquet(path)
        assert not frame.empty, f"{path.name} holds no row"


def test_the_manifest_seals_the_run(produced_run: ProducedRun) -> None:
    """The seal names the solver, the regime and the mesh a reader will find."""
    manifest = json.loads(produced_run.manifest.read_text(encoding="utf-8"))
    assert manifest["run"]["status"] == "completed"
    assert manifest["run"]["solver"] == "modflow_nwt"
    assert manifest["run"]["flow_regime"] == "steady"
    assert manifest["geometry"]["n_cells"] > 0
    assert manifest["geometry"]["n_layers"] >= 1
    assert manifest["artifacts"], "the seal lists no artefact"


def test_the_manifest_cell_count_matches_the_field_store(produced_run: ProducedRun) -> None:
    """The declared geometry and the stored arrays describe the same mesh."""
    manifest = json.loads(produced_run.manifest.read_text(encoding="utf-8"))
    head = zarr.open_group(str(produced_run.field_store), mode="r")["head"][...]
    assert head.shape[-1] == manifest["geometry"]["n_cells"]
    assert head.shape[-2] == manifest["geometry"]["n_layers"]


@pytest.mark.parametrize("payload", ["config.toml", "provenance.json", "manifest.json"])
def test_the_run_is_self_describing_without_the_index(
    produced_run: ProducedRun, payload: str
) -> None:
    """A reader who never opens the DuckDB index still finds the run's story."""
    path = produced_run.run_dir / payload
    assert path.is_file(), f"{payload} absent from the run directory"
    assert path.stat().st_size > 0
