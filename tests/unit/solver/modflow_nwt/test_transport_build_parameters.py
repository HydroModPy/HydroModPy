"""The MT3DMS and MODPATH transport adapters pass validated parameters to their engine."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.model.transport.transport_config import (
    ConcentrationTransportParametersConfig,
    ModpathParametersConfig,
)
from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.solver.modflow_nwt.modpath import modpath
from hydromodpy.solver.modflow_nwt.mt3dms import mt3dms
from tests.unit.solver.modflow_common.solver_runs import solved_run


def _upstream(tmp_path: Path) -> SolverRun:
    flow_model = SimpleNamespace(
        model_name="island",
        full_path=str(tmp_path / "island"),
        solver_mesh=SimpleNamespace(nrow=10, ncol=10),
    )
    return solved_run(tmp_path / "island", solver_model=flow_model)


def _model() -> Any:
    return SimpleNamespace(geometry=SimpleNamespace(domain="DOMAIN", geographic="GEOGRAPHIC"))


def test_mt3dms_build_forwards_non_default_parameters(tmp_path: Path, monkeypatch) -> None:
    recorded: dict[str, Any] = {}

    class _FakeMt3dms:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            recorded["params"] = kwargs.get("params")
            self.model_folder = kwargs.get("model_folder")
            self.model_name = kwargs.get("model_name")
            self.full_path = str(tmp_path / "island")

        def pre_processing(self) -> None:
            recorded["pre_processed"] = True

    monkeypatch.setattr(mt3dms, "Mt3dms", _FakeMt3dms)

    adapter = mt3dms.Mt3dmsTransportAdapter()
    options = ConcentrationTransportParametersConfig(porosity=0.15, disp_long=12.0)
    slot = RunSlot(tmp_path, "island_mt")
    followed = _upstream(tmp_path)

    adapter.build(_model(), options, slot, (followed,))

    params = recorded.get("params")
    assert isinstance(params, dict)
    assert params["porosity"] == 0.15
    assert params["disp_long"] == 12.0


def test_modpath_build_forwards_non_default_parameters_and_detects_seepage_clip(
    tmp_path: Path, monkeypatch
) -> None:
    recorded: dict[str, Any] = {}
    seepage_called = []

    class _FakeModpath:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            recorded["params"] = kwargs.get("params")
            self.model_folder = kwargs.get("model_folder")
            self.model_name = kwargs.get("model_name")
            self.full_path = str(tmp_path / "island")

        def pre_processing(self) -> None:
            recorded["pre_processed"] = True

    monkeypatch.setattr(modpath, "Modpath", _FakeModpath)
    monkeypatch.setattr(
        modpath, "_write_seepage_clip_raster", lambda flow_run: seepage_called.append(flow_run)
    )

    adapter = modpath.ModpathTransportAdapter()
    options = ModpathParametersConfig(zone_partic="seepage_clip", track_dir="backward")
    slot = RunSlot(tmp_path, "island_mp")
    followed = _upstream(tmp_path)

    adapter.build(_model(), options, slot, (followed,))

    params = recorded.get("params")
    assert isinstance(params, dict)
    assert params["track_dir"] == "backward"
    assert params["zone_partic"] == "seepage_clip"
    assert len(seepage_called) == 1


def test_the_seepage_clip_raster_reads_the_heads_under_the_nwt_name(tmp_path: Path) -> None:
    """A run name with spaces names its NWT files with underscores, and so its heads."""
    flow_dir = tmp_path / "Example 12 run"
    flow_model = SimpleNamespace(
        full_path=str(flow_dir), dem_watershed_path=str(tmp_path / "dem.tif")
    )
    followed = SolverRun(
        slot=RunSlot(tmp_path, "Example 12 run"),
        model=None,
        options=None,
        solver_model=flow_model,
        output_dir=flow_dir,
        written=True,
        solved=True,
    )

    with pytest.raises(SolverInputError) as raised:
        modpath._write_seepage_clip_raster(followed)

    assert str(flow_dir / "Example_12_run.hds") in str(raised.value)
