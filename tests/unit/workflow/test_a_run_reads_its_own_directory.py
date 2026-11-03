"""A run read by its steps reads its own directory, never the index.

The display and export steps open a :class:`Run` on the store of the run in
flight. Its rows (series, observations, budget), its periods and its status
come from the run directory, with ``Catalog.__init__`` patched to raise. Once
sealed, a table written after the seal carries the licence of the seal, the
annotations of the run land in ``annotations.json``, and the run is deleted
by a move to the trash.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.manifest import read_manifest
from hydromodpy.results.run import Run
from hydromodpy.results.storage.attempt import close_sealed_attempt
from hydromodpy.results.storage.parquet_io import read_kv_metadata
from hydromodpy.results.storage.run_facts import LicenceSource
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.results.trash import list_trash
from tests._helpers.run_stores import open_run_store

STAMPS = pd.to_datetime(["2000-02-01", "2000-03-01", "2000-04-01"])


@pytest.fixture
def no_index(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args, **_kwargs):
        raise AssertionError("a run step opened the index")

    monkeypatch.setattr(Catalog, "__init__", refuse)


def _monthly_store(project: Path) -> RunStore:
    store = open_run_store(
        project,
        "monthly",
        n_timesteps=3,
        period_start=datetime(2000, 1, 1, tzinfo=UTC),
        period_end=datetime(2000, 4, 1, tzinfo=UTC),
        time_unit="month",
    )
    sid = store.sim_id
    store.write_time(sid, STAMPS.values.astype("datetime64[s]").astype("int64"))
    store.write_timeseries(sid, "J0014010", "discharge", pd.Series([1.0, 2.0, 3.0], index=STAMPS))
    store.write_timeseries(
        sid, "J0014010", "discharge", pd.Series([1.5, 2.5], index=STAMPS[:2]), source="observed"
    )
    store.write_budgets(
        sid,
        [
            {"timestep": t, "zone_id": "catchment", "component": "drain", "flux_out": 1.0 + t}
            for t in range(3)
        ],
    )
    return store


def test_a_running_run_reads_its_rows_from_its_directory(tmp_path: Path, no_index) -> None:
    with _monthly_store(tmp_path / "p") as store:
        run = Run(store.sim_id, store)

        assert run.status == "running"
        assert run.n_timesteps == 3
        assert run.stations("discharge") == ["J0014010"]
        assert run.timeseries("discharge").tolist() == [1.0, 2.0, 3.0]
        assert run.timeseries("discharge", period=("2000-02-15", "2000-04-30")).tolist() == [
            2.0,
            3.0,
        ]
        assert run.observed("discharge")["value"].tolist() == [1.5, 2.5]
        assert run.budget(component="drain")["flux_out"].tolist() == [1.0, 2.0, 3.0]
        assert run.has_table("budgets") and not run.has_table("mass_balance")
        assert list(run.periods.edges) == list(
            pd.to_datetime(["2000-01-01", "2000-02-01", "2000-03-01", "2000-04-01"])
        )
        assert run.periods.step_at("2000-02-15") == 1


def test_a_table_written_after_the_seal_keeps_the_licence_of_the_seal(tmp_path: Path) -> None:
    store = _monthly_store(tmp_path / "p")
    store.facts.licence_sources.append(LicenceSource(source="hubeau"))
    run_dir = store.run_dir
    seal_completed(store)
    close_sealed_attempt(run_dir)
    sealed_licence = read_manifest(run_dir)["run"]["license"]

    with RunStore.open(run_dir) as reopened:
        reopened.write_view(
            reopened.sim_id,
            "observation_points",
            [{"station_id": "p1", "x": 0.0, "y": 0.0, "cell_id": 0, "layer": 0}],
        )
        footer = read_kv_metadata(reopened.table_path_for(reopened.sim_id, "observation_points"))

    assert sealed_licence not in (None, "", "LicenseRef-undetermined")
    assert footer["license"] == sealed_licence


def test_tags_notes_and_delete_are_written_in_the_run_directory(tmp_path: Path) -> None:
    project = tmp_path / "p"
    store = _monthly_store(project)
    run_dir, sid = store.run_dir, store.sim_id
    seal_completed(store)
    close_sealed_attempt(run_dir)

    with RunStore.open(run_dir) as sealed:
        run = Run(sid, sealed)
        run.tag("keep", "+pinned", "-keep")
        run.note("best fit")

        payload = json.loads((run_dir / "annotations.json").read_text(encoding="utf-8"))
        assert payload["sim_id"] == sid
        assert payload["tags"] == ["pinned"]
        assert [note["note"] for note in payload["notes"]] == ["best fit"]
        assert run.tags == ["pinned"]

    with RunStore.open(run_dir) as sealed:
        run = Run(sid, sealed)
        run.tag("-pinned")
        run.delete()

    assert not run_dir.exists()
    assert [entry.rel_dir for entry in list_trash(project)] == ["runs/monthly"]


def test_a_long_vector_layer_name_lists_back_whole(tmp_path: Path, no_index) -> None:
    """The listing reads the name from the file name: it is not cut to 32 characters."""
    import geopandas as gpd
    from shapely.geometry import LineString

    name = "hydrographic_network_reference_permanent"
    layer = gpd.GeoDataFrame(geometry=[LineString([(0.0, 0.0), (1.0, 0.0)])], crs="EPSG:2154")
    with open_run_store(tmp_path / "p", "layers") as store:
        store.write_geographic_feature(store.sim_id, name, layer)

        assert store.list_geographic_features(store.sim_id) == [name]
        assert len(Run(store.sim_id, store).hydrographic_network("reference_permanent")) == 1
