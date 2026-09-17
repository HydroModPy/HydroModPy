"""Tests for validation output loader contracts."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from validation_cases.shared.loaders import (
    load_field,
    load_field_on_expected_grid,
    load_time_series_fields,
)


def test_load_field_requires_store_context() -> None:
    with pytest.raises(ValueError, match="no store/sim_id provided"):
        load_field(observable_name="watertable_elevation")


def test_load_time_series_fields_requires_store_context() -> None:
    with pytest.raises(ValueError, match="no store/sim_id provided"):
        load_time_series_fields(observable_name="watertable_elevation")


def test_load_field_on_expected_grid_requires_store_context(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no store/sim_id provided"):
        load_field_on_expected_grid(
            observable_name="watertable_elevation",
            case_dir=tmp_path,
            metadata={},
            solver="boussinesq",
            expected_shape=(1, 1),
        )


class _BudgetOnlyStore:
    """A store whose only readable table is the budget.

    Mirrors what a launcher run of a fixed-head strip leaves behind: no Zarr
    entry under the observable's name, no `_catchment` timeseries at all, and a
    budget carrying one lumped constant-head record per timestep.
    """

    def __init__(self, budget: pd.DataFrame) -> None:
        self._budget = budget

    def open_zarr(self, sim_id: str):  # noqa: ARG002
        raise KeyError("no field store")

    def query_timeseries(self, sim_id: str, station_id: str, variable: str):  # noqa: ARG002
        raise KeyError("no timeseries")

    def query_budget(self, sim_id: str):  # noqa: ARG002
        return self._budget


def _budget_rows(components: list[tuple[int, str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timestep": timestep,
                "zone_id": zone_id,
                "component": component,
                "flux_in": 0.0,
                "flux_out": flux_out,
                "unit": "m3/d",
            }
            for timestep, zone_id, component, flux_out in components
        ]
    )


def test_the_outlet_discharge_falls_back_to_the_constant_head_record() -> None:
    """The name the extractors write, not the raw MODFLOW label they stopped writing."""
    store = _BudgetOnlyStore(
        _budget_rows(
            [
                (0, "0", "recharge", 0.0),
                (0, "0", "constant_head", 3.0),
                (1, "0", "constant_head", 2.0),
                (2, "0", "constant_head", 1.0),
            ]
        )
    )

    indices, values = load_time_series_fields(
        store=store, sim_id="sim", observable_name="outlet_discharge_east_side_m3_s"
    )

    assert indices.tolist() == [0, 1, 2]
    assert values.tolist() == [3.0, 2.0, 1.0]


def test_a_budget_without_a_constant_head_record_says_so() -> None:
    """The generic "queries failed" message named nothing a reader could act on."""
    store = _BudgetOnlyStore(_budget_rows([(0, "0", "drain", 1.0)]))

    with pytest.raises(RuntimeError, match="no 'constant_head' record"):
        load_time_series_fields(
            store=store, sim_id="sim", observable_name="outlet_discharge_east_side_m3_s"
        )


def test_two_constant_head_zones_refuse_a_per_boundary_question() -> None:
    """One record lumps one zone. Two zones cannot answer "which side".

    Returning the total under the name of one side is the silent answer, and a
    silent answer is the one a validation case cannot catch.
    """
    store = _BudgetOnlyStore(
        _budget_rows(
            [
                (0, "east", "constant_head", 3.0),
                (0, "west", "constant_head", 1.0),
                (1, "east", "constant_head", 2.0),
                (1, "west", "constant_head", 0.5),
            ]
        )
    )

    with pytest.raises(RuntimeError, match="not readable from a lumped total"):
        load_time_series_fields(
            store=store, sim_id="sim", observable_name="outlet_discharge_east_side_m3_s"
        )
