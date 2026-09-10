"""A file says how precisely it wants the answer, not what scipy calls it.

Nine engines stop for nine reasons and name the rule nine ways. The precision is
stated once, on the parameter, and each engine's traits say which of its own
options that writes. What is gated here is the arithmetic of that translation,
because a wrong conversion does not fail: it reports convergence on a bracket
orders of magnitude wide.
"""

from __future__ import annotations

import math

import pytest

from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.optim.stopping import search_width, stopping_kwargs

K = CalibParameter(name="K", lower=1e-8, upper=1e-2, transform="log")
SY = CalibParameter(name="Sy", lower=1e-4, upper=0.5, transform="log")
POROSITY = CalibParameter(name="n", lower=0.0, upper=0.4, transform="identity")


def test_a_log_parameter_reads_a_precision_as_a_ratio() -> None:
    # Ten per cent on a conductivity is 0.0414 decades wherever the value sits,
    # so the bounds do not enter at all.
    assert search_width(K, 0.10) == pytest.approx(math.log10(1.1))
    assert search_width(SY, 0.10) == pytest.approx(math.log10(1.1))


def test_a_linear_parameter_reads_it_as_a_fraction_of_its_interval() -> None:
    # Nothing on the value to be relative to before the search has a value.
    assert search_width(POROSITY, 0.05) == pytest.approx(0.05 * 0.4)


def test_nelder_mead_gets_the_precision_as_an_absolute_width() -> None:
    kwargs = stopping_kwargs("scipy_nelder_mead", ParameterSpace([K]), tolerance=0.10)
    assert kwargs == {"xatol": pytest.approx(math.log10(1.1))}


def test_the_strictest_parameter_sets_the_width() -> None:
    # One number stops the search for every parameter at once.
    space = ParameterSpace([K, POROSITY])
    kwargs = stopping_kwargs("scipy_nelder_mead", space, tolerance=0.05)
    assert kwargs["xatol"] == pytest.approx(
        min(search_width(K, 0.05), search_width(POROSITY, 0.05))
    )


def test_the_root_search_reads_the_same_number_unconverted() -> None:
    # rel_tol is already a relative width on the parameter's own value, and the
    # paper's one per cent is the engine's default, so the two agree.
    kwargs = stopping_kwargs("bisection", ParameterSpace([K]), tolerance=0.01)
    assert kwargs == {"rel_tol": 0.01}


def test_the_declared_kwargs_pass_through_untouched_without_a_precision() -> None:
    declared = {"maxiter": 30, "xatol": 0.30}
    assert (
        stopping_kwargs("scipy_nelder_mead", ParameterSpace([K]), tolerance=None, declared=declared)
        == declared
    )


def test_the_precision_joins_the_other_declared_kwargs() -> None:
    kwargs = stopping_kwargs(
        "scipy_nelder_mead", ParameterSpace([K]), tolerance=0.10, declared={"maxiter": 30}
    )
    assert kwargs["maxiter"] == 30
    assert kwargs["xatol"] == pytest.approx(math.log10(1.1))


def test_saying_it_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="both set the"):
        stopping_kwargs(
            "scipy_nelder_mead",
            ParameterSpace([K]),
            tolerance=0.10,
            declared={"xatol": 0.30},
        )


def test_an_engine_that_stops_on_its_budget_refuses_a_precision() -> None:
    # Silently dropping it would report a search that honoured a request it never
    # read. The message has to name what does bound that engine.
    with pytest.raises(ValueError, match="max_iter"):
        stopping_kwargs("grid", ParameterSpace([K]), tolerance=0.10)


def test_the_built_optimizers_accept_what_the_translation_produces() -> None:
    from hydromodpy.calibration.optim.optimizer import build_optimizer

    space = ParameterSpace([K])
    for method, extra in (("scipy_nelder_mead", {}), ("bisection", {"sweep_points": 0})):
        kwargs = stopping_kwargs(method, space, tolerance=0.05, declared=extra)
        assert build_optimizer(method, space, **kwargs) is not None
