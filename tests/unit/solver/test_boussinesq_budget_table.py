"""Boussinesq lumped budget: always written, MODFLOW in/out orientation."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.extractors.flow import BoussinesqOutputAdapter


class _RecordingStore:
    """Minimal store capturing the lumped budget rows."""

    def __init__(self) -> None:
        self.budgets: list[dict] = []

    def write_budgets(self, sim_id: str, records: list[dict]) -> None:
        self.budgets = records


def _components() -> dict[str, np.ndarray]:
    return {
        "recharge": np.array([[1.0, 2.0]]),
        "drain": np.array([[0.5, 0.0]]),
        "well": np.array([[-0.25, 0.75]]),
        "surface_excess": np.array([[0.0, 0.125]]),
        "constant_head": np.array([[-3.0, 4.0]]),
    }


def _by_component(records: list[dict]) -> dict[str, dict]:
    return {record["component"]: record for record in records}


def test_budget_components_convert_rates_to_fluxes() -> None:
    payload = {
        "recharge_rate_history_m_s": np.array([[1e-8, 2e-8]]),
        "saturation_excess_history_m_s": np.array([[0.0, 3e-8]]),
        "drainage_flux_history_m3_s": np.array([[0.5, 0.0]]),
    }
    components = BoussinesqOutputAdapter._budget_components(
        payload,
        n_timesteps=1,
        n_cells=2,
        cell_area_m2=np.array([10.0, 20.0]),
    )

    assert set(components) == {"recharge", "drain", "surface_excess"}
    assert components["recharge"] == pytest.approx(np.array([[1e-7, 4e-7]]))
    assert components["surface_excess"] == pytest.approx(np.array([[0.0, 6e-7]]))
    assert components["drain"] == pytest.approx(np.array([[0.5, 0.0]]))


def test_outflow_positive_components_land_in_flux_out() -> None:
    store = _RecordingStore()

    BoussinesqOutputAdapter._write_budget_table("sim", store, _components(), n_timesteps=1)

    rows = _by_component(store.budgets)
    # Drain and surface excess only ever leave the aquifer.
    assert rows["drain"]["flux_in"] == pytest.approx(0.0)
    assert rows["drain"]["flux_out"] == pytest.approx(0.5)
    assert rows["surface_excess"]["flux_out"] == pytest.approx(0.125)
    # A prescribed-head cell that feeds the aquifer carries a negative flux.
    assert rows["constant_head"]["flux_in"] == pytest.approx(3.0)
    assert rows["constant_head"]["flux_out"] == pytest.approx(4.0)


def test_source_components_keep_the_modflow_orientation() -> None:
    store = _RecordingStore()

    BoussinesqOutputAdapter._write_budget_table("sim", store, _components(), n_timesteps=1)

    rows = _by_component(store.budgets)
    assert rows["recharge"]["flux_in"] == pytest.approx(3.0)
    assert rows["recharge"]["flux_out"] == pytest.approx(0.0)
    # Well flux is signed: injection enters, pumping leaves.
    assert rows["well"]["flux_in"] == pytest.approx(0.75)
    assert rows["well"]["flux_out"] == pytest.approx(0.25)
    assert all(record["unit"] == "m3/s" for record in store.budgets)


def test_every_timestep_gets_one_row_per_component() -> None:
    store = _RecordingStore()
    components = {"drain": np.array([[1.0], [2.0], [3.0]])}

    BoussinesqOutputAdapter._write_budget_table("sim", store, components, n_timesteps=3)

    assert [record["timestep"] for record in store.budgets] == [0, 1, 2]
    assert [record["flux_out"] for record in store.budgets] == pytest.approx([1.0, 2.0, 3.0])
