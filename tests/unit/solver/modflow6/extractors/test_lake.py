"""The LAK extractor stores a lake outflow as a positive number and the exchange from the lake side.

MODFLOW 6 reports the water that leaves a lake negative. The extractor stores it positive, like an
SFR outflow. The lake-aquifer exchange is the applied flux of the LAK budget, positive when the lake
gains water from the aquifer (``GWF_IN - GWF_OUT``), so the lake gains what the aquifer loses and
the exchange is read against the convention of ``core/budget/flux.py`` with its sign turned. A rate
is divided by the seconds in one TDIS unit, a state keeps its unit, and the MODFLOW 6 no-data
sentinel of an outlet that carries nothing is zero flow.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.solver.modflow6.extractors import lake as lake_extractor
from hydromodpy.solver.modflow6.extractors.lake import (
    AppliedExchange,
    LakeObsSpec,
    build_lake_records,
    read_applied_exchange,
)

_SPT = 86400.0
_DNODATA = 3.0e30


def _spec(*obsnames_and_quantities: tuple[str, str], lake_id: str = "lac0") -> LakeObsSpec:
    return LakeObsSpec.from_mapping(
        {
            "obs_csv": "m.lak.obs.csv",
            "entries": [
                {"obsname": obsname, "lake_id": lake_id, "quantity": quantity}
                for obsname, quantity in obsnames_and_quantities
            ],
        }
    )


def _write(tmp_path: Path, spec: LakeObsSpec, values: list[float]) -> Path:
    obs = tmp_path / spec.obs_csv
    header = ",".join(["TIME"] + [entry.obsname.upper() for entry in spec.entries])
    obs.write_text(f"{header}\n{_SPT},{','.join(str(v) for v in values)}\n", encoding="utf-8")
    return obs


def _records(tmp_path: Path, spec: LakeObsSpec, values: list[float]):
    obs = _write(tmp_path, spec, values)
    return build_lake_records(spec, obs, times=[_SPT], seconds_per_time_unit=_SPT)


# One row per quantity: the value MODFLOW 6 writes for a period of one day, the value stored and
# its unit. A rate of 86 400 m3/day is 1 m3/s. The outflows are negated, the rest keep their sign.
_QUANTITIES = [
    pytest.param("ext_outflow", -_SPT, 1.0, "m3 s-1", id="ext_outflow_rendered_positive"),
    pytest.param("outlet", -_SPT, 1.0, "m3 s-1", id="outlet_rendered_positive"),
    pytest.param("to_mvr", -_SPT, 1.0, "m3 s-1", id="to_mvr_rendered_positive"),
    pytest.param("outlet_inflow", _SPT, 1.0, "m3 s-1", id="outlet_inflow_kept"),
    pytest.param("inflow", _SPT, 1.0, "m3 s-1", id="inflow_kept"),
    pytest.param("rainfall", _SPT / 2, 0.5, "m3 s-1", id="rainfall_kept"),
    pytest.param("lake_storage", -2.0 * _SPT, -2.0, "m3 s-1", id="storage_keeps_its_sign"),
    pytest.param("stage", 90.0, 90.0, "m", id="stage_is_a_state_in_meters"),
    pytest.param("volume", 450.0, 450.0, "m3", id="volume_is_a_state_in_cubic_meters"),
    pytest.param("surface_area", 90.0, 90.0, "m2", id="surface_area_is_a_state_in_square_meters"),
    pytest.param("ext_outflow", _DNODATA, 0.0, "m3 s-1", id="dnodata_is_zero_flow"),
    pytest.param("outlet", -_DNODATA, 0.0, "m3 s-1", id="negative_dnodata_is_zero_flow"),
]


@pytest.mark.parametrize(("quantity", "written", "stored", "unit"), _QUANTITIES)
def test_a_lake_quantity_is_stored_with_its_sign_and_unit(
    tmp_path, quantity, written, stored, unit
) -> None:
    spec = _spec((f"lac0_{quantity}", quantity))

    timeseries, _ = _records(tmp_path, spec, [written])

    assert [(r["variable"], r["unit"]) for r in timeseries] == [(quantity, unit)]
    assert timeseries[0]["value"] == pytest.approx(stored, abs=1e-15)
    assert timeseries[0]["station_id"] == "lake:lac0"


def test_the_outlets_of_one_lake_are_summed_into_one_positive_outflow(tmp_path) -> None:
    spec = _spec(("lac0_ext_outflow_0", "ext_outflow"), ("lac0_ext_outflow_1", "ext_outflow"))

    timeseries, _ = _records(tmp_path, spec, [-_SPT, -3.0 * _SPT])

    assert [r["value"] for r in timeseries] == pytest.approx([4.0])


def test_the_outlet_of_a_lake_fed_by_another_is_positive_and_the_receiver_gains(tmp_path) -> None:
    """The upstream lake loses water through its outlet, the downstream lake receives it."""
    spec = LakeObsSpec.from_mapping(
        {
            "obs_csv": "m.lak.obs.csv",
            "entries": [
                {"obsname": "up_outlet_0", "lake_id": "up", "quantity": "outlet"},
                {"obsname": "down_outlet_inflow", "lake_id": "down", "quantity": "outlet_inflow"},
            ],
        }
    )

    timeseries, _ = _records(tmp_path, spec, [-_SPT, _SPT])

    by_key = {(r["station_id"], r["variable"]): r["value"] for r in timeseries}
    assert by_key[("lake:up", "outlet")] == pytest.approx(1.0)
    assert by_key[("lake:down", "outlet_inflow")] == pytest.approx(1.0)


# One row per applied exchange, positive when the lake gains water from the aquifer: the value in
# m3/s stored on the lake side and the budget row. A lake that gains is an outflow of the aquifer.
_EXCHANGE = [
    pytest.param(_SPT, 1.0, 1.0, 0.0, id="the_lake_gains"),
    pytest.param(-_SPT, -1.0, 0.0, 1.0, id="the_lake_loses"),
    pytest.param(0.0, 0.0, 0.0, 0.0, id="no_exchange"),
    pytest.param(-0.0, 0.0, 0.0, 0.0, id="negative_zero"),
]


@pytest.mark.parametrize(("applied", "stored", "flux_in", "flux_out"), _EXCHANGE)
def test_the_applied_exchange_is_read_from_the_lake_side(
    tmp_path, monkeypatch, applied, stored, flux_in, flux_out
) -> None:
    spec = _spec(("lac0_stage", "stage"))
    monkeypatch.setattr(
        lake_extractor,
        "read_applied_exchange",
        lambda _spec, _path, *, times: {"lac0": AppliedExchange(total=[applied], under_dam=None)},
    )

    timeseries, budgets = _records(tmp_path, spec, [90.0])

    exchange = next(r for r in timeseries if r["variable"] == "gwf_exchange")
    assert exchange["value"] == pytest.approx(stored, abs=1e-15)
    assert len(budgets) == 1
    assert budgets[0]["component"] == "lak_gwf"
    assert budgets[0]["flux_in"] == pytest.approx(flux_in, abs=1e-15)
    assert budgets[0]["flux_out"] == pytest.approx(flux_out, abs=1e-15)


class _Record:
    def __init__(self, text: str, totim: float) -> None:
        self.text = text
        self.totim = totim


class _Budget:
    """A LAK binary budget with one GWF record of two connections of one lake."""

    def __init__(self, _path: Path, q=(_SPT, -_SPT / 2)) -> None:
        self.records = [_Record("GWF", _SPT)]
        self._q = q

    def __enter__(self) -> _Budget:
        return self

    def __exit__(self, *_exc) -> None:
        return None

    def read_record(self, _index: int) -> np.ndarray:
        rec = np.zeros(len(self._q), dtype=[("node", "<i4"), ("q", "<f8")])
        rec["node"] = 1
        rec["q"] = self._q
        return rec


def test_the_applied_exchange_sums_the_connections_and_the_lake_bed_is_the_vertical_subset(
    tmp_path, monkeypatch
) -> None:
    spec = LakeObsSpec.from_mapping(
        {
            "obs_csv": "m.lak.obs.csv",
            "budget_bin": "m.lak.cbc",
            "entries": [
                {
                    "obsname": "lac0_lak_0",
                    "lake_id": "lac0",
                    "quantity": "lak_connection",
                    "iconn": 0,
                    "under_dam": True,
                },
                {
                    "obsname": "lac0_lak_1",
                    "lake_id": "lac0",
                    "quantity": "lak_connection",
                    "iconn": 1,
                    "under_dam": False,
                },
            ],
        }
    )
    (tmp_path / "m.lak.cbc").write_bytes(b"")
    monkeypatch.setattr(lake_extractor, "Mf6CellBudgetReader", _Budget)

    exchange = read_applied_exchange(spec, tmp_path / spec.obs_csv, times=[_SPT])

    assert exchange["lac0"].total == pytest.approx([_SPT / 2])
    assert exchange["lac0"].under_dam == pytest.approx([_SPT])


def test_a_budget_that_holds_another_number_of_connections_gives_no_exchange(
    tmp_path, monkeypatch
) -> None:
    spec = LakeObsSpec.from_mapping(
        {
            "obs_csv": "m.lak.obs.csv",
            "budget_bin": "m.lak.cbc",
            "entries": [
                {
                    "obsname": "lac0_lak_0",
                    "lake_id": "lac0",
                    "quantity": "lak_connection",
                    "iconn": 0,
                    "under_dam": True,
                },
            ],
        }
    )
    (tmp_path / "m.lak.cbc").write_bytes(b"")
    monkeypatch.setattr(lake_extractor, "Mf6CellBudgetReader", _Budget)

    assert read_applied_exchange(spec, tmp_path / spec.obs_csv, times=[_SPT]) == {}
