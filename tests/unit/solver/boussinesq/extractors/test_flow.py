"""The Boussinesq extractor stores each budget term with the MODFLOW sign, and an outflow as a positive number.

The solver counts drain, surface excess and prescribed-head flux positive when water leaves, so those
three are negated once. Recharge and wells keep their sign. A budget row then holds the inflow and the
outflow, both positive. The storage term is positive when water leaves storage to enter the flow.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.extractors.flow import BoussinesqOutputAdapter, _storage_flux

_AREA = np.array([10.0])


class _Store:
    def __init__(self) -> None:
        self.budgets: list[dict] = []

    def write_budgets(self, _sim_id: str, records: list[dict]) -> None:
        self.budgets = records


def _row(history: str, value: float) -> dict:
    payload = {history: np.array([[value]])}
    components = BoussinesqOutputAdapter._budget_components(
        payload, n_timesteps=1, n_cells=1, cell_area_m2=_AREA
    )
    store = _Store()
    BoussinesqOutputAdapter._write_budget_table("sim", store, components, n_timesteps=1)
    assert len(store.budgets) == 1
    return store.budgets[0]


# One row per solver history: its name, the component it gives, the value the solver wrote, and
# the inflow and outflow of the row. A rate in m/s is multiplied by the cell area of 10 m2.
_HISTORIES = [
    pytest.param("drainage_flux_history_m3_s", "drain", 0.5, 0.0, 0.5, id="drain_leaves"),
    pytest.param(
        "drainage_flux_history_m3_s", "drain", -0.5, 0.5, 0.0, id="a_negative_drain_enters"
    ),
    pytest.param("drainage_flux_history_m3_s", "drain", 0.0, 0.0, 0.0, id="no_drainage"),
    pytest.param(
        "prescribed_head_flux_history_m3_s", "constant_head", 2.0, 0.0, 2.0, id="chd_leaves"
    ),
    pytest.param(
        "prescribed_head_flux_history_m3_s", "constant_head", -3.0, 3.0, 0.0, id="chd_feeds"
    ),
    pytest.param(
        "saturation_excess_history_m_s", "surface_excess", 1.0e-1, 0.0, 1.0, id="excess_leaves"
    ),
    pytest.param("recharge_rate_history_m_s", "recharge", 1.0e-1, 1.0, 0.0, id="recharge_enters"),
    pytest.param(
        "recharge_rate_history_m_s",
        "recharge",
        -1.0e-1,
        0.0,
        1.0,
        id="a_loss_to_evapotranspiration",
    ),
    pytest.param("well_flux_history_m3_s", "well", 0.75, 0.75, 0.0, id="injection_enters"),
    pytest.param("well_flux_history_m3_s", "well", -0.25, 0.0, 0.25, id="pumping_leaves"),
]


@pytest.mark.parametrize(("history", "component", "value", "flux_in", "flux_out"), _HISTORIES)
def test_a_solver_term_is_stored_with_the_modflow_sign(
    history, component, value, flux_in, flux_out
) -> None:
    row = _row(history, value)

    assert row["component"] == component
    assert row["flux_in"] == pytest.approx(flux_in, abs=1e-15)
    assert row["flux_out"] == pytest.approx(flux_out, abs=1e-15)
    assert row["flux_in"] >= 0.0 and row["flux_out"] >= 0.0


def _storage(heads: list[float], bottom: float = 0.0) -> float:
    payload = {
        "storage_coefficient": np.array([0.1]),
        "z_bottom_m": np.array([bottom]),
        "cell_area_m2": np.array([100.0]),
        "head_history_m": np.array(heads, dtype=float).reshape(-1, 1),
        "snapshot_elapsed_seconds": np.array([0.0, 86400.0]),
    }
    return float(_storage_flux(payload, first_snapshot=1, n_periods=1)[0, 0])


# One row per head change over one day on a cell of 100 m2 and Sy 0.1: the head before and after
# and the flux out of storage in m3/s. A rise stores water, so water leaves the flow: negative.
_STORAGE = [
    pytest.param([10.0, 11.0], 0.0, -10.0 / 86400.0, id="a_rise_fills_the_storage"),
    pytest.param([11.0, 10.0], 0.0, 10.0 / 86400.0, id="a_fall_empties_the_storage"),
    pytest.param([10.0, 10.0], 0.0, 0.0, id="no_change"),
    pytest.param([-1.0, -2.0], 0.0, 0.0, id="a_dry_cell_has_no_drainable_volume"),
    pytest.param([0.0, 1.0], 0.0, -10.0 / 86400.0, id="a_cell_wetting_from_its_bottom"),
]


@pytest.mark.parametrize(("heads", "bottom", "flux"), _STORAGE)
def test_the_storage_term_is_positive_when_water_leaves_storage(heads, bottom, flux) -> None:
    assert _storage(heads, bottom) == pytest.approx(flux, abs=1e-18)


def test_a_steady_history_has_no_storage_term() -> None:
    assert _storage_flux({}, first_snapshot=0, n_periods=1) is None


def test_a_missing_storage_input_is_named() -> None:
    with pytest.raises(KeyError, match="storage_coefficient"):
        _storage_flux({"z_bottom_m": np.array([0.0])}, first_snapshot=1, n_periods=1)
