"""A run whose snap is on stores its snapped maps; one whose snap is off stores none.

``[geographic.snap_streams]`` in ``diagnose`` or ``apply`` moves the mapped
network onto the talwegs. The moved map and its displacement are kept with the
run as geographic features, one per map: the maximal map always, the minimal
map when the run carries its permanent reaches.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString

import hydromodpy.results.derive.snapped_network as snapped_network
from hydromodpy.core.state.paths import PROJECT_MARKER_FILENAME, RUNS_DIRNAME
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.derive.snapped_network import (
    SNAPPED_NETWORK_COLUMNS,
    SNAPPED_NETWORK_FEATURES,
    persist_snapped_networks,
    snapped_mask_from_frame,
    stored_snapped_network,
    write_snapped_network,
)
from hydromodpy.results.derive.stream_network import network_comparison_from_run
from hydromodpy.results.run import Run
from hydromodpy.results.storage.contract import PARQUET_FILE_SUFFIX, TABLES_DIRNAME
from tests.unit.display._network_comparison_run import (
    AXIS_COLUMN,
    CELL_M,
    NY,
    cell,
    column_cells,
    comparison_run,
)

SHIFTED_COLUMN = AXIS_COLUMN + 1
RUN_NAME = "snapped_baseline"


def _line(column: int, run: SimpleNamespace) -> gpd.GeoDataFrame:
    x = (column + 0.5) * CELL_M
    return gpd.GeoDataFrame(
        geometry=[LineString([(x, 0.1 * CELL_M), (x, (NY - 0.1) * CELL_M)])], crs=run.mesh.crs
    )


def shifted_run(
    mode: str | None, *, with_minimal: bool = False, with_release: bool = True
) -> SimpleNamespace:
    """A run whose mapped network, and permanent reaches, lie one column off the talweg."""
    run = comparison_run(
        seepage_cells=[cell(AXIS_COLUMN, row) for row in range(NY)], with_release=with_release
    )
    networks = {"reference": _line(SHIFTED_COLUMN, run)}
    if with_minimal:
        networks["reference_permanent"] = _line(SHIFTED_COLUMN, run)
    run.has_hydrographic_network = lambda role="generated": role in networks
    run.hydrographic_network = lambda role="generated": networks[role]
    run.config_snapshot = None if mode is None else {"geographic": {"snap_streams": {"mode": mode}}}
    return run


class _Store:
    """Keeps what the run writes, by feature name."""

    def __init__(self) -> None:
        self.written: dict[str, gpd.GeoDataFrame] = {}

    def write_geographic_feature(self, sim_id: str, name: str, frame: gpd.GeoDataFrame) -> None:
        self.written[name] = frame


class _Warnings:
    """Records the warnings the module logs."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def warning(self, message: str, *args: object) -> None:
        self.messages.append(message % args)

    def debug(self, *_args: object) -> None:
        return None


@pytest.mark.parametrize("mode", [None, "off"])
def test_a_run_whose_snap_is_off_stores_nothing(mode: str | None) -> None:
    store = _Store()

    assert persist_snapped_networks(shifted_run(mode), store) == ()
    assert store.written == {}


@pytest.mark.parametrize("mode", ["diagnose", "apply"])
def test_a_run_whose_snap_is_on_stores_its_snapped_map(mode: str) -> None:
    store = _Store()

    assert persist_snapped_networks(shifted_run(mode), store) == ("maximal",)

    frame = store.written[SNAPPED_NETWORK_FEATURES["maximal"]]
    assert set(SNAPPED_NETWORK_COLUMNS) <= set(frame.columns)
    assert set(frame["status"]) == {"moved"}
    assert np.allclose(frame["displacement_m"], CELL_M)
    moved_onto = sorted(int(i) for i in np.flatnonzero(snapped_mask_from_frame(frame, 15)))
    assert moved_onto == column_cells(AXIS_COLUMN)
    assert SNAPPED_NETWORK_FEATURES["minimal"] not in store.written


def test_a_run_with_its_permanent_reaches_stores_both_maps() -> None:
    store = _Store()

    assert persist_snapped_networks(shifted_run("apply", with_minimal=True), store) == (
        "maximal",
        "minimal",
    )
    minimal = store.written[SNAPPED_NETWORK_FEATURES["minimal"]]
    assert sorted(int(i) for i in np.flatnonzero(snapped_mask_from_frame(minimal, 15))) == (
        column_cells(AXIS_COLUMN)
    )


