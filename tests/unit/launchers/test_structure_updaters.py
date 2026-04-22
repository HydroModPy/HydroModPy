"""Unit tests for structural binders applied after data loading."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.spatial.geographic.structure_binders import (
    apply_catchment_zones_to_domain,
    apply_geology_to_domain,
)
from hydromodpy.physics.flow.flow import Flow
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.flow.sinks_sources import FlowSinksSourcesConfig
from hydromodpy.physics.flow.structure_binders import (
    apply_oceanic_to_flow,
    apply_simulation_time_to_flow_boundary_conditions,
    apply_simulation_time_to_flow_wells,
)
from hydromodpy.core.time import ResolvedSimulationTimeWindow


class _DummyDomain:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def set_zone(self, zone_id: str, zone_obj: object) -> None:
        self.calls.append((zone_id, zone_obj))


def test_apply_geology_to_domain_sets_declared_zone() -> None:
    domain = _DummyDomain()
    geology = object()

    apply_geology_to_domain(domain=domain, geology=geology)

    assert domain.calls == [("geology", geology)]


def test_apply_geology_to_domain_is_noop_without_geology() -> None:
    domain = _DummyDomain()

    apply_geology_to_domain(domain=domain, geology=None)

    assert domain.calls == []


def test_apply_catchment_zones_to_domain_sets_zone(monkeypatch, tmp_path: Path) -> None:
    domain = _DummyDomain()

    geographic_dir = tmp_path / "geographic"
    geographic_dir.mkdir(parents=True, exist_ok=True)

    watershed_shp = geographic_dir / "watershed.shp"
    watershed_buff_shp = geographic_dir / "watershed_buff.shp"
    watershed_box_buff_shp = geographic_dir / "watershed_box_buff.shp"
    watershed_box_buff_dem = geographic_dir / "watershed_box_buff_dem.tif"
    for path in (
        watershed_shp,
        watershed_buff_shp,
        watershed_box_buff_shp,
        watershed_box_buff_dem,
    ):
        path.write_text("", encoding="utf-8")

    def _fake_build_catchment_zone_codes(**_kwargs):
        return SimpleNamespace(
            zone_codes=np.array(
                [
                    [1, 1, 2],
                    [2, 3, 3],
                ],
                dtype=np.uint8,
            ),
            zone_codes_tif=str(geographic_dir / "catchment_zone_codes.tif"),
        )

    monkeypatch.setattr(
        "hydromodpy.spatial.geographic.structure_binders.build_catchment_zone_codes",
        _fake_build_catchment_zone_codes,
    )

    geographic = SimpleNamespace(
        watershed_shp=str(watershed_shp),
        box_buff=str(watershed_box_buff_shp),
        watershed_box_buff_dem=str(watershed_box_buff_dem),
    )
    apply_catchment_zones_to_domain(domain=domain, geographic=geographic)

    assert len(domain.calls) == 1
    zone_id, zone_obj = domain.calls[0]
    assert zone_id == "catchment"
    assert zone_obj.identifier == "catchment_zones"
    assert zone_obj.shape == (2, 3)
    assert zone_obj.encoded_to_zone == {1: "domain", 2: "buffer", 3: "core"}


def test_apply_catchment_zones_to_domain_sets_uniform_zone(monkeypatch, tmp_path: Path) -> None:
    domain = _DummyDomain()

    geographic_dir = tmp_path / "geographic"
    geographic_dir.mkdir(parents=True, exist_ok=True)

    watershed_shp = geographic_dir / "watershed.shp"
    watershed_box_buff_dem = geographic_dir / "watershed_box_buff_dem.tif"
    watershed_shp.write_text("", encoding="utf-8")
    watershed_box_buff_dem.write_text("", encoding="utf-8")

    def _fake_build_uniform_zone_codes(**_kwargs):
        return SimpleNamespace(
            zone_codes=np.array(
                [
                    [4, 4, 0],
                    [4, 4, 4],
                ],
                dtype=np.uint8,
            ),
            zone_codes_tif=str(geographic_dir / "catchment_zone_codes.tif"),
        )

    monkeypatch.setattr(
        "hydromodpy.spatial.geographic.structure_binders.build_uniform_zone_codes",
        _fake_build_uniform_zone_codes,
    )

    geographic = SimpleNamespace(
        watershed_shp=str(watershed_shp),
        watershed_box_buff_dem=str(watershed_box_buff_dem),
        zone_kind="uniform",
    )
    apply_catchment_zones_to_domain(domain=domain, geographic=geographic)

    assert len(domain.calls) == 1
    zone_id, zone_obj = domain.calls[0]
    assert zone_id == "catchment"
    assert zone_obj.identifier == "catchment_zones"
    assert zone_obj.shape == (2, 3)
    assert zone_obj.encoded_to_zone == {4: "uniform"}


def test_apply_catchment_zones_to_domain_is_noop_with_missing_artifacts() -> None:
    domain = _DummyDomain()
    geographic = SimpleNamespace(
        watershed_shp="missing/watershed.shp",
        box_buff="missing/watershed_box_buff.shp",
        watershed_box_buff_dem="missing/watershed_box_buff_dem.tif",
    )
    apply_catchment_zones_to_domain(domain=domain, geographic=geographic)
    assert domain.calls == []


def test_apply_oceanic_to_flow_updates_ocean_boundary_value() -> None:
    from hydromodpy.data.contracts.load_result import LoadResult
    from hydromodpy.data.contracts.timeseries import PointRecord

    flow = SimpleNamespace(boundary_conditions={"ocean": SimpleNamespace(value=None)})
    msl_data = pd.DataFrame({"datetime": [pd.Timestamp.now()], "value": [7.5]})
    oceanic = LoadResult(
        points=[
            PointRecord(
                station_id="constant",
                variable="mean_sea_level",
                source="constant",
                unit="m",
                frequency="constant",
                data=msl_data,
                date_start=pd.Timestamp.now().to_pydatetime(),
                date_end=pd.Timestamp.now().to_pydatetime(),
                is_constant=True,
            )
        ]
    )

    apply_oceanic_to_flow(flow=flow, oceanic=oceanic)

    assert flow.boundary_conditions["ocean"].value == 7.5


def test_apply_oceanic_to_flow_fallback_to_series_mean() -> None:
    from hydromodpy.data.contracts.load_result import LoadResult
    from hydromodpy.data.contracts.timeseries import PointRecord

    flow = SimpleNamespace(boundary_conditions={"ocean": SimpleNamespace(value=None)})
    ts_data = pd.DataFrame(
        {
            "datetime": pd.date_range("2003-01-01", periods=3, freq="h"),
            "value": [1.0, 2.0, 3.0],
        }
    )
    oceanic = LoadResult(
        points=[
            PointRecord(
                station_id="shom_001",
                variable="sea_level",
                source="shom",
                unit="m",
                frequency="H",
                data=ts_data,
                date_start=ts_data["datetime"].min().to_pydatetime(),
                date_end=ts_data["datetime"].max().to_pydatetime(),
            )
        ]
    )

    apply_oceanic_to_flow(flow=flow, oceanic=oceanic)

    assert flow.boundary_conditions["ocean"].value == pytest.approx(2.0)


def test_apply_oceanic_to_flow_is_noop_without_ocean_boundary() -> None:
    from hydromodpy.data.contracts.load_result import LoadResult

    flow = SimpleNamespace(boundary_conditions={})
    oceanic = LoadResult(points=[])

    apply_oceanic_to_flow(flow=flow, oceanic=oceanic)

    assert flow.boundary_conditions == {}


class _DummyRechargeConfig:
    first_clim = "mean"
    units = "m/s"
    negative_to_evt = True


class _DummyFlow:
    def __init__(self) -> None:
        self.sinks_sources = {"recharge": _DummyRechargeConfig()}
        self.bound_recharge = None

    def set_recharge(self, recharge) -> None:
        self.bound_recharge = recharge


def test_apply_simulation_time_to_flow_wells_binds_constant_forcing() -> None:
    cfg = FlowConfig(
        sinks_sources=FlowSinksSourcesConfig(
            wells={
                "W1": {
                    "cell": [0, 0, 0],
                    "units": "m3/day",
                    "forcing": {"mode": "constant", "value": -86400.0},
                }
            }
        )
    )
    flow = Flow(cfg)
    window = ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2003-01-01"),
        end=pd.Timestamp("2003-03-31"),
        step_value=1,
        step_unit="month",
        coverage_policy="error",
    )

    apply_simulation_time_to_flow_wells(flow=flow, simulation_window=window)

    well = flow.sinks_sources["wells"]["W1"]
    assert well.units == "m3/s"
    assert well.flux == pytest.approx([-1.0, -1.0, -1.0])


def test_apply_simulation_time_to_flow_wells_binds_csv_forcing(tmp_path: Path) -> None:
    csv_path = tmp_path / "well.csv"
    csv_path.write_text(
        "\n".join(
            [
                "date,rate",
                "2003-01-01,-86400.0",
                "2003-01-17,-86400.0",
                "2003-02-03,-43200.0",
                "2003-02-19,-43200.0",
                "2003-03-05,0.0",
                "2003-03-22,0.0",
            ]
        ),
        encoding="utf-8",
    )
    cfg = FlowConfig(
        sinks_sources=FlowSinksSourcesConfig(
            wells={
                "W1": {
                    "cell": [0, 0, 0],
                    "units": "m3/day",
                    "forcing": {
                        "mode": "csv",
                        "path_file": csv_path,
                        "date_column": "date",
                        "value_column": "rate",
                    },
                }
            }
        )
    )
    flow = Flow(cfg)
    window = ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2003-01-01"),
        end=pd.Timestamp("2003-03-31"),
        step_value=1,
        step_unit="month",
        coverage_policy="error",
    )

    apply_simulation_time_to_flow_wells(flow=flow, simulation_window=window)

    well = flow.sinks_sources["wells"]["W1"]
    assert well.units == "m3/s"
    assert well.flux == pytest.approx([-1.0, -0.5, 0.0])


def test_apply_simulation_time_to_flow_boundary_conditions_binds_constant_forcing() -> None:
    cfg = FlowConfig(
        bc={
            "dirichlet": {
                "west_side": {
                    "units": "cm",
                    "forcing": {"mode": "constant", "value": 12.0},
                }
            }
        },
        active_bc=["west_side"],
    )
    flow = Flow(cfg)
    window = ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2003-01-01"),
        end=pd.Timestamp("2003-03-31"),
        step_value=1,
        step_unit="month",
        coverage_policy="error",
    )

    apply_simulation_time_to_flow_boundary_conditions(flow=flow, simulation_window=window)

    west_side = flow.boundary_conditions["west_side"]
    assert west_side.forcing is None
    assert west_side.units == "m"
    assert west_side.value == pytest.approx([0.12, 0.12, 0.12])


def test_apply_simulation_time_to_flow_boundary_conditions_binds_csv_forcing(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "boundary.csv"
    csv_path.write_text(
        "\n".join(
            [
                "date,head",
                "2003-01-01,10.0",
                "2003-01-17,10.0",
                "2003-02-03,11.0",
                "2003-02-19,11.0",
                "2003-03-05,12.0",
                "2003-03-22,12.0",
            ]
        ),
        encoding="utf-8",
    )
    cfg = FlowConfig(
        bc={
            "dirichlet": {
                "east_side": {
                    "forcing": {
                        "mode": "csv",
                        "path_file": csv_path,
                        "date_column": "date",
                        "value_column": "head",
                    }
                }
            }
        },
        active_bc=["east_side"],
    )
    flow = Flow(cfg)
    window = ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2003-01-01"),
        end=pd.Timestamp("2003-03-31"),
        step_value=1,
        step_unit="month",
        coverage_policy="error",
    )

    apply_simulation_time_to_flow_boundary_conditions(flow=flow, simulation_window=window)

    east_side = flow.boundary_conditions["east_side"]
    assert east_side.forcing is None
    assert east_side.value == pytest.approx([10.0, 11.0, 12.0])
