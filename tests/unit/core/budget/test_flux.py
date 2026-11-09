"""Per-cell budget fluxes: sign, outflow, drains with mover, release and seepage.

Every solver gives a per-cell flux the MODFLOW sign: negative where water leaves
the aquifer, positive where it enters. An outflow is therefore never negative,
and a stack of periods is the sum of its periods.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.budget.flux import (
    RELEASE_BUDGET_KEYS,
    budget_outflow,
    budget_outflow_stack,
    drain_band_depth,
    drain_stack_with_mover,
    find_drain_budget_key,
    first_finite_layer,
    has_release_budget,
    networks_route_drainage,
    release_flux_stack,
    seepage_mask,
    select_budget_zone,
)
from hydromodpy.core.scope import CATCHMENT, DOMAIN

# ------------------------------------------------------------------ zones


def _zones(*zones: str) -> pd.DataFrame:
    return pd.DataFrame({"zone_id": list(zones), "value": range(len(zones))})


@pytest.mark.parametrize(
    ("frame", "rows", "label"),
    [
        (_zones(DOMAIN, CATCHMENT), [1], "the delineated catchment"),
        (_zones(DOMAIN, DOMAIN), [0, 1], "the model domain"),
        (_zones("other"), [0], "the model domain"),
        (pd.DataFrame({"value": [1, 2]}), [0, 1], "the model domain"),
    ],
    ids=["catchment-wins", "domain-only", "unknown-zone", "no-zone-column"],
)
def test_the_catchment_rows_win_over_the_domain_so_water_is_not_counted_twice(frame, rows, label):
    chosen, said = select_budget_zone(frame)
    assert chosen["value"].tolist() == [frame["value"].tolist()[i] for i in rows]
    assert said == label


# -------------------------------------------------------- routed drainage


def _model(active, networks):
    """A model double read by its ``boundaries`` and ``sfr`` members."""
    return SimpleNamespace(
        boundaries=SimpleNamespace(active_ids=tuple(active or ())),
        sfr=(networks or {}).get("sfr"),
    )


@pytest.mark.parametrize(
    ("model", "routes"),
    [
        (_model(["sfr"], {"sfr": {"a": {}}}), True),
        (_model(["SFR"], {"sfr": {"a": {"route_drainage": True}}}), True),
        (_model(["sfr"], {"sfr": {"a": {"route_drainage": False}}}), False),
        (_model(["sfr"], {"sfr": {"a": SimpleNamespace(route_drainage=False), "b": {}}}), False),
        (_model(["sfr"], {"sfr": {"a": SimpleNamespace(route_drainage=True)}}), True),
        (_model(["lak"], {"sfr": {"a": {}}}), False),
        (_model(["sfr"], {"sfr": {}}), False),
        (_model(["sfr"], None), False),
        (_model(None, None), False),
        (SimpleNamespace(), False),
    ],
    ids=[
        "default-on",
        "upper-case",
        "kept-out",
        "one-network-keeps-out",
        "attr-on",
        "lake-only",
        "no-reach",
        "no-sinks",
        "no-active",
        "bare",
    ],
)
def test_only_an_active_sfr_network_that_keeps_routing_takes_the_drainage(model, routes):
    assert networks_route_drainage(model) is routes


def test_a_drain_key_is_found_in_a_mapping_and_not_in_what_cannot_be_searched():
    assert find_drain_budget_key({"drain": 1}) == "drain"
    assert find_drain_budget_key({"stream": 1}) is None
    assert find_drain_budget_key(5) is None


# ------------------------------------------------------------ outflow


@pytest.mark.parametrize(
    ("signed", "n_cells", "expected"),
    [
        ([-1.0, 2.0, 0.0], 3, [1.0, 0.0, 0.0]),
        ([[-1.0, -2.0], [-3.0, 4.0]], 2, [4.0, 2.0]),  # two layers summed per cell
        ([-1.0, -2.0, -3.0, -4.0], 2, [4.0, 6.0]),  # flat field reshaped on n_cells
        ([[-1.0, -2.0], [-3.0, 4.0]], None, [4.0, 2.0]),
        ([-1.0, 2.0], None, [1.0, 0.0]),
        ([np.nan, -9999.0, 1.0, -5.0], 4, [0.0, 0.0, 0.0, 5.0]),
    ],
    ids=["one-layer", "two-layers", "flat", "no-n_cells-2d", "no-n_cells-1d", "missing-values"],
)
def test_the_outflow_of_a_step_is_the_water_that_leaves_and_adds_nothing_when_it_enters(
    signed, n_cells, expected
):
    assert budget_outflow(np.array(signed), n_cells=n_cells).tolist() == expected


def test_a_scalar_budget_is_one_cell():
    assert budget_outflow(-2.5).tolist() == [2.5]


def test_a_three_dimensional_step_keeps_its_first_axis_summed_and_loses_no_water():
    field = -np.ones((2, 3, 4))
    out = budget_outflow(field)
    assert out.shape == (12,)
    assert out.sum() == pytest.approx(24.0)


@pytest.mark.parametrize("seed", range(5))
def test_an_outflow_is_never_negative_and_never_exceeds_the_water_leaving(seed):
    rng = np.random.default_rng(seed)
    signed = rng.normal(size=(4, 3, 7))
    out = budget_outflow_stack(signed, n_cells=7)
    assert out.shape == (4, 7)
    assert (out >= 0).all()
    assert out.sum() == pytest.approx(-signed[signed < 0].sum())


def test_a_stack_of_periods_is_the_per_period_outflow_stacked():
    rng = np.random.default_rng(0)
    signed = rng.normal(size=(5, 2, 6))
    stack = budget_outflow_stack(signed, n_cells=6)
    for t in range(5):
        np.testing.assert_allclose(stack[t], budget_outflow(signed[t], n_cells=6))


def test_a_two_dimensional_stack_has_one_layer():
    stack = budget_outflow_stack(np.array([[-1.0, 2.0], [-3.0, -4.0]]), n_cells=2)
    assert stack.tolist() == [[1.0, 0.0], [3.0, 4.0]]


def test_a_stack_of_layers_flattened_on_n_cells_is_summed_per_cell():
    stack = budget_outflow_stack(np.array([[[-1.0, -2.0, -3.0, -4.0]]]), n_cells=2)
    assert stack.tolist() == [[4.0, 6.0]]


def test_an_empty_stack_gives_zeros_and_a_wrong_rank_is_refused():
    assert budget_outflow_stack(np.empty((3, 0, 0)), n_cells=4).tolist() == [[0.0] * 4] * 3
    with pytest.raises(ValueError, match="Expected a"):
        budget_outflow_stack(np.zeros(5), n_cells=5)


# ------------------------------------------------------ drain and mover


def test_a_drain_and_its_mover_record_add_up_cell_by_cell():
    budget = {"drain": np.array([[-1.0, -2.0]]), "drain_to_mover": np.array([[-0.5, 0.0]])}
    assert drain_stack_with_mover(budget, "drain", 0, 1).tolist() == [[-1.5, -2.0]]


@pytest.mark.parametrize(
    ("budget", "key", "expected"),
    [
        ({"drain": np.array([[-1.0]])}, "drain", [[-1.0]]),
        ({"drain_to_mover": np.array([[-2.0]])}, None, [[-2.0]]),
        (
            {"drain": np.array([[-1.0]]), "drain_to_mover": np.array([[-1.0, -1.0]])},
            "drain",
            [[-1.0]],
        ),
        ({"stream": np.array([[-1.0]])}, None, None),
    ],
    ids=["drain-only", "mover-only", "shape-mismatch-keeps-drain", "neither"],
)
def test_the_drain_stack_uses_what_the_store_holds(budget, key, expected):
    got = drain_stack_with_mover(budget, key, 0, 1)
    assert (got is None) if expected is None else got.tolist() == expected


def test_the_drain_stack_reads_only_the_rows_asked():
    budget = {"drain": np.arange(-5.0, 0.0).reshape(5, 1)}
    assert drain_stack_with_mover(budget, "drain", 1, 3).ravel().tolist() == [-4.0, -3.0]


# ------------------------------------------------------------ release


def test_the_release_keys_hold_the_drain_the_mover_and_the_surface_paths():
    assert {"drain", "drain_to_mover", "stream", "lake", "surface_excess"} <= set(
        RELEASE_BUDGET_KEYS
    )
    assert "constant_head" not in RELEASE_BUDGET_KEYS  # an ocean is not a release to the surface


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (["drain"], True),
        (["stream"], True),
        (["constant_head_stream"], True),
        (["constant_head"], False),
        ([], False),
    ],
)
def test_a_store_has_a_release_path_only_for_a_drain_or_a_surface_term(names, expected):
    assert has_release_budget({n: 0 for n in names}) is expected


def test_the_release_is_the_sum_of_every_path_out_and_nothing_enters():
    budget = {
        "drain": np.array([[-1.0, 0.0, 0.0]]),
        "drain_to_mover": np.array([[-0.5, 0.0, 0.0]]),
        "stream": np.array([[0.0, -2.0, 0.0]]),
        "lake": np.array([[0.0, 0.0, -3.0]]),
        "surface_excess": np.array([[0.0, -0.25, 0.0]]),
        "recharge": np.array([[10.0, 10.0, 10.0]]),  # not a path out
        "constant_head": np.array([[-99.0, -99.0, -99.0]]),  # no role: not counted
    }
    got = release_flux_stack(budget, n_cells=3, start=0, stop=1)
    np.testing.assert_allclose(got, [[1.5, 2.25, 3.0]])


def test_a_gaining_cell_releases_nothing():
    budget = {"stream": np.array([[5.0, -1.0]])}
    assert release_flux_stack(budget, n_cells=2, start=0, stop=1).tolist() == [[0.0, 1.0]]


def test_a_slice_of_the_release_is_the_release_over_that_slice():
    rng = np.random.default_rng(1)
    budget = {"drain": rng.normal(size=(6, 1, 4)), "stream": rng.normal(size=(6, 1, 4))}
    whole = release_flux_stack(budget, n_cells=4, start=0, stop=6)
    part = release_flux_stack(budget, n_cells=4, start=2, stop=5)
    np.testing.assert_allclose(part, whole[2:5])
    assert (whole >= 0).all()
    assert np.isfinite(whole).all()


def test_an_empty_slice_is_an_empty_stack_and_no_path_at_all_is_refused():
    budget = {"drain": np.zeros((3, 1, 2))}
    assert release_flux_stack(budget, n_cells=2, start=2, stop=2).shape == (0, 2)
    with pytest.raises(KeyError, match="No release budget field"):
        release_flux_stack({"recharge": np.zeros((1, 2))}, n_cells=2, start=0, stop=1)


# ----------------------------------------------------------------- seepage


def test_the_seepage_mask_is_one_where_the_water_table_reaches_the_land_surface():
    mask = seepage_mask(
        watertable=np.array([10.0, 9.9, 10.1]), topography=np.array([10.0, 10.0, 10.0])
    )
    assert mask.tolist() == [1.0, 0.0, 1.0]


def test_a_banded_drain_seeps_from_half_a_band_below_the_surface():
    wt, top = np.array([[9.4, 9.6]]), np.array([10.0, 10.0])
    assert seepage_mask(watertable=wt, topography=top).tolist() == [[0.0, 0.0]]
    assert seepage_mask(watertable=wt, topography=top, band_depth=1.0).tolist() == [[0.0, 1.0]]


def test_a_stack_of_water_tables_is_masked_step_by_step():
    wt = np.array([[1.0, 5.0], [6.0, 5.0]])
    mask = seepage_mask(watertable=wt, topography=np.array([5.0, 5.0]))
    assert mask.shape == wt.shape
    assert mask.tolist() == [[0.0, 1.0], [1.0, 1.0]]


def test_a_solver_surface_excess_wins_over_the_geometry():
    mask = seepage_mask(
        surface_excess=np.array([-0.1, 0.0, 0.2]),
        watertable=np.array([100.0] * 3),
        topography=np.array([0.0] * 3),
    )
    assert mask.tolist() == [1.0, 0.0, 0.0]


def test_a_mask_without_surface_excess_needs_both_water_table_and_topography():
    for kwargs in ({}, {"watertable": np.zeros(2)}, {"topography": np.zeros(2)}):
        with pytest.raises(ValueError, match="needs either surface_excess"):
            seepage_mask(**kwargs)


# ------------------------------------------------------------- drain band


class _Root:
    def __init__(self, attrs):
        self.attrs = attrs


@pytest.mark.parametrize(
    ("root", "depth"),
    [
        (_Root({"drain_band_depth_m": 2.5}), 2.5),
        (_Root({}), 0.0),
        (_Root({"drain_band_depth_m": -1.0}), 0.0),
        (_Root({"drain_band_depth_m": float("nan")}), 0.0),
        (_Root({"drain_band_depth_m": float("inf")}), 0.0),
        (object(), 0.0),
        (SimpleNamespace(attrs=None), 0.0),
    ],
    ids=["band", "absent", "negative", "nan", "inf", "no-attrs", "attrs-none"],
)
def test_the_drain_band_is_read_back_from_the_store_and_zero_when_unusable(root, depth):
    assert drain_band_depth(root) == depth


# ------------------------------------------------------------------ water table


def test_first_finite_layer_of_a_head_without_layers_is_the_head() -> None:
    """A one-layer, (time, n_cells) head is the water table as it is."""
    head = np.array([[1.0, np.nan], [2.0, 3.0]])

    np.testing.assert_array_equal(first_finite_layer(head), head)


def test_first_finite_layer_takes_the_topmost_finite_layer_of_each_column() -> None:
    """A dry cell of the top layer reads the first layer below that is finite."""
    head = np.array(
        [
            [
                [np.nan, 5.0, np.nan],  # layer 0: the first column dry, 5.0, the last dry
                [1.5, 6.0, np.nan],  # layer 1: 1.5, dry already answered, and dry again
                [9.0, 7.0, np.nan],  # layer 2: never read, a finite layer is above
            ]
        ]
    )

    np.testing.assert_allclose(first_finite_layer(head), [[1.5, 5.0, np.nan]])


def test_a_column_of_no_finite_layer_is_nan_head() -> None:
    head = np.array([[[np.nan], [np.nan]]])

    water_table = first_finite_layer(head)

    assert np.isnan(water_table).tolist() == [[True]]
