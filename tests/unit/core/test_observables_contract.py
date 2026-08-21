"""Unit tests for the solver-facing observable contract."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.contracts.observables import (
    ObservableRequest,
    ObservableResult,
    select_time_indices,
)
from hydromodpy.core.exceptions import ObservableNotAvailableError, SolverError


def test_request_is_frozen_and_hashable() -> None:
    request = ObservableRequest(id="q", name="discharge", support="domain")
    with pytest.raises(AttributeError):
        request.name = "head"  # type: ignore[misc]
    assert {request, ObservableRequest(id="q", name="discharge", support="domain")} == {request}


def test_request_defaults_to_every_timestep() -> None:
    assert ObservableRequest(id="q", name="discharge", support="domain").times == "all"


@pytest.mark.parametrize("support", ["boundary", "lake"])
def test_keyed_supports_need_a_key(support: str) -> None:
    with pytest.raises(ValueError, match="needs a key"):
        ObservableRequest(id="x", name="discharge", support=support)  # type: ignore[arg-type]
    ObservableRequest(id="x", name="discharge", support=support, key="lac0")  # type: ignore[arg-type]


def test_cell_support_needs_a_cell() -> None:
    with pytest.raises(ValueError, match=r"needs a \(layer, row, col\) cell"):
        ObservableRequest(id="h", name="head", support="cell")
    ObservableRequest(id="h", name="head", support="cell", cell=(0, 1, 2))


def test_request_rejects_empty_identifiers() -> None:
    with pytest.raises(ValueError, match="non-empty id"):
        ObservableRequest(id="", name="head", support="domain")
    with pytest.raises(ValueError, match="non-empty name"):
        ObservableRequest(id="h", name="", support="domain")


def test_request_rejects_an_empty_time_tuple() -> None:
    with pytest.raises(ValueError, match="empty set of timesteps"):
        ObservableRequest(id="h", name="head", support="domain", times=())


def test_result_carries_its_shape_in_the_data() -> None:
    # One class covers a scalar, a series and a field: the consumer reads ndim.
    scalar = ObservableResult(request_id="a", values=np.asarray(1.0), units="m")
    series = ObservableResult(request_id="b", values=np.zeros(3), units="m3 s-1")
    field = ObservableResult(request_id="c", values=np.zeros((3, 7)), units="m3 s-1")

    assert (scalar.values.ndim, series.values.ndim, field.values.ndim) == (0, 1, 2)
    assert scalar.times is None


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        ("all", [0, 1, 2, 3]),
        ("first", [0]),
        ("last", [3]),
        ((1, 2), [1, 2]),
        ((-1,), [3]),
        ((0, -2), [0, 2]),
    ],
)
def test_select_time_indices(selector, expected) -> None:
    assert select_time_indices(4, selector).tolist() == expected


def test_select_time_indices_bounds_check() -> None:
    with pytest.raises(ValueError, match="out of range"):
        select_time_indices(4, (4,))
    with pytest.raises(ValueError, match="out of range"):
        select_time_indices(4, (-5,))


def test_select_time_indices_on_an_empty_run() -> None:
    # "all" over nothing is an empty selection, not an error; asking for a
    # specific timestep of a run that has none is an error.
    assert select_time_indices(0, "all").tolist() == []
    with pytest.raises(ValueError, match="no timestep"):
        select_time_indices(0, "last")


def test_select_time_indices_rejects_an_unknown_selector() -> None:
    with pytest.raises(ValueError, match="unknown time selector"):
        select_time_indices(4, "middle")  # type: ignore[arg-type]


def test_observable_error_is_a_solver_error() -> None:
    # It must be catchable as a solver failure, and it must carry a code so the
    # CLI can map it to an exit code like every other typed exception.
    error = ObservableNotAvailableError("release_flux is not available")
    assert isinstance(error, SolverError)
    assert error.code == "HMPY.E408"
