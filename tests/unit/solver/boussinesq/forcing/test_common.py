"""Period series of the Boussinesq forcing: heads in m, recharge in m/s, one value per stress period.

The mixin turns a scalar, a sequence or a dated record into one value per period, and refuses
two prescribed heads that disagree on the same cell or edge.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.model.model import ModelTime
from hydromodpy.solver.boussinesq.forcing.common import ForcingCommonMixin
from tests._helpers.model_factory import make_model


def transient_host() -> ForcingCommonMixin:
    """A forcing host on a transient run with no steady period and no time grid."""
    host = ForcingCommonMixin()
    host.inputs = make_model(
        time=ModelTime(grid=None, regime="transient", first_period_steady=False)
    )
    return host


# Two prescribed heads on the same support, in m. The second one is on cells 1 and 2.
OVERLAPS = [
    pytest.param(
        "assign_prescribed_head_cells", "cell_indices", "prescribed-head BC on cell 1", id="cells"
    ),
    pytest.param(
        "assign_boundary_head_edges", "edge_indices", "boundary-head support on edge 1", id="edges"
    ),
]


@pytest.mark.parametrize(("method", "indices", "message"), OVERLAPS)
def test_conflicting_heads_are_refused(method: str, indices: str, message: str) -> None:
    assign = getattr(ForcingCommonMixin, method)
    values = np.full(3, np.nan)
    assign(values, **{indices: np.array([0, 1])}, head_value_m=10.0, label="flow.bc.west")
    # The same head on a shared cell is not a conflict.
    assign(values, **{indices: np.array([1])}, head_value_m=10.0, label="flow.bc.east")

    with pytest.raises(
        ValueError, match=rf"flow.bc.south overlaps another {message}.*10.0 vs 12.0"
    ):
        assign(values, **{indices: np.array([1, 2])}, head_value_m=12.0, label="flow.bc.south")


FORCINGS = [
    pytest.param(SimpleNamespace(kind="constant", value=3.0), [3.0, 3.0], id="constant"),
    pytest.param(
        SimpleNamespace(kind="values", values=[1.0, 2.0]), [1.0, 2.0], id="one per period"
    ),
]


@pytest.mark.parametrize(("forcing", "series"), FORCINGS)
def test_boundary_head_from_a_forcing(forcing: object, series: list[float]) -> None:
    boundary = SimpleNamespace(forcing=forcing)

    heads = transient_host().boundary_value_series(boundary=boundary, bc_id="west", nper=2)

    np.testing.assert_array_equal(heads, series)


DATED = pd.Series([1e-9, 2e-9, 3e-9], index=pd.date_range("2020-01-01", periods=3))  # m/s

RECHARGES = [
    pytest.param(3, 0, [], id="no period"),
    pytest.param([4e-9], 3, [4e-9] * 3, id="one value for every period"),
    pytest.param(DATED, 3, [1e-9, 2e-9, 3e-9], id="dated record"),
]


@pytest.mark.parametrize(("payload", "nper", "series"), RECHARGES)
def test_recharge_period_series(payload: object, nper: int, series: list[float]) -> None:
    rates = transient_host().recharge_period_series(
        payload=payload, nper=nper, first_clim="first", label="recharge"
    )

    np.testing.assert_allclose(rates, series, rtol=0.0, atol=1e-18)


SIMPLE_SERIES = [
    pytest.param(5.0, 0, [], id="no period"),
    pytest.param(5.0, 2, [5.0, 5.0], id="scalar"),
    pytest.param([5.0], 2, [5.0, 5.0], id="one value for every period"),
    pytest.param([5.0, 6.0, 7.0], 3, [5.0, 6.0, 7.0], id="one value per period"),
    pytest.param([5.0, 6.0, 7.0], 1, [5.0], id="first value of a longer record"),
]


@pytest.mark.parametrize(("payload", "nper", "series"), SIMPLE_SERIES)
def test_simple_period_series(payload: object, nper: int, series: list[float]) -> None:
    values = ForcingCommonMixin.simple_period_series(payload, nper=nper, label="head")

    np.testing.assert_array_equal(values, series)


SEQUENCES = [
    pytest.param(pd.Series([1.0, 2.0]), [1.0, 2.0], id="pandas series"),
    pytest.param((3, 4), [3.0, 4.0], id="tuple"),
]


@pytest.mark.parametrize(("payload", "values"), SEQUENCES)
def test_payload_to_sequence(payload: object, values: list[float]) -> None:
    np.testing.assert_array_equal(
        ForcingCommonMixin.payload_to_sequence(payload, label="head"), values
    )


def refuse_recharge(payload: object, nper: int) -> None:
    transient_host().recharge_period_series(
        payload=payload, nper=nper, first_clim="first", label="recharge"
    )


def refuse_simple(payload: object, nper: int) -> None:
    ForcingCommonMixin.simple_period_series(payload, nper=nper, label="head")


def refuse_sequence(payload: object, nper: int) -> None:
    ForcingCommonMixin.payload_to_sequence(payload, label="head")


REFUSALS = [
    pytest.param(refuse_recharge, None, 2, ValueError, "recharge cannot be None", id="no recharge"),
    pytest.param(
        refuse_recharge,
        [1e-9, 2e-9],
        3,
        ValueError,
        r"length \(2\) must be 1 or match nper \(3\)",
        id="recharge length",
    ),
    pytest.param(refuse_simple, None, 2, ValueError, "head is required", id="no head"),
    pytest.param(
        refuse_simple,
        [1.0, 2.0],
        3,
        ValueError,
        r"length \(2\) must be 1 or match nper \(3\)",
        id="head length",
    ),
    pytest.param(refuse_sequence, ["a", "b"], 1, TypeError, "head must be numeric", id="text"),
    pytest.param(refuse_sequence, [], 1, ValueError, "head cannot be empty", id="empty"),
    pytest.param(
        refuse_sequence, [1.0, np.nan], 1, ValueError, "only finite numeric", id="not finite"
    ),
]


@pytest.mark.parametrize(("refuse", "payload", "nper", "exc", "message"), REFUSALS)
def test_refusals(refuse, payload: object, nper: int, exc, message: str) -> None:
    with pytest.raises(exc, match=message):
        refuse(payload, nper)
