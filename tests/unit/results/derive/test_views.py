"""Catchment views of a run: budget totals (m3/s) and means over the delineated catchment.

``budget_over`` sums a per-cell budget term over a polygon, the catchment by default, each
face counted by ``mesh/catchment_fraction``. ``catchment_mean`` weighs each face by its area (m2)
inside the catchment. Drainage density and active-cell metrics count the faces of the basin of D.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from pyproj import Transformer
from shapely.geometry import box
from shapely.ops import transform

from hydromodpy.results.derive import views
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.run.contracts import Mesh
from hydromodpy.results.run.descent import read_catchment_fraction
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from tests._helpers.ugrid_meshes import quad_mesh

# Two rows of three cells, six faces. Cell 2 and cell 5 lie outside the basin of D.
NROW, NCOL = 2, 3
N_CELLS = NROW * NCOL
BASIN = np.array([True, True, False, True, True, False])
FRACTION = np.array([1.0, 0.5, 0.25, 1.0, 0.75, 0.0])
STAMPS = pd.to_datetime(["1970-01-02", "1970-01-03"])

# m3/s per cell, two steps; exact in the compact float precision of the store.
RECHARGE = np.array(
    [
        [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        [0.25, 1.0, 2.0, 0.125, 0.5, 4.0],
    ]
)
DRAIN = -np.array(
    [
        [0.0, 1.0, 0.0, 0.0, 2.0, 0.0],
        [0.5, 0.0, 1.0, 0.25, 0.0, 8.0],
    ]
)
STORAGE_SS = np.array(
    [
        [0.5, -0.25, 0.0, 1.0, 0.0, 0.0],
        [-1.0, 0.5, 0.0, 0.0, 2.0, 0.0],
    ]
)
STORAGE_SY = np.array(
    [
        [-0.5, 1.0, 0.0, -2.0, 0.0, 0.0],
        [0.25, 0.0, 0.0, 0.0, -1.0, 0.0],
    ]
)

# Cell 5 has no model top: it is outside the active domain.
TOPOGRAPHY = np.array([10.0, 11.0, 12.0, 10.5, 11.5, np.nan])
ACTIVE = np.isfinite(TOPOGRAPHY)
# Columns 10, 10 and 30 m wide, 10 m high: faces of 100, 100 and 300 m2.
CELL_AREAS = np.array([100.0, 100.0, 300.0, 100.0, 100.0, 300.0])
DEPTH = np.array(  # m
    [
        [1.0, 2.0, 4.0, 3.0, 5.0, 9.0],
        [2.0, 2.0, 6.0, 1.0, 3.0, 9.0],
    ]
)
SEEPAGE = np.array([[1, 0, 0, 1, 1, 1], [0, 0, 1, 1, 0, 0]], dtype=float)
RECHARGE_FORCING = np.array([[1.0, 2.0, 3.0, 4.0, 5.0, 6.0], [2.0, 2.0, 2.0, 2.0, 8.0, 6.0]])
# An active cell is a depth above 1.5 m: cells 1 to 4 then cells 0, 1, 2 and 4.
THRESHOLD = 1.5


def write_basin(store, rule, fraction):
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


def budget_run(
    tmp_path,
    *,
    rule="near_point",
    fraction=FRACTION,
    crs="EPSG:2154",
    storage=False,
    outside=None,
):
    """A run with recharge and drain budget terms, and optional stacks outside ``budget``."""
    path = tmp_path / "run.zarr"
    store = SimulationZarr.create(path, n_cells=N_CELLS, n_layers=1)
    vertices, connectivity = quad_mesh(NROW, NCOL, cell_size=10.0)
    terms = [("recharge", RECHARGE), ("drain", DRAIN)]
    if storage:
        terms += [("storage_ss", STORAGE_SS), ("storage_sy", STORAGE_SY)]
    try:
        store.write_mesh(vertices, connectivity, np.array([0.0, -10.0]))
        store.write_time(np.array([86400.0, 2 * 86400.0]))
        for name, values in terms:
            store.write_field_stack(
                name, values[:, None, :], n_timesteps=2, timestep_offset=0, subgroup="budget"
            )
        for group, stacks in (outside or {}).items():
            for name, values in stacks.items():
                store.write_field_stack(name, values, n_timesteps=2, subgroup=group)
        if rule is not None:
            write_basin(store, rule, fraction)
    finally:
        store.close()
    mesh = Mesh(
        vertices=vertices,
        face_node_connectivity=connectivity,
        z_interfaces=np.array([[0.0] * N_CELLS, [-10.0] * N_CELLS]),
        crs=crs,
    )
    return SimpleNamespace(
        sim_id="sim-total",
        _sim_id="sim-total",
        n_timesteps=2,
        mesh=mesh,
        has_field=lambda name, **_: name in dict(terms),
        _catalog=SimpleNamespace(open_zarr=lambda sim_id: SimulationZarr(path)),
    )


def view_run(tmp_path, *, fraction=FRACTION, rule="near_point"):
    """A run with watertable depth and recharge, on a mesh whose last column is 30 m wide."""
    path = tmp_path / "run.zarr"
    store = SimulationZarr.create(path, n_cells=N_CELLS, n_layers=1)
    vertices, connectivity = quad_mesh(NROW, NCOL, cell_size=10.0)
    vertices[:, 0] = np.where(vertices[:, 0] == 30.0, 50.0, vertices[:, 0])
    try:
        store.write_mesh(
            vertices, connectivity, np.array([0.0, -10.0]), topography=TOPOGRAPHY, grid_type="disv"
        )
        store.write_time(np.array([86400.0, 2 * 86400.0]))
        store.write_field_stack(
            "watertable_depth", DEPTH[:, None, :], n_timesteps=2, subgroup="derived"
        )
        store.write_field_stack(
            "recharge",
            RECHARGE_FORCING[:, None, :],
            n_timesteps=2,
            timestep_offset=0,
            subgroup="budget",
        )
        if rule is not None:
            write_basin(store, rule, fraction)
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


def weighted_mean(stack, weights):
    finite = np.isfinite(stack)
    return (np.where(finite, stack, 0.0) @ weights) / (finite @ weights)


def test_budget_boundary_cells_by_share(tmp_path):
    run = budget_run(tmp_path)

    recharge = views.budget_over(run, "recharge")
    seepage = -views.budget_over(run, "drain", name="seepage")

    np.testing.assert_allclose(recharge.to_numpy(), RECHARGE @ FRACTION)
    np.testing.assert_allclose(seepage.to_numpy(), -DRAIN @ FRACTION)
    assert seepage.name == "seepage"
    assert list(recharge.index) == list(STAMPS)


def test_budget_without_fraction(tmp_path, caplog):
    run = budget_run(tmp_path, fraction=None)

    with caplog.at_level(logging.INFO):
        recharge = views.budget_over(run, "recharge")

    assert read_catchment_fraction(run) is None
    np.testing.assert_allclose(recharge.to_numpy(), RECHARGE @ BASIN.astype(float))
    assert "count the cells of the basin of D whole" in caplog.text


def test_budget_over_polygon(tmp_path):
    run = budget_run(tmp_path)
    # Cells 0 and 1 are the squares [0, 10] and [10, 20] of the first row; the
    # box holds all of cell 0 and half of cell 1.
    total = views.budget_over(run, "recharge", box(0.0, 0.0, 15.0, 10.0))

    np.testing.assert_allclose(total.to_numpy(), RECHARGE[:, 0] + 0.5 * RECHARGE[:, 1])


def test_budget_polygon_other_crs(tmp_path):
    run = budget_run(tmp_path, crs="EPSG:2154")
    to_wgs84 = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True).transform
    polygon = transform(to_wgs84, box(0.0, 0.0, 10.0, 10.0))

    total = views.budget_over(run, "recharge", polygon, crs="EPSG:4326")

    np.testing.assert_allclose(total.to_numpy(), RECHARGE[:, 0], rtol=1e-6)


def test_run_without_crs(tmp_path):
    run = budget_run(tmp_path, crs=None)

    total = views.budget_over(run, "recharge", box(0.0, 0.0, 10.0, 10.0), crs=None)

    np.testing.assert_allclose(total.to_numpy(), RECHARGE[:, 0])


def test_storage_family_sum(tmp_path):
    run = budget_run(tmp_path, storage=True)

    storage = views.budget_over(run, "storage")
    split = views.budget_over(run, "storage", split=True)

    np.testing.assert_allclose(storage.to_numpy(), (STORAGE_SS + STORAGE_SY) @ FRACTION)
    assert storage.name == "storage"
    elements = np.stack([STORAGE_SS, STORAGE_SY])
    np.testing.assert_allclose(split["inflow"], np.maximum(elements, 0).sum(axis=0) @ FRACTION)
    np.testing.assert_allclose(split["outflow"], np.maximum(-elements, 0).sum(axis=0) @ FRACTION)


def test_split_inflow_outflow(tmp_path):
    run = budget_run(tmp_path)

    split = views.budget_over(run, "drain", split=True)

    assert list(split.columns) == ["inflow", "outflow"]
    np.testing.assert_allclose(split["inflow"], [0.0, 0.0])
    np.testing.assert_allclose(split["outflow"], -DRAIN @ FRACTION)
    assert list(split.index) == list(STAMPS)


def test_budget_term_wins(tmp_path):
    run = budget_run(tmp_path, outside={None: {"recharge": 10.0 * RECHARGE}})

    total = views.budget_over(run, "recharge")

    np.testing.assert_allclose(total.to_numpy(), RECHARGE @ FRACTION)


def test_flux_field_outside_budget(tmp_path):
    release = np.abs(DRAIN)
    run = budget_run(tmp_path, outside={"derived": {"release_flux": release}})

    total = views.budget_over(run, "release_flux")
    split = views.budget_over(run, "release_flux", split=True)

    np.testing.assert_allclose(total.to_numpy(), release @ FRACTION)
    np.testing.assert_allclose(split["outflow"], [0.0, 0.0])


BUDGET_REFUSALS = [
    pytest.param(
        {"rule": "largest_basin", "fraction": None},
        "recharge",
        {},
        ValueError,
        "only the largest one of its domain",
        id="synthetic domain",
    ),
    pytest.param(
        {"rule": None, "fraction": None}, "recharge", {}, ValueError, "is missing", id="no basin"
    ),
    pytest.param(
        {"outside": {"derived": {"watertable_depth": np.abs(DRAIN)}}},
        "watertable_depth",
        {},
        FieldNotFoundError,
        "as a budget term or a field in m3/s",
        id="other unit outside budget",
    ),
    pytest.param(
        {},
        "storage",
        {},
        FieldNotFoundError,
        "'storage' is not stored per cell",
        id="term not stored",
    ),
    pytest.param(
        {"crs": None},
        "recharge",
        {"polygon": box(0.0, 0.0, 10.0, 10.0), "crs": "EPSG:4326"},
        ValueError,
        "stores no CRS, so a polygon in EPSG:4326",
        id="foreign crs on a run without crs",
    ),
]


@pytest.mark.parametrize(("run_kwargs", "variable", "call", "error", "message"), BUDGET_REFUSALS)
def test_budget_refusals(tmp_path, run_kwargs, variable, call, error, message):
    run = budget_run(tmp_path, **run_kwargs)

    with pytest.raises(error, match=message):
        views.budget_over(run, variable, **call)


def test_catchment_mean_area_weights(tmp_path):
    run = view_run(tmp_path)

    mean = views.catchment_mean(run, "watertable_depth")

    np.testing.assert_allclose(mean.to_numpy(), weighted_mean(DEPTH, FRACTION * CELL_AREAS))
    assert list(mean.index) == list(STAMPS)
    assert mean.name == "watertable_depth"


def test_catchment_mean_not_domain_mean(tmp_path):
    run = view_run(tmp_path)

    mean = views.catchment_mean(run, "watertable_depth", name="depth")

    assert not np.allclose(mean.to_numpy(), DEPTH[:, ACTIVE].mean(axis=1))
    assert mean.name == "depth"


def test_catchment_mean_skips_nan(tmp_path, monkeypatch):
    run = view_run(tmp_path)
    holes = DEPTH.copy()
    holes[0, 1] = np.nan
    monkeypatch.setattr(views, "_stack_field", lambda sim, variable: holes)

    mean = views.catchment_mean(run, "watertable_depth")

    np.testing.assert_allclose(mean.to_numpy(), weighted_mean(holes, FRACTION * CELL_AREAS))
    assert np.isfinite(mean.to_numpy()).all()


def test_catchment_mean_without_fraction(tmp_path):
    run = view_run(tmp_path, fraction=None)

    mean = views.catchment_mean(run, "watertable_depth")

    np.testing.assert_allclose(mean.to_numpy(), weighted_mean(DEPTH, BASIN * CELL_AREAS))


@pytest.mark.parametrize("rule", ["largest_basin", None], ids=["synthetic domain", "no basin"])
def test_catchment_mean_refusals(tmp_path, rule):
    run = view_run(tmp_path, rule=rule, fraction=None)

    with pytest.raises(ValueError, match="stores no catchment"):
        views.catchment_mean(run, "watertable_depth")


def test_saturated_fraction(tmp_path, monkeypatch):
    run = view_run(tmp_path)
    monkeypatch.setattr(views, "_stack_field", lambda sim, variable: SEEPAGE)

    series = views.saturated_fraction(run)

    # Cell 5 has no top, so five cells count: three then two are saturated.
    np.testing.assert_allclose(series.to_numpy(), [60.0, 40.0])
    over_the_basin = 100.0 * (SEEPAGE[:, BASIN] > 0).mean(axis=1)
    assert not np.allclose(series.to_numpy(), over_the_basin)
    assert list(series.index) == list(STAMPS)


def test_drainage_density(tmp_path, monkeypatch):
    run = view_run(tmp_path)
    monkeypatch.setattr(views, "_stack_field", lambda sim, variable: SEEPAGE)

    series = views.drainage_density(run)

    # The basin holds cells 0, 1, 3 and 4: three then one are above the threshold.
    np.testing.assert_allclose(series.to_numpy(), [75.0, 25.0])
    assert not np.allclose(series.to_numpy(), 100.0 * (SEEPAGE[:, ACTIVE] > 0).mean(axis=1))
    assert list(series.index) == list(STAMPS)


def test_density_matches_metrics(tmp_path, monkeypatch):
    run = view_run(tmp_path)
    monkeypatch.setattr(views, "_stack_field", lambda sim, variable: SEEPAGE)

    series = views.drainage_density(run)
    metrics = views.cell_field_active_metrics(run)

    assert metrics["catchment_cell_count"] == 4
    assert metrics["drainage_density_mean_pct"] == pytest.approx(series.mean())
    assert metrics["drainage_density_max_pct"] == pytest.approx(series.max())
    assert metrics["drainage_density_last_pct"] == pytest.approx(series.iloc[-1])


def test_density_without_catchment(tmp_path, monkeypatch, caplog):
    run = view_run(tmp_path, rule=None, fraction=None)
    monkeypatch.setattr(views, "_stack_field", lambda sim, variable: SEEPAGE)

    with caplog.at_level(logging.INFO):
        series = views.drainage_density(run)

    np.testing.assert_allclose(series.to_numpy(), [60.0, 40.0])
    assert "stores no catchment" in caplog.text


def test_recharge_forcing_is_a_rate_over_the_domain(tmp_path):
    run = view_run(tmp_path)

    series = views.recharge_forcing(run)

    # m3/s summed over the active cells, divided by their area: a depth per second.
    expected = RECHARGE_FORCING[:, ACTIVE].sum(axis=1) / CELL_AREAS[ACTIVE].sum()
    np.testing.assert_allclose(series.to_numpy(), expected)
    assert series.attrs["unit"] == "m s-1"
    # A mean of the per-cell volumes weighs the 300 m2 cell like a 100 m2 one.
    assert not np.allclose(series.to_numpy(), RECHARGE_FORCING[:, ACTIVE].mean(axis=1))


def test_view_support_documented():
    for view in (views.saturated_fraction, views.recharge_forcing):
        assert "model domain" in (view.__doc__ or ""), view.__name__
        assert "not the catchment" in (view.__doc__ or ""), view.__name__
    assert "basin of D" in (views.drainage_density.__doc__ or "")
    assert "inside the delineated catchment" in (views.catchment_mean.__doc__ or "")


def test_active_metrics_on_basin(tmp_path):
    run = view_run(tmp_path)

    metrics = views.cell_field_active_metrics(run, variable="watertable_depth", threshold=THRESHOLD)

    # Cells 0, 1, 3, 4 hold the depths 1 2 3 5 then 2 2 1 3: three are active at each step.
    assert metrics["active_cell_count_mean"] == pytest.approx(3.0)
    assert metrics["drainage_density_mean_pct"] == pytest.approx(75.0)
    assert metrics["always_active_ratio"] == pytest.approx(0.5)
    assert metrics["persistent_ratio"] == pytest.approx(1.0)


def test_overlap_metrics_on_basin(tmp_path, monkeypatch):
    run = view_run(tmp_path)
    network = np.array([False, True, True, True, False, True])
    run.hydrographic_network = lambda role: SimpleNamespace()
    monkeypatch.setattr(views, "_network_cells", lambda *args, **kwargs: network)
    monkeypatch.setattr(views, "_network_geometries", lambda *args, **kwargs: [])

    metrics = views.cell_field_network_overlap_metrics(
        run, variable="watertable_depth", threshold=THRESHOLD, mode="last"
    )

    # On the basin the active cells are 0, 1, 4 and the network cells 1, 3.
    assert metrics["catchment_cell_count"] == 4
    assert metrics["active_cell_count"] == 3
    assert metrics["network_cell_count"] == 2
    assert metrics["overlap_cell_count"] == 1
    assert metrics["active_precision_ratio"] == pytest.approx(1.0 / 3.0)
    assert metrics["network_coverage_ratio"] == pytest.approx(0.5)
