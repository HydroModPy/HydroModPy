"""Space-filling designs: the draw is pinned, nested where it claims to be, and refused when unknown."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.calibration.optim.adapters.lhs_adapter import LhsAdapter
from hydromodpy.calibration.optim.design import (
    SAMPLERS,
    DesignParameter,
    design_points,
    draw_unit,
    lot_seed,
)
from hydromodpy.calibration.optim.optimizer import optimizers
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace

# Points LhsAdapter drew at 6010d96b8, before the draw moved to design.py. They must not move.
BASE_LHS_POINTS = {
    (None, 0): [
        (2.3069506947869993e-07, 0.2079404632521194),
        (9.099687457207068e-05, 0.2988017464241816),
        (1.5371978232144996e-06, 0.08882522064736516),
        (0.0002473797943968498, 0.029611499328660112),
    ],
    (None, 1): [
        (3.077360501966352e-06, 0.2310913820163697),
        (7.17530534643094e-07, 0.01372291508254982),
        (0.0004877177347234101, 0.12430883244948825),
        (1.4869535640237434e-05, 0.1978330626132358),
    ],
    (None, 42): [
        (1.682844359566716e-06, 0.050681313117976204),
        (1.3848479105473958e-07, 0.17694081789319613),
        (8.050496251264402e-05, 0.22926737950633522),
        (0.0001733246364797344, 0.09801033786742083),
    ],
    ("random-cd", 0): [
        (2.3069506947869993e-07, 0.2079404632521194),
        (9.099687457207068e-05, 0.2988017464241816),
        (0.0002473797943968498, 0.08882522064736516),
        (1.5371978232144996e-06, 0.029611499328660112),
    ],
    ("random-cd", 1): [
        (1.4869535640237434e-05, 0.2310913820163697),
        (3.077360501966352e-06, 0.01372291508254982),
        (0.0004877177347234101, 0.12430883244948825),
        (7.17530534643094e-07, 0.1978330626132358),
    ],
    ("random-cd", 42): [
        (1.682844359566716e-06, 0.050681313117976204),
        (1.3848479105473958e-07, 0.17694081789319613),
        (8.050496251264402e-05, 0.22926737950633522),
        (0.0001733246364797344, 0.09801033786742083),
    ],
}

# Sobol points of seed 0 at the day the design was added: a drift of scipy shows here.
FROZEN_SOBOL = [
    (0.000252546799276188, 0.28009614144451916),
    (6.401176793507442e-06, 0.05841171734035015),
]

PARAMETERS = (
    DesignParameter("K", 1e-7, 1e-3, "log_uniform"),
    DesignParameter("Sy", 0.01, 0.3, "uniform"),
)


def _space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(
                name="K", lower=1e-7, upper=1e-3, search_space="log", sampling="log_uniform"
            ),
            CalibParameter(name="Sy", lower=0.01, upper=0.3),
        ]
    )


@pytest.mark.parametrize(("optimization", "seed"), sorted(BASE_LHS_POINTS, key=str))
def test_lhs_adapter_points_are_the_ones_of_the_base_commit(optimization, seed):
    adapter = LhsAdapter(_space(), n_samples=4, optimization=optimization, seed=seed)
    got = [(s.values["K"], s.values["Sy"]) for s in adapter.ask(4)]
    assert got == BASE_LHS_POINTS[(optimization, seed)]


@pytest.mark.parametrize("method", sorted(SAMPLERS))
def test_every_sampler_gives_the_unit_cube_and_the_same_points_twice(method):
    n = None if method == "grid" else 8
    first = draw_unit(method, n, 3, 5)
    again = draw_unit(method, n, 3, 5)
    assert first.shape[1] == 3
    assert np.array_equal(first, again)
    assert first.min() >= 0.0 and first.max() <= 1.0


def test_sobol_is_nested_whatever_the_size():
    small = draw_unit("sobol", 5, 2, 3)
    big = draw_unit("sobol", 16, 2, 3)
    assert np.array_equal(small, big[:5])
    assert np.array_equal(draw_unit("sobol", 8, 2, 3), big[:8])


def test_sobol_not_a_power_of_two_raises_no_warning(recwarn):
    draw_unit("sobol", 6, 2, 1)
    assert not recwarn.list


def test_lhs_hits_every_stratum_once_with_and_without_random_cd():
    for options in ({}, {"optimization": "random-cd"}):
        unit = draw_unit("lhs", 10, 3, 4, options)
        for column in unit.T:
            assert sorted((column * 10).astype(int)) == list(range(10))


def test_log_column_stays_stratified_after_the_physical_mapping():
    points = design_points("lhs", [10], 7, PARAMETERS)
    decades = np.log10([p.values["K"] for p in points])
    strata = np.floor((decades - (-7)) / 4 * 10).astype(int)
    assert sorted(strata) == list(range(10))


def test_grid_counts_the_product_of_its_axes_and_reaches_the_bounds():
    points = design_points("grid", None, None, PARAMETERS, {"points_per_dim": [3, 2]})
    assert [p.recipe for p in points] == [f"p{i:04d}" for i in range(1, 7)]
    assert sorted({p.values["Sy"] for p in points}) == [0.01, 0.3]
    assert min(p.values["K"] for p in points) == pytest.approx(1e-7)
    assert max(p.values["K"] for p in points) == pytest.approx(1e-3)


def test_lhs_lots_keep_the_earlier_lots_and_use_distinct_seeds():
    one = design_points("lhs", [4], 9, PARAMETERS)
    two = design_points("lhs", [4, 4], 9, PARAMETERS)
    assert two[:4] == one
    assert [p.recipe for p in two[4:]] == ["b2p0001", "b2p0002", "b2p0003", "b2p0004"]
    assert lot_seed(9, 1) != lot_seed(9, 2)
    assert two[4].values != two[0].values


def test_sobol_doubling_keeps_the_first_points_and_the_names():
    four = design_points("sobol", 4, 11, PARAMETERS)
    eight = design_points("sobol", 8, 11, PARAMETERS)
    assert eight[:4] == four
    assert [p.recipe for p in four] == ["p0001", "p0002", "p0003", "p0004"]


def test_sobol_points_are_frozen_for_one_seed():
    points = design_points("sobol", 2, 0, PARAMETERS)
    assert [(p.values["K"], p.values["Sy"]) for p in points] == FROZEN_SOBOL


def test_two_seeds_in_one_process_are_independent():
    a = design_points("sobol", 4, 1, PARAMETERS)
    b = design_points("sobol", 4, 2, PARAMETERS)
    assert a != b
    assert a == design_points("sobol", 4, 1, PARAMETERS)


def test_unknown_method_names_the_known_ones():
    with pytest.raises(ValueError, match="sobol, lhs, grid"):
        draw_unit("maximin", 4, 2, 1)


def test_the_names_shared_with_calibration_are_the_same_names():
    assert {"lhs", "grid"} <= set(SAMPLERS) & set(optimizers.names())


def test_an_option_of_another_method_is_refused():
    with pytest.raises(ValueError, match="optimization"):
        draw_unit("grid", None, 2, None, {"optimization": "random-cd"})
