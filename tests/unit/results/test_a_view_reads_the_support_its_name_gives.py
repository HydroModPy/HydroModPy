"""A view that says catchment reads the basin, the others keep the active domain.

``catchment_mean`` weighs each face by its area inside the delineated catchment.
``saturated_fraction`` and ``recharge_forcing`` do not say catchment, so they keep
the active cells of the model domain, the cells with a finite model top, whatever
the basin is. The drainage density and the metrics of an active cell field carry
the catchment: their cells are the active faces of the basin of D, whole, and
every share is taken over them. ``catchment_cell_count`` is their number.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.derive import views
from hydromodpy.results.run.contracts import Mesh
from hydromodpy.results.zarr_store import SimulationZarr
from tests._helpers.ugrid_meshes import quad_mesh

NROW, NCOL = 2, 3
N_CELLS = NROW * NCOL
BASIN = np.array([True, True, False, True, True, False])
FRACTION = np.array([1.0, 0.5, 0.25, 1.0, 0.75, 0.0])
# Cell 5 has no model top: it is outside the active domain.
TOPOGRAPHY = np.array([10.0, 11.0, 12.0, 10.5, 11.5, np.nan])
ACTIVE = np.isfinite(TOPOGRAPHY)
# Columns 10, 10 and 30 m wide, 10 m high: faces of 100, 100 and 300 m2.
AREAS = np.array([100.0, 100.0, 300.0, 100.0, 100.0, 300.0])
DEPTH = np.array(
    [
        [1.0, 2.0, 4.0, 3.0, 5.0, 9.0],
        [2.0, 2.0, 6.0, 1.0, 3.0, 9.0],
    ]
)
SEEPAGE = np.array([[1, 0, 0, 1, 1, 1], [0, 0, 1, 1, 0, 0]], dtype=float)
RECHARGE = np.array([[1.0, 2.0, 3.0, 4.0, 5.0, 6.0], [2.0, 2.0, 2.0, 2.0, 8.0, 6.0]])
STAMPS = pd.to_datetime(["1970-01-02", "1970-01-03"])


def _mesh() -> tuple[np.ndarray, np.ndarray]:
    vertices, connectivity = quad_mesh(NROW, NCOL, cell_size=10.0)
    vertices[:, 0] = np.where(vertices[:, 0] == 30.0, 50.0, vertices[:, 0])
    return vertices, connectivity


def _run(tmp_path, *, fraction: np.ndarray | None = FRACTION, rule: str | None = "near_point"):
    path = tmp_path / "run.zarr"
    store = SimulationZarr.create(path, n_cells=N_CELLS, n_layers=1)
    vertices, connectivity = _mesh()
    try:
        store.write_mesh(
            vertices, connectivity, np.array([0.0, -10.0]), topography=TOPOGRAPHY, grid_type="disv"
        )
        store.write_time(np.array([86400.0, 2 * 86400.0]))
        store.write_field_stack(
            "watertable_depth", DEPTH[:, None, :], n_timesteps=2, subgroup="derived"
        )
        store.write_field_stack(
            "recharge", RECHARGE[:, None, :], n_timesteps=2, timestep_offset=0, subgroup="budget"
        )
        if rule is not None:
            store.write_descent(
                receiver=np.full(N_CELLS, -1, dtype=np.int64),
                surface=np.zeros(N_CELLS),
                base_level=np.zeros(N_CELLS, dtype=bool),
                constant_head=np.zeros(N_CELLS, dtype=bool),
                raised=np.zeros(N_CELLS, dtype=bool),
                channel=np.zeros(N_CELLS, dtype=bool),
                pinned=np.zeros(N_CELLS, dtype=bool),
                attrs={"adjacency": "shared_nodes"},
                basin=BASIN,
                basin_attrs={"descent_outlet": 0, "basin_rule": rule},
                catchment_fraction=fraction,
            )
    finally:
        store.close()
    return SimpleNamespace(
        sim_id="sim-view",
        _sim_id="sim-view",
        n_timesteps=2,
        mesh=Mesh(
            vertices=vertices, face_node_connectivity=connectivity, z_interfaces=np.zeros((2, 6))
        ),
        _catalog=SimpleNamespace(open_zarr=lambda sim_id: SimulationZarr(path)),
    )


def _weighted_mean(stack: np.ndarray, weights: np.ndarray) -> np.ndarray:
    finite = np.isfinite(stack)
    return (np.where(finite, stack, 0.0) @ weights) / (finite @ weights)


def test_the_catchment_mean_weighs_each_face_by_its_area_in_the_catchment(tmp_path) -> None:
    run = _run(tmp_path)

    mean = views.catchment_mean(run, "watertable_depth")

    np.testing.assert_allclose(mean.to_numpy(), _weighted_mean(DEPTH, FRACTION * AREAS))
    assert list(mean.index) == list(STAMPS)
    assert mean.name == "watertable_depth"


def test_the_catchment_mean_is_no_longer_the_mean_of_the_active_domain(tmp_path) -> None:
    run = _run(tmp_path)

    mean = views.catchment_mean(run, "watertable_depth", name="depth")

    over_the_domain = DEPTH[:, ACTIVE].mean(axis=1)
    assert not np.allclose(mean.to_numpy(), over_the_domain)
    assert mean.name == "depth"


def test_a_face_without_a_value_leaves_the_sum_and_the_weights(tmp_path, monkeypatch) -> None:
    run = _run(tmp_path)
    holes = DEPTH.copy()
    holes[0, 1] = np.nan
    monkeypatch.setattr(views, "_stack_field", lambda sim, variable: holes)

    mean = views.catchment_mean(run, "watertable_depth")

    np.testing.assert_allclose(mean.to_numpy(), _weighted_mean(holes, FRACTION * AREAS))
    assert np.isfinite(mean.to_numpy()).all()


def test_a_run_without_a_fraction_counts_the_basin_whole(tmp_path) -> None:
    run = _run(tmp_path, fraction=None)

    mean = views.catchment_mean(run, "watertable_depth")

    np.testing.assert_allclose(mean.to_numpy(), _weighted_mean(DEPTH, BASIN * AREAS))


@pytest.mark.parametrize("rule", ["largest_basin", None], ids=["synthetic_domain", "no_basin"])
def test_a_run_with_no_catchment_has_no_catchment_mean(tmp_path, rule) -> None:
    run = _run(tmp_path, rule=rule, fraction=None)

    with pytest.raises(ValueError, match="stores no catchment"):
        views.catchment_mean(run, "watertable_depth")


def test_the_saturated_fraction_counts_the_cells_of_the_active_domain(
    tmp_path, monkeypatch
) -> None:
    run = _run(tmp_path)
    monkeypatch.setattr(views, "_stack_field", lambda sim, variable: SEEPAGE)

    series = views.saturated_fraction(run)

    # Cell 5 has no top, so five cells count: three then two are saturated.
    np.testing.assert_allclose(series.to_numpy(), [60.0, 40.0])
    over_the_basin = 100.0 * (SEEPAGE[:, BASIN] > 0).mean(axis=1)
    assert not np.allclose(series.to_numpy(), over_the_basin)
    assert list(series.index) == list(STAMPS)


def test_the_drainage_density_counts_the_cells_of_the_basin(tmp_path, monkeypatch) -> None:
    run = _run(tmp_path)
    monkeypatch.setattr(views, "_stack_field", lambda sim, variable: SEEPAGE)

    series = views.drainage_density(run)

    # The basin holds cells 0, 1, 3 and 4: three then one are above the threshold.
    np.testing.assert_allclose(series.to_numpy(), [75.0, 25.0])
    over_the_domain = 100.0 * (SEEPAGE[:, ACTIVE] > 0).mean(axis=1)
    assert not np.allclose(series.to_numpy(), over_the_domain)
    assert list(series.index) == list(STAMPS)


def test_the_drainage_density_and_the_metrics_read_the_same_cells(tmp_path, monkeypatch) -> None:
    run = _run(tmp_path)
    monkeypatch.setattr(views, "_stack_field", lambda sim, variable: SEEPAGE)

    series = views.drainage_density(run)
    metrics = views.cell_field_active_metrics(run)

    assert metrics["catchment_cell_count"] == 4
    assert metrics["drainage_density_mean_pct"] == pytest.approx(series.mean())
    assert metrics["drainage_density_max_pct"] == pytest.approx(series.max())
    assert metrics["drainage_density_last_pct"] == pytest.approx(series.iloc[-1])


def test_a_run_with_no_catchment_reads_the_active_domain_for_its_drainage_density(
    tmp_path, monkeypatch, caplog
) -> None:
    run = _run(tmp_path, rule=None, fraction=None)
    monkeypatch.setattr(views, "_stack_field", lambda sim, variable: SEEPAGE)

    with caplog.at_level(logging.INFO):
        series = views.drainage_density(run)

    np.testing.assert_allclose(series.to_numpy(), [60.0, 40.0])
    assert "stores no catchment" in caplog.text


def test_the_recharge_forcing_is_the_mean_over_the_active_domain(tmp_path) -> None:
    run = _run(tmp_path)

    series = views.recharge_forcing(run)

    np.testing.assert_allclose(series.to_numpy(), RECHARGE[:, ACTIVE].mean(axis=1))
    assert not np.allclose(series.to_numpy(), RECHARGE[:, BASIN].mean(axis=1))


def test_the_support_of_each_view_is_in_its_docstring() -> None:
    for view in (views.saturated_fraction, views.recharge_forcing):
        assert "model domain" in (view.__doc__ or ""), view.__name__
        assert "not the catchment" in (view.__doc__ or ""), view.__name__
    assert "basin of D" in (views.drainage_density.__doc__ or "")
    assert "inside the delineated catchment" in (views.catchment_mean.__doc__ or "")


# An active cell is a depth above 1.5 m: cells 1 to 4 then cells 0, 1, 2 and 4.
THRESHOLD = 1.5


def _overlap(run, monkeypatch, network: np.ndarray) -> dict:
    run.hydrographic_network = lambda role: SimpleNamespace()
    monkeypatch.setattr(views, "_network_cells", lambda *args, **kwargs: network)
    monkeypatch.setattr(views, "_network_geometries", lambda *args, **kwargs: [])
    return views.cell_field_network_overlap_metrics(
        run, variable="watertable_depth", threshold=THRESHOLD, mode="last"
    )


def test_the_catchment_cell_count_is_the_active_faces_of_the_basin(tmp_path) -> None:
    run = _run(tmp_path)

    metrics = views.cell_field_active_metrics(run, variable="watertable_depth", threshold=THRESHOLD)

    assert metrics["catchment_cell_count"] == int((BASIN & ACTIVE).sum()) == 4
    assert metrics["catchment_cell_count"] != int(ACTIVE.sum())


def test_every_share_of_the_active_metrics_is_taken_over_the_basin(tmp_path) -> None:
    run = _run(tmp_path)

    metrics = views.cell_field_active_metrics(run, variable="watertable_depth", threshold=THRESHOLD)

    # Cells 0, 1, 3, 4 hold the depths 1 2 3 5 then 2 2 1 3: three are active at each step.
    assert metrics["active_cell_count_mean"] == pytest.approx(3.0)
    assert metrics["drainage_density_mean_pct"] == pytest.approx(75.0)
    assert metrics["always_active_ratio"] == pytest.approx(0.5)
    assert metrics["persistent_ratio"] == pytest.approx(1.0)


def test_the_overlap_metrics_read_the_cells_of_the_basin(tmp_path, monkeypatch) -> None:
    run = _run(tmp_path)
    network = np.array([False, True, True, True, False, True])

    metrics = _overlap(run, monkeypatch, network)

    # On the basin the active cells are 0, 1, 4 and the network cells 1, 3.
    assert metrics["catchment_cell_count"] == 4
    assert metrics["active_cell_count"] == 3
    assert metrics["network_cell_count"] == 2
    assert metrics["overlap_cell_count"] == 1
    assert metrics["active_precision_ratio"] == pytest.approx(1.0 / 3.0)
    assert metrics["network_coverage_ratio"] == pytest.approx(0.5)


def test_the_active_mask_keeps_the_active_domain(tmp_path) -> None:
    run = _run(tmp_path)

    mask = views.cell_field_active_mask(
        run, variable="watertable_depth", threshold=THRESHOLD, mode="last"
    )

    np.testing.assert_array_equal(np.isfinite(mask), ACTIVE)


def test_a_run_with_no_catchment_counts_its_active_domain_and_says_so(tmp_path, caplog) -> None:
    run = _run(tmp_path, rule=None, fraction=None)

    with caplog.at_level(logging.INFO):
        metrics = views.cell_field_active_metrics(
            run, variable="watertable_depth", threshold=THRESHOLD
        )

    assert metrics["catchment_cell_count"] == int(ACTIVE.sum())
    assert "stores no catchment" in caplog.text


def test_a_synthetic_domain_counts_its_active_domain(tmp_path) -> None:
    run = _run(tmp_path, rule="largest_basin", fraction=None)

    metrics = views.cell_field_active_metrics(run, variable="watertable_depth", threshold=THRESHOLD)

    assert metrics["catchment_cell_count"] == int(ACTIVE.sum())
