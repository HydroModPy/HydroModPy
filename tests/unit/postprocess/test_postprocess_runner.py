"""Unit tests for launcher-managed postprocess dispatch."""

from types import SimpleNamespace

import hydromodpy.postprocess.netcdf as netcdf_postprocess

from hydromodpy.postprocess.postprocess_config import PostprocessConfig
from hydromodpy.postprocess.runner import PostprocessRunner


def test_postprocess_runner_is_disabled_by_default() -> None:
    runner = PostprocessRunner(PostprocessConfig())
    called: list[str] = []
    runner._after_flow = lambda state: called.append("flow")  # type: ignore[method-assign]
    runner._after_transport = lambda state: called.append("transport")  # type: ignore[method-assign]

    runner.after_process("flow", SimpleNamespace())
    runner.after_process("transport", SimpleNamespace())

    assert called == []


def test_postprocess_runner_dispatches_flow_and_transport() -> None:
    runner = PostprocessRunner(PostprocessConfig(enabled=True))
    called: list[str] = []
    runner._after_flow = lambda state: called.append("flow")  # type: ignore[method-assign]
    runner._after_transport = lambda state: called.append("transport")  # type: ignore[method-assign]

    runner.after_process(" flow ", SimpleNamespace())
    runner.after_process("transport", SimpleNamespace())

    assert called == ["flow", "transport"]


def test_postprocess_runner_ignores_unknown_process_type() -> None:
    runner = PostprocessRunner(PostprocessConfig(enabled=True))
    called: list[str] = []
    runner._after_flow = lambda state: called.append("flow")  # type: ignore[method-assign]
    runner._after_transport = lambda state: called.append("transport")  # type: ignore[method-assign]

    runner.after_process("particles", SimpleNamespace())

    assert called == []


def test_postprocess_runner_calls_flow_netcdf_when_enabled(monkeypatch) -> None:
    cfg = PostprocessConfig.model_validate(
        {
            "enabled": True,
            "flow": {
                "timeseries": {"enabled": False},
                "netcdf": {"enabled": True, "datetime_format": False},
                "matching_streams": False,
                "display": False,
            },
            "transport": {"enabled": False},
        }
    )
    runner = PostprocessRunner(cfg)

    captured: list[dict] = []

    class _FakeFlowNetcdf:
        def __init__(self, geographic, *, model_modflow, datetime_format):
            captured.append(
                {
                    "geographic": geographic,
                    "model_modflow": model_modflow,
                    "datetime_format": datetime_format,
                }
            )

    monkeypatch.setattr(netcdf_postprocess, "FlowNetcdfPostprocess", _FakeFlowNetcdf)

    flow_model = SimpleNamespace(model_name="flow")

    class _State:
        setup = SimpleNamespace(geographic=SimpleNamespace())
        data = SimpleNamespace(climatic=None, hydrography=None)
        cfg = SimpleNamespace(display=SimpleNamespace(to_runtime_options=lambda: SimpleNamespace()))

        @staticmethod
        def get_model_for_solver(name: str):
            if name == "modflownwt":
                return flow_model
            return None

    runner.after_process("flow", _State())

    assert len(captured) == 1
    assert captured[0]["model_modflow"] is flow_model
    assert captured[0]["datetime_format"] is False


def test_postprocess_runner_calls_transport_netcdf_when_enabled(monkeypatch) -> None:
    cfg = PostprocessConfig.model_validate(
        {
            "enabled": True,
            "flow": {"enabled": False},
            "transport": {
                "enabled": True,
                "timeseries": {"enabled": False},
                "netcdf": {
                    "enabled": True,
                    "datetime_format": False,
                    "residence_times": True,
                    "concentration_seepage": False,
                    "mass_accumulated": True,
                },
                "display_particles": False,
                "display_transport": False,
            },
        }
    )
    runner = PostprocessRunner(cfg)

    captured: list[dict] = []

    class _FakeTransportNetcdf:
        def __init__(
            self,
            geographic,
            *,
            model_modflow,
            model_modpath,
            model_mt3dms,
            datetime_format,
            residence_times,
            concentration_seepage,
            mass_accumulated,
        ):
            captured.append(
                {
                    "geographic": geographic,
                    "model_modflow": model_modflow,
                    "model_modpath": model_modpath,
                    "model_mt3dms": model_mt3dms,
                    "datetime_format": datetime_format,
                    "residence_times": residence_times,
                    "concentration_seepage": concentration_seepage,
                    "mass_accumulated": mass_accumulated,
                }
            )

    monkeypatch.setattr(netcdf_postprocess, "TransportNetcdfPostprocess", _FakeTransportNetcdf)

    flow_model = SimpleNamespace(model_name="flow")
    particle_model = SimpleNamespace(name="particles")
    transport_model = SimpleNamespace(name="transport")

    class _State:
        setup = SimpleNamespace(geographic=SimpleNamespace())
        data = SimpleNamespace(climatic=None, hydrography=None)
        cfg = SimpleNamespace(display=SimpleNamespace(to_runtime_options=lambda: SimpleNamespace()))

        @staticmethod
        def get_model_for_solver(name: str):
            if name == "modflownwt":
                return flow_model
            if name == "modpath":
                return particle_model
            if name == "mt3dms":
                return transport_model
            return None

    runner.after_process("transport", _State())

    assert len(captured) == 1
    assert captured[0]["model_modflow"] is flow_model
    assert captured[0]["model_modpath"] is particle_model
    assert captured[0]["model_mt3dms"] is transport_model
    assert captured[0]["datetime_format"] is False
    assert captured[0]["residence_times"] is True
    assert captured[0]["concentration_seepage"] is False
    assert captured[0]["mass_accumulated"] is True
