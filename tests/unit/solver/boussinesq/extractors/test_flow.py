"""The Boussinesq extractor stores each budget term with the MODFLOW sign, and an outflow as a positive number.

The solver counts drain, surface excess and prescribed-head flux positive when water leaves, so those
three are negated once. Recharge and wells keep their sign. A budget row then holds the inflow and the
outflow, both positive. The storage term is positive when water leaves storage to enter the flow.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.config_kit.persistence import PersistenceConfig
from hydromodpy.core.exceptions import NothingThereError
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.solver.boussinesq.extractors.flow import BoussinesqOutputAdapter, _storage_flux
from tests._helpers.run_stores import claim_run, facts_of

from .._solver_runs import extract_run

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


def test_a_one_dimensional_history_is_one_period() -> None:
    payload = {"well_flux_history_m3_s": np.array([2.0, -3.0])}  # m3/s in two cells

    components = BoussinesqOutputAdapter._budget_components(
        payload, n_timesteps=1, n_cells=2, cell_area_m2=None
    )

    np.testing.assert_array_equal(components["well"], [[2.0, -3.0]])


WELL = "well_flux_history_m3_s"
RECHARGE = "recharge_rate_history_m_s"

BUDGET_REFUSALS = [
    pytest.param(
        {}, 1, 2, np.ones(3), ValueError, "has 3 cells; expected 2", id="area of other size"
    ),
    pytest.param(
        {WELL: np.zeros((1, 3))},
        1,
        2,
        None,
        ValueError,
        "has 3 cells; expected 2",
        id="history of other size",
    ),
    pytest.param(
        {WELL: np.zeros((1, 2))},
        2,
        2,
        None,
        ValueError,
        "1 timesteps; expected at least 2",
        id="history too short",
    ),
    pytest.param(
        {RECHARGE: np.zeros((1, 2))},
        1,
        2,
        None,
        KeyError,
        "recharge history requires cell_area_m2",
        id="rate without area",
    ),
]


@pytest.mark.parametrize(
    ("payload", "n_timesteps", "n_cells", "area", "exc", "message"), BUDGET_REFUSALS
)
def test_budget_refusals(payload, n_timesteps, n_cells, area, exc, message) -> None:
    with pytest.raises(exc, match=message):
        BoussinesqOutputAdapter._budget_components(
            payload, n_timesteps=n_timesteps, n_cells=n_cells, cell_area_m2=area
        )


class _Zarr:
    """Keeps the topography the extractor writes."""

    def __init__(self) -> None:
        self.topography: dict = {}

    def write_topography(self, **fields) -> None:
        self.topography = fields

    def close(self) -> None:
        pass


def write_surface(tmp_path: Path, n_cells: int, *, z_top, z_bottom, files=None) -> _Zarr:
    zarr = _Zarr()
    store = SimpleNamespace(open_zarr=lambda _sim_id: zarr)
    for name, text in (files or {}).items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    BoussinesqOutputAdapter()._write_surface_elevation(
        "sim", store, tmp_path, n_cells, z_top_m=z_top, z_bottom_m=z_bottom
    )
    return zarr


def test_one_surface_value_covers_every_cell(tmp_path: Path) -> None:
    zarr = write_surface(tmp_path, 3, z_top=np.array([10.0]), z_bottom=np.array([2.0]))

    np.testing.assert_array_equal(zarr.topography["topography"], [10.0, 10.0, 10.0])
    np.testing.assert_array_equal(zarr.topography["z_interfaces"], [[10.0] * 3, [2.0] * 3])


SUMMARY = '{"z_top_m": [10.0, 12.0]}'

SURFACE_REFUSALS = [
    pytest.param(
        {}, None, None, FileNotFoundError, "No Boussinesq surface metadata", id="no summary file"
    ),
    pytest.param(
        {"_boussinesq_summary.json": SUMMARY},
        None,
        None,
        KeyError,
        "missing z_top_m/z_bottom_m",
        id="no bottom",
    ),
    pytest.param(
        {},
        np.zeros(2),
        np.zeros(3),
        ValueError,
        "z_top=2, z_bottom=3, n_cells=3",
        id="sizes differ",
    ),
]


@pytest.mark.parametrize(("files", "z_top", "z_bottom", "exc", "message"), SURFACE_REFUSALS)
def test_surface_refusals(tmp_path: Path, files, z_top, z_bottom, exc, message) -> None:
    with pytest.raises(exc, match=message):
        write_surface(tmp_path, 3, z_top=z_top, z_bottom=z_bottom, files=files)


def solved_payload(**members) -> dict:
    """A state history of one period on two cells, with the elapsed time of its stamp."""
    return {
        "snapshot_elapsed_seconds": np.array([0.0]),
        "z_top_m": np.array([10.0, 12.0]),
        "z_bottom_m": np.array([0.0, 1.0]),
    } | members


EXTRACT_REFUSALS = [
    pytest.param({}, KeyError, "No head data", id="no head"),
    pytest.param(
        {"head_history_m": np.array([[5.0, 6.0]])} | {"snapshot_elapsed_seconds": np.array([])},
        KeyError,
        "No snapshot_elapsed_seconds",
        id="no time axis",
    ),
    pytest.param(
        {"head_history_m": np.array([[5.0, 6.0]])},
        TypeError,
        "must implement write_time",
        id="store cannot write time",
    ),
]


@pytest.mark.parametrize(("members", "exc", "message"), EXTRACT_REFUSALS)
def test_extract_refusals(tmp_path: Path, members: dict, exc, message: str) -> None:
    np.savez(tmp_path / "_boussinesq_state_history.npz", **solved_payload(**members))

    with pytest.raises(exc, match=message):
        extract_run(SimpleNamespace(sim_id="sim"), tmp_path)


def test_extract_without_a_history_file(tmp_path: Path) -> None:
    with pytest.raises(NothingThereError, match="No _boussinesq_state_history.npz"):
        extract_run(SimpleNamespace(sim_id="sim"), tmp_path)


def open_two_cell_store(tmp_path: Path) -> RunStore:
    project = tmp_path / "project"
    claim = claim_run(project, "bouss")
    store = RunStore.open(
        claim.run_dir,
        facts=facts_of(
            claim,
            project=project.name,
            solver="boussinesq",
            n_cells=2,
            n_layers=1,
            n_timesteps=1,
            period_start=datetime(2020, 1, 1, tzinfo=UTC),
            period_end=datetime(2020, 1, 2, tzinfo=UTC),
        ),
        persistence=PersistenceConfig(field_precision="exact"),
        workspace=project,
    )
    store.create_zarr(n_cells=2, n_layers=1)
    return store


# A history of one period holding the heads of two cells, in m, written in either of the two ways
# a solver leaves it: a flat final state or a flat head history.
SINGLE_STATES = [
    pytest.param("final_head_m", id="final head only"),
    pytest.param("head_history_m", id="flat head history"),
]


@pytest.mark.parametrize("name", SINGLE_STATES)
def test_extract_a_flat_head(tmp_path: Path, name: str) -> None:
    output_dir = tmp_path / "solver"
    output_dir.mkdir()
    np.savez(
        output_dir / "_boussinesq_state_history.npz",
        **solved_payload(**{name: np.array([5.0, 6.0])}),
    )
    store = open_two_cell_store(tmp_path)
    try:
        extract_run(store, output_dir)
        with store.open_zarr(store.sim_id) as fields:
            heads = np.asarray(fields.root["head"][:]).reshape(1, 2)
    finally:
        store.close()

    np.testing.assert_allclose(heads, [[5.0, 6.0]])
