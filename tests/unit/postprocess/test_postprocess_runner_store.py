"""Tests for PostprocessRunner integration with ResultStore."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from hydromodpy.analysis.display.suites import _CATCHMENT_STATION
from hydromodpy.analysis.postprocess.postprocess_config import PostprocessConfig
from hydromodpy.analysis.postprocess.runner import PostprocessRunner
from hydromodpy.simulation.results.store import ResultStore


@pytest.fixture
def store(tmp_path):
    project = tmp_path / "project"
    s = ResultStore(project)
    yield s
    s.close()


class TestPostprocessRunnerStore:
    def test_write_timeseries_to_store(self, store):
        sid = str(uuid4())
        store.register_simulation(sid, solver="modflownwt")

        runner = PostprocessRunner(
            PostprocessConfig(enabled=True),
            store=store,
            sim_id=sid,
        )
        idx = pd.date_range("2020-01-01", periods=5, freq="ME")
        df = pd.DataFrame({
            "recharge": np.arange(5, dtype=float),
            "outflow_drain": np.arange(5, dtype=float) * 2,
            "watertable_depth": np.linspace(4.0, 3.0, 5),
        }, index=idx)

        runner._write_timeseries_to_store(df)

        ts = store.query_timeseries(sid, _CATCHMENT_STATION, "recharge")
        assert len(ts) == 5
        np.testing.assert_array_almost_equal(ts.values, np.arange(5, dtype=float))

        ts = store.query_timeseries(sid, _CATCHMENT_STATION, "outflow_drain")
        np.testing.assert_array_almost_equal(ts.values, np.arange(5, dtype=float) * 2)

    def test_write_skips_empty_columns(self, store):
        sid = str(uuid4())
        store.register_simulation(sid, solver="modflownwt")

        runner = PostprocessRunner(store=store, sim_id=sid)
        idx = pd.date_range("2020-01-01", periods=3, freq="ME")
        df = pd.DataFrame({
            "recharge": [1.0, 2.0, 3.0],
            "empty_col": [np.nan, np.nan, np.nan],
        }, index=idx)

        runner._write_timeseries_to_store(df)

        ts = store.query_timeseries(sid, _CATCHMENT_STATION, "recharge")
        assert len(ts) == 3

        with pytest.raises(KeyError):
            store.query_timeseries(sid, _CATCHMENT_STATION, "empty_col")

    def test_write_noop_without_store(self):
        runner = PostprocessRunner()
        idx = pd.date_range("2020-01-01", periods=3, freq="ME")
        df = pd.DataFrame({"recharge": [1.0, 2.0, 3.0]}, index=idx)
        runner._write_timeseries_to_store(df)  # should not raise

    def test_after_flow_writes_to_store(self, monkeypatch, store):
        sid = str(uuid4())
        store.register_simulation(sid, solver="modflownwt")

        cfg = PostprocessConfig.model_validate({
            "enabled": True,
            "flow": {
                "timeseries": {"enabled": True},
                "netcdf": {"enabled": False},
                "matching_streams": False,
                "display": False,
            },
            "transport": {"enabled": False},
        })
        runner = PostprocessRunner(cfg, store=store, sim_id=sid)

        idx = pd.date_range("2020-01-01", periods=10, freq="ME")
        fake_mfdata = pd.DataFrame({
            "recharge": np.arange(10, dtype=float),
            "outflow_drain": np.arange(10, dtype=float) * 0.5,
            "watertable_depth": np.linspace(5.0, 3.0, 10),
        }, index=idx)

        class _FakeTimeseriesPostprocess:
            def __init__(self, *args, **kwargs):
                self.mfdata = fake_mfdata

        monkeypatch.setattr(
            "hydromodpy.analysis.postprocess.timeseries.FlowTimeseriesPostprocess",
            _FakeTimeseriesPostprocess,
        )

        flow_model = SimpleNamespace(model_name="flow_main")

        class _State:
            setup = SimpleNamespace(geographic=SimpleNamespace())
            loaded_data = SimpleNamespace(hydrography=None, runoff=None)
            cfg = SimpleNamespace(
                display=SimpleNamespace(to_runtime_options=lambda: SimpleNamespace()),
            )

            @staticmethod
            def get_model_for_solver(name):
                if name == "modflownwt":
                    return flow_model
                return None

        runner.after_process("flow", _State())

        ts = store.query_timeseries(sid, _CATCHMENT_STATION, "recharge")
        assert len(ts) == 10
        np.testing.assert_array_almost_equal(ts.values, np.arange(10, dtype=float))

    def test_display_receives_store(self, monkeypatch, store):
        sid = str(uuid4())
        store.register_simulation(sid, solver="modflownwt")

        cfg = PostprocessConfig.model_validate({
            "enabled": True,
            "flow": {
                "timeseries": {"enabled": False},
                "netcdf": {"enabled": False},
                "matching_streams": False,
                "display": True,
            },
        })
        runner = PostprocessRunner(cfg, store=store, sim_id=sid)

        captured_kwargs = {}

        def _mock_plot(state, options, **kwargs):
            captured_kwargs.update(kwargs)

        monkeypatch.setattr(
            "hydromodpy.analysis.postprocess.runner.plot_flow_suite",
            _mock_plot,
        )

        flow_model = SimpleNamespace(model_name="flow_main")
        display_options = SimpleNamespace()

        class _State:
            setup = SimpleNamespace(geographic=SimpleNamespace())
            loaded_data = SimpleNamespace(hydrography=None, runoff=None)
            cfg = SimpleNamespace(
                display=SimpleNamespace(to_runtime_options=lambda: display_options),
            )

            @staticmethod
            def get_model_for_solver(name):
                if name == "modflownwt":
                    return flow_model
                return None

        runner.after_process("flow", _State())

        assert captured_kwargs.get("store") is store
        assert captured_kwargs.get("sim_id") == sid
