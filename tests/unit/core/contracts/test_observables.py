"""The observable contract between a solver and its callers: what a request names and which timesteps it selects."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.contracts.observables import (
    ObservableRequest,
    ObservableResult,
    require_unique_request_ids,
    select_time_indices,
)

REFUSED_REQUESTS = [
    pytest.param({"support": "boundary"}, "needs a key", id="boundary without key"),
    pytest.param({"support": "lake"}, "needs a key", id="lake without key"),
    pytest.param({"support": "cell"}, r"needs a \(layer, row, col\) cell", id="cell without cell"),
    pytest.param({"id": "", "support": "domain"}, "non-empty id", id="empty id"),
    pytest.param({"name": "", "support": "domain"}, "non-empty name", id="empty name"),
    pytest.param(
        {"support": "domain", "times": ()}, "empty set of timesteps", id="empty time tuple"
    ),
]


@pytest.mark.parametrize(("kwargs", "message"), REFUSED_REQUESTS)
def test_request_refusals(kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        ObservableRequest(**{"id": "h", "name": "head"} | kwargs)


def test_valid_requests() -> None:
    for support in ("boundary", "lake"):
        ObservableRequest(id="x", name="discharge", support=support, key="lac0")  # type: ignore[arg-type]
    ObservableRequest(id="h", name="head", support="cell", cell=(0, 1, 2))


def test_result_shape() -> None:
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
def test_time_indices(selector, expected) -> None:
    assert select_time_indices(4, selector).tolist() == expected


def test_time_indices_out_of_range() -> None:
    with pytest.raises(ValueError, match="out of range"):
        select_time_indices(4, (4,))
    with pytest.raises(ValueError, match="out of range"):
        select_time_indices(4, (-5,))


def test_time_indices_on_an_empty_run() -> None:
    # "all" over nothing is an empty selection, not an error; asking for a
    # specific timestep of a run that has none is an error.
    assert select_time_indices(0, "all").tolist() == []
    with pytest.raises(ValueError, match="no timestep"):
        select_time_indices(0, "last")


def test_unknown_time_selector() -> None:
    with pytest.raises(ValueError, match="unknown time selector"):
        select_time_indices(4, "middle")  # type: ignore[arg-type]


def test_duplicate_request_ids() -> None:
    # The returned mapping is keyed by id, so a duplicate would silently drop
    # one of the two requests instead of answering both.
    first = ObservableRequest(id="q", name="discharge", support="domain")
    second = ObservableRequest(id="q", name="head", support="cell", cell=(0, 0, 0))

    require_unique_request_ids([first])
    require_unique_request_ids([])
    with pytest.raises(ValueError, match=r"distinct ids; \['q'\] repeat"):
        require_unique_request_ids([first, second])
