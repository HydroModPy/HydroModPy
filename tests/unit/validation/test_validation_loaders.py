"""Reading validation outputs back from the result store.

Fields are 2d arrays of heads (m). The outlet discharge of a fixed-head strip is not
a field. It is read from the budget (m3/s) as the lumped constant-head record.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from validation_cases.shared.loaders import (
    load_field,
    load_field_on_expected_grid,
    load_time_series_fields,
)

OUTLET = "outlet_discharge_east_side_m3_s"


class BudgetOnlyStore:
    """A store whose only readable table is the budget.

    It mirrors a launcher run of a fixed-head strip: no Zarr entry under the name of
    the observable, no timeseries, and one lumped constant-head record per timestep.
    """

    def __init__(self, budget):
        self._budget = budget

    def open_zarr(self, sim_id):
        raise KeyError("no field store")

    def query_timeseries(self, sim_id, station_id, variable):
        raise KeyError("no timeseries")

    def query_budget(self, sim_id):
        return self._budget


def budget_store(rows):
    """Rows are (timestep, zone_id, component, flux_out)."""
    return BudgetOnlyStore(
        pd.DataFrame(
            [
                {
                    "timestep": timestep,
                    "zone_id": zone_id,
                    "component": component,
                    "flux_in": 0.0,
                    "flux_out": flux_out,
                    "unit": "m3/d",
                }
                for timestep, zone_id, component, flux_out in rows
            ]
        )
    )


DISCHARGES = [
    pytest.param(
        [
            (0, "0", "recharge", 0.0),
            (0, "0", "constant_head", 3.0),
            (1, "0", "constant_head", 2.0),
            (2, "0", "constant_head", 1.0),
        ],
        [0, 1, 2],
        [3.0, 2.0, 1.0],
        id="falls back to the constant head record",
    ),
    # A basin writes a catchment row beside the domain row of every component. Its cells
    # lie inside the domain, so it is a second support of the same records, not a second side.
    pytest.param(
        [
            (0, "0", "constant_head", 3.0),
            (0, "catchment", "constant_head", 0.0),
            (1, "0", "constant_head", 2.0),
            (1, "catchment", "constant_head", 0.0),
        ],
        [0, 1],
        [3.0, 2.0],
        id="catchment row is no second boundary",
    ),
]


@pytest.mark.parametrize(("rows", "indices", "values"), DISCHARGES)
def test_outlet_discharge_from_the_budget(rows, indices, values):
    got_indices, got_values = load_time_series_fields(
        store=budget_store(rows), sim_id="sim", observable_name=OUTLET
    )

    assert got_indices.tolist() == indices
    assert got_values.tolist() == values


# The lumped record holds one zone. Two zones cannot answer "which side", and a total
# returned under the name of one side is a silent answer no validation case would catch.
BAD_BUDGETS = [
    pytest.param(
        [(0, "0", "drain", 1.0)], "no 'constant_head' record", id="no constant head record"
    ),
    pytest.param(
        [
            (0, "east", "constant_head", 3.0),
            (0, "west", "constant_head", 1.0),
            (1, "east", "constant_head", 2.0),
            (1, "west", "constant_head", 0.5),
        ],
        "not readable from a lumped total",
        id="two constant head zones",
    ),
]


@pytest.mark.parametrize(("rows", "match"), BAD_BUDGETS)
def test_outlet_discharge_refusals(rows, match):
    with pytest.raises(RuntimeError, match=match):
        load_time_series_fields(store=budget_store(rows), sim_id="sim", observable_name=OUTLET)


NO_STORE = [
    pytest.param(load_field, {}, id="load field"),
    pytest.param(load_time_series_fields, {}, id="load time series"),
    pytest.param(
        load_field_on_expected_grid,
        {"case_dir": Path("."), "metadata": {}, "solver": "boussinesq", "expected_shape": (1, 1)},
        id="load field on expected grid",
    ),
]


@pytest.mark.parametrize(("loader", "kwargs"), NO_STORE)
def test_loaders_require_a_store(loader, kwargs):
    with pytest.raises(ValueError, match="no store/sim_id provided"):
        loader(observable_name="watertable_elevation", **kwargs)