def test_the_stored_map_is_the_map_the_redraw_scores() -> None:
    run = shifted_run("apply")
    store = _Store()
    persist_snapped_networks(run, store)

    snap = network_comparison_from_run(run).geometry.snap
    frame = store.written[SNAPPED_NETWORK_FEATURES["maximal"]]
    assert np.array_equal(snapped_mask_from_frame(frame, snap.raw.size), snap.snapped)


def test_a_run_that_cannot_be_redrawn_says_why_and_stores_nothing(monkeypatch) -> None:
    warnings = _Warnings()
    monkeypatch.setattr(snapped_network, "logger", warnings)
    store = _Store()

    assert persist_snapped_networks(shifted_run("apply", with_release=False), store) == ()
    assert store.written == {}
    assert len(warnings.messages) == 1
    assert "snapped maximal map is not stored" in warnings.messages[0]
    assert "release_flux" in warnings.messages[0]


def test_a_snap_that_fails_is_logged_and_the_other_map_still_stored(monkeypatch) -> None:
    warnings = _Warnings()
    monkeypatch.setattr(snapped_network, "logger", warnings)
    run = shifted_run("apply", with_minimal=True)
    empty = gpd.GeoDataFrame(geometry=[], crs=run.mesh.crs)
    networks = {"reference": _line(SHIFTED_COLUMN, run), "reference_permanent": empty}
    run.hydrographic_network = lambda role="generated": networks[role]
    store = _Store()

    assert persist_snapped_networks(run, store) == ("maximal",)
    assert len(warnings.messages) == 1
    assert "snapped minimal map is not stored" in warnings.messages[0]


@pytest.mark.parametrize("error", [FileNotFoundError, KeyError, RuntimeError])
def test_an_indexed_network_missing_on_disk_is_logged_and_the_run_kept(
    monkeypatch, error: type[Exception]
) -> None:
    # The index lists the network, so the pre-check passes; its file is gone.
    warnings = _Warnings()
    monkeypatch.setattr(snapped_network, "logger", warnings)
    run = shifted_run("apply", with_minimal=True)

    def _gone(role: str = "generated") -> gpd.GeoDataFrame:
        if role == "reference":
            raise error(f"geographic feature payload of {role!r} is missing")
        return _line(SHIFTED_COLUMN, run)

    run.hydrographic_network = _gone
    store = _Store()

    assert persist_snapped_networks(run, store) == ("minimal",)
    assert list(store.written) == [SNAPPED_NETWORK_FEATURES["minimal"]]
    assert len(warnings.messages) == 1
    assert "snapped maximal map is not stored" in warnings.messages[0]


def test_a_catchment_without_a_mapped_cell_writes_no_feature() -> None:
    run = shifted_run("apply")
    snap = network_comparison_from_run(run).geometry.snap
    empty = replace(snap, raw=np.zeros_like(snap.raw))
    store = _Store()

    assert not write_snapped_network(store, run.sim_id, empty, np.zeros((15, 2)), crs=None)
    assert store.written == {}


def test_the_stored_map_is_one_geoparquet_table_of_the_run(tmp_path) -> None:
    """The feature lands in the run's table directory and reads back through the run."""
    project = tmp_path / "project"
    project.mkdir()
    (project / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    sim_id = str(uuid.uuid4())
    source = shifted_run("apply")
    snap = network_comparison_from_run(source).geometry.snap
    centroids = network_comparison_from_run(source).geometry.metric.centroids

    with Catalog(project) as catalog:
        reg = catalog.register_simulation(
            sim_id,
            project="demo",
            solver="modflow6",
            name=RUN_NAME,
            n_cells=15,
            n_layers=1,
            n_timesteps=1,
            config={"geographic": {"snap_streams": {"mode": "apply"}}},
        )
        if reg.zarr is not None:
            reg.zarr.close()
        assert write_snapped_network(catalog, sim_id, snap, centroids, crs=source.mesh.crs)
        catalog.finalize(sim_id, status="completed")

        stored = stored_snapped_network(Run(sim_id, catalog))
        assert stored is not None
        assert np.array_equal(snapped_mask_from_frame(stored, snap.raw.size), snap.snapped)
        assert stored_snapped_network(Run(sim_id, catalog), map_role="minimal") is None

    tables = project / RUNS_DIRNAME / RUN_NAME / TABLES_DIRNAME
    name = f"geographic_{SNAPPED_NETWORK_FEATURES['maximal']}{PARQUET_FILE_SUFFIX}"
    assert (tables / name).is_file()
