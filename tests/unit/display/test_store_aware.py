"""Tests for store-aware data loading in display suites and posthoc."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from hydromodpy.analysis.display.display_config import DisplayOptions, DisplaySectionOptions
from hydromodpy.analysis.display.suites import (
    _CATCHMENT_STATION,
    _FLOW_TIMESERIES_VARIABLES,
    _load_flow_timeseries_from_store,
)
from hydromodpy.analysis.display.common import (
    load_field_dict_from_store as _load_field_dict_from_store,
)
from hydromodpy.results.catalog import SimulationCatalog


@pytest.fixture
def catalog(tmp_path):
    c = SimulationCatalog(tmp_path / "workspace")
    yield c
    c.close()


class TestLoadFlowTimeseriesFromStore:
    def test_returns_dataframe_with_stored_variables(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflownwt")

        idx = pd.date_range("2020-01-01", periods=5, freq="ME")
        catalog.write_timeseries(sid, _CATCHMENT_STATION, "recharge_budget", pd.Series(np.arange(5.0), index=idx))
        catalog.write_timeseries(sid, _CATCHMENT_STATION, "outflow_drain", pd.Series(np.arange(5.0) * 2, index=idx))

        df = _load_flow_timeseries_from_store(catalog, sid)
        assert df is not None
        assert "recharge_budget" in df.columns
        assert "outflow_drain" in df.columns
        assert len(df) == 5

    def test_returns_none_when_no_data(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflownwt")
        assert _load_flow_timeseries_from_store(catalog, sid) is None

    def test_partial_variables(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflownwt")

        idx = pd.date_range("2020-01-01", periods=3, freq="ME")
        catalog.write_timeseries(sid, _CATCHMENT_STATION, "watertable_depth", pd.Series([4.1, 4.2, 4.3], index=idx))

        df = _load_flow_timeseries_from_store(catalog, sid)
        assert df is not None
        assert list(df.columns) == ["watertable_depth"]
        assert len(df) == 3

    def test_all_flow_variables(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflownwt")

        idx = pd.date_range("2020-01-01", periods=4, freq="ME")
        for var in _FLOW_TIMESERIES_VARIABLES:
            catalog.write_timeseries(sid, _CATCHMENT_STATION, var, pd.Series(np.ones(4), index=idx))

        df = _load_flow_timeseries_from_store(catalog, sid)
        assert df is not None
        assert set(df.columns) == set(_FLOW_TIMESERIES_VARIABLES)


class TestLoadFieldDictFromStore:
    def test_loads_field_as_dict(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(
            sid, project="test", solver="modflownwt",
            n_cells=10, n_layers=1, n_timesteps=3,
        )

        for t in range(3):
            values = np.random.rand(1, 10)
            catalog.write_field(sid, "head", t, values, n_timesteps=3)

        result = _load_field_dict_from_store(catalog, sid, "head")
        assert result is not None
        assert len(result) == 3
        assert all(isinstance(v, np.ndarray) for v in result.values())

    def test_returns_none_for_missing_variable(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflownwt", n_cells=10, n_layers=1, n_timesteps=1)
        result = _load_field_dict_from_store(catalog, sid, "nonexistent")
        assert result is None

    def test_returns_none_for_missing_sim(self, catalog):
        result = _load_field_dict_from_store(catalog, "no_such_sim", "head")
        assert result is None


class TestPlotFlowSuiteWithStore:
    def test_falls_back_to_csv(self, monkeypatch):
        """When store returns no data, suite completes without error."""
        flow_model = SimpleNamespace(
            model_name="flow_main",
            dem_watershed_path=Path("solver_grid_template.tif"),
        )
        geographic = SimpleNamespace(
            watershed_dem=Path("native_dem.tif"),
            watershed_shp=Path("watershed.shp"),
        )
        workspace = SimpleNamespace(simulations_folder=Path("simulations"), project_root=Path("."))
        hydrography = SimpleNamespace(streams=Path("streams.shp"))

        class _Result:
            setup = SimpleNamespace(geographic=geographic, workspace=workspace)
            loaded_data = SimpleNamespace(
                hydrometry=None, hydrography=hydrography,
                recharge=None, piezometry=None,
            )
            cfg = SimpleNamespace(workspace=SimpleNamespace(data_path=Path(".")))

            @staticmethod
            def get_model_for_solver(name):
                return flow_model if name == "modflownwt" else None

        result = _Result()

        csv_called = []
        monkeypatch.setattr(
            "hydromodpy.analysis.display.suites._load_flow_timeseries",
            lambda r: (csv_called.append(True), pd.DataFrame({"dummy": [0.0]}))[1],
        )
        monkeypatch.setattr(
            "hydromodpy.analysis.display.suites._load_observed_streamflow",
            lambda r: None,
        )
        monkeypatch.setattr(
            "hydromodpy.analysis.display.suites._extract_cross_section_data",
            lambda dem_path, *, store=None, sim_id=None, x_index=None: (
                np.array([0.0]), np.array([0.0]), np.array([0.0]),
            ),
        )
        monkeypatch.setattr("hydromodpy.analysis.display.suites.plot_cross_section", lambda **kw: None)

        def _raise_key_error(*args, **kwargs):
            raise KeyError("no data")

        mock_store = SimpleNamespace(query_timeseries=_raise_key_error)

        from hydromodpy.analysis.display.suites import plot_flow_suite

        options = DisplayOptions(
            enabled=True, show=True, save=False,
            flow=DisplaySectionOptions(
                enabled=True,
                flags={"cross_section": True, "streamflow": False, "piezometry": False},
            ),
        )
        plot_flow_suite(result, options, store=mock_store, sim_id="test")
        # No CSV fallback — suite completes with cross_section only.

    def test_uses_store_when_available(self, monkeypatch, catalog):
        """When store has data, CSV loader is not called."""
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflownwt")

        idx = pd.date_range("2020-01-01", periods=5, freq="ME")
        for var in ["recharge", "outflow_drain", "runoff", "watertable_depth"]:
            catalog.write_timeseries(sid, _CATCHMENT_STATION, var, pd.Series(np.ones(5), index=idx))

        flow_model = SimpleNamespace(
            model_name="flow_main",
            dem_watershed_path=Path("solver_grid_template.tif"),
        )
        geographic = SimpleNamespace(
            watershed_dem=Path("native_dem.tif"),
            watershed_shp=Path("watershed.shp"),
        )
        workspace = SimpleNamespace(simulations_folder=Path("simulations"), project_root=Path("."))

        class _Result:
            setup = SimpleNamespace(geographic=geographic, workspace=workspace)
            loaded_data = SimpleNamespace(
                hydrometry=None, hydrography=None,
                recharge=None, piezometry=None,
            )
            cfg = SimpleNamespace(workspace=SimpleNamespace(data_path=Path(".")))

            @staticmethod
            def get_model_for_solver(name):
                return flow_model if name == "modflownwt" else None

        result = _Result()

        csv_called = []
        monkeypatch.setattr(
            "hydromodpy.analysis.display.suites._load_flow_timeseries",
            lambda r: (csv_called.append(True), pd.DataFrame({"dummy": [0.0]}))[1],
        )
        monkeypatch.setattr(
            "hydromodpy.analysis.display.suites._load_observed_streamflow",
            lambda r: None,
        )
        monkeypatch.setattr(
            "hydromodpy.analysis.display.suites._extract_cross_section_data",
            lambda dem_path, *, store=None, sim_id=None, x_index=None: (
                np.array([0.0]), np.array([0.0]), np.array([0.0]),
            ),
        )
        monkeypatch.setattr("hydromodpy.analysis.display.suites.plot_cross_section", lambda **kw: None)

        from hydromodpy.analysis.display.suites import plot_flow_suite

        options = DisplayOptions(
            enabled=True, show=True, save=False,
            flow=DisplaySectionOptions(
                enabled=True,
                flags={"cross_section": True, "streamflow": False, "piezometry": False},
            ),
        )
        plot_flow_suite(result, options, store=catalog, sim_id=sid)
        assert not csv_called, "should NOT have called CSV loader when store has data"


class TestPosthocContextFromResultStore:
    def test_from_result_store_discovers_runs(self, catalog, tmp_path):
        from hydromodpy.analysis.display.posthoc import PosthocContext

        project = tmp_path / "project"
        project.mkdir(parents=True, exist_ok=True)

        # Create geographic directory
        geo_dir = project / ".solver_scratch/_preprocessing" / "geographic"
        geo_dir.mkdir(parents=True)

        # Create simulation directories
        sims_dir = project / "results_simulations"
        for name in ["run_a", "run_b"]:
            pp = sims_dir / name / "_postprocess"
            pp.mkdir(parents=True)

        # Register simulations in catalog
        sid_a, sid_b = str(uuid4()), str(uuid4())
        catalog.register_simulation(sid_a, project="test", solver="modflownwt", name="run_a")
        catalog.finalize(sid_a)
        catalog.register_simulation(sid_b, project="test", solver="modflownwt", name="run_b")
        catalog.finalize(sid_b)

        ctx = PosthocContext.from_result_store(project, catalog)
        assert len(ctx.runs) == 2
        run_ids = {r.run_id for r in ctx.runs}
        assert "run_a" in run_ids
        assert "run_b" in run_ids

    def test_from_result_store_falls_back_to_filesystem(self, catalog, tmp_path):
        from hydromodpy.analysis.display.posthoc import PosthocContext

        project = tmp_path / "project_empty"
        project.mkdir(parents=True)

        geo_dir = project / ".solver_scratch/_preprocessing" / "geographic"
        geo_dir.mkdir(parents=True)

        sims_dir = project / "results_simulations"
        pp = sims_dir / "fs_run" / "_postprocess"
        pp.mkdir(parents=True)

        # No simulations in catalog
        ctx = PosthocContext.from_result_store(project, catalog)
        assert len(ctx.runs) == 1
        assert ctx.runs[0].run_id == "fs_run"
