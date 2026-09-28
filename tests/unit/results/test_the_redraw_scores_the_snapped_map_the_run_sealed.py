"""A run that scored a snapped map redraws the snapped map, and can store it.

The setting lives in the run's sealed configuration, ``[geographic.snap_streams]``,
so the redraw reads it there: a figure of an ``apply`` run shows the map the
criterion scored, and one of an ``off`` run the raw projection, without the
caller naming either.
"""

from __future__ import annotations

from types import SimpleNamespace

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString

from hydromodpy.core.stream_snap import SnapStreamsConfig
from hydromodpy.results.derive.snapped_network import (
    SNAPPED_NETWORK_COLUMNS,
    SNAPPED_NETWORK_FEATURES,
    snap_settings_of_run,
    snapped_mask_from_frame,
    snapped_network_frame,
    stored_snapped_network,
    write_snapped_network,
)
from hydromodpy.results.derive.stream_network import network_comparison_from_run
from tests.unit.display._network_comparison_run import (
    AXIS_COLUMN,
    CELL_M,
    NY,
    cell,
    column_cells,
    comparison_run,
)

SHIFTED_COLUMN = AXIS_COLUMN + 1


def shifted_run(mode: str | None):
    """A run whose mapped network lies one column off the talweg."""
    run = comparison_run(seepage_cells=[cell(AXIS_COLUMN, row) for row in range(NY)])
    x = (SHIFTED_COLUMN + 0.5) * CELL_M
    network = gpd.GeoDataFrame(
        geometry=[LineString([(x, 0.1 * CELL_M), (x, (NY - 0.1) * CELL_M)])], crs=run.mesh.crs
    )
    run.hydrographic_network = lambda role="generated": network
    run.config_snapshot = None if mode is None else {"geographic": {"snap_streams": {"mode": mode}}}
    return run


def _mapped(comparison) -> list[int]:
    return sorted(int(index) for index in np.flatnonzero(comparison.mapped))


def test_a_run_without_the_setting_did_not_snap() -> None:
    assert snap_settings_of_run(shifted_run(None)) is None
    assert snap_settings_of_run(shifted_run("off")) is None
    assert snap_settings_of_run(SimpleNamespace(sim_id="x")) is None


def test_an_off_run_redraws_the_raw_map() -> None:
    comparison = network_comparison_from_run(shifted_run(None))

    assert comparison.geometry.snap is None
    assert _mapped(comparison) == column_cells(SHIFTED_COLUMN)


def test_an_apply_run_redraws_the_snapped_map() -> None:
    comparison = network_comparison_from_run(shifted_run("apply"))

    assert comparison.geometry.snap is not None
    assert _mapped(comparison) == column_cells(AXIS_COLUMN)


def test_a_diagnose_run_redraws_the_raw_map_and_carries_the_snap() -> None:
    comparison = network_comparison_from_run(shifted_run("diagnose"))

    assert _mapped(comparison) == column_cells(SHIFTED_COLUMN)
    snap = comparison.geometry.snap
    assert sorted(int(i) for i in np.flatnonzero(snap.snapped)) == column_cells(AXIS_COLUMN)


def test_a_caller_may_name_the_setting_itself() -> None:
    comparison = network_comparison_from_run(
        shifted_run(None), snap=SnapStreamsConfig(mode="apply")
    )

    assert _mapped(comparison) == column_cells(AXIS_COLUMN)


def test_the_snapped_map_is_stored_and_read_back() -> None:
    run = shifted_run("apply")
    comparison = network_comparison_from_run(run)
    snap = comparison.geometry.snap
    written: dict[str, gpd.GeoDataFrame] = {}
    store = SimpleNamespace(
        write_geographic_feature=lambda sim_id, name, frame: written.__setitem__(name, frame)
    )

    write_snapped_network(
        store, run.sim_id, snap, comparison.geometry.metric.centroids, crs=run.mesh.crs
    )
    frame = written[SNAPPED_NETWORK_FEATURES["maximal"]]
    run.geographic = lambda name: written[name]

    assert set(SNAPPED_NETWORK_COLUMNS) <= set(frame.columns)
    assert set(frame["status"]) == {"moved"}
    assert np.allclose(frame["displacement_m"], CELL_M)
    stored = stored_snapped_network(run)
    assert np.array_equal(snapped_mask_from_frame(stored, snap.raw.size), snap.snapped)
    assert stored_snapped_network(run, map_role="minimal") is None


def test_the_frame_places_a_rejected_cell_at_its_raw_centre() -> None:
    run = shifted_run("diagnose")
    comparison = network_comparison_from_run(
        run, snap=SnapStreamsConfig(mode="diagnose", radius="1 m")
    )
    snap = comparison.geometry.snap
    frame = snapped_network_frame(snap, comparison.geometry.metric.centroids, crs=run.mesh.crs)

    rejected = frame[frame["status"] == "rejected"]
    assert not rejected.empty
    assert np.allclose(rejected.geometry.x, rejected["raw_x"])
    assert (rejected["snapped_cell"] == -1).all()
