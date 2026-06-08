"""Parity between the subprocess and api MF6 run modes through HMP extraction.

This exercises the new explicit ``runner`` dispatch end-to-end. One single-lake
DISV simulation is written once, then solved two ways:

* SUBPROCESS leg: ``run_processing`` with ``runner="subprocess"`` shells out to
  the mf6 executable (6.6.3).
* API leg: ``run_processing`` with ``runner="api"`` drives libmf6 (6.7.0) via
  modflowapi, with NO developer callback (the transparent path).

Both legs leave the OC/LAK output files (``.hds`` / ``.cbc`` / ``*.lak.stage`` /
obs CSV) on disk, so the normal ``Modflow6OutputAdapter`` extracts both
identically. We then compare the HMP-extracted lake stage, lake volume, and the
GWF heads across the two engines.

The two engines are DIFFERENT MODFLOW 6 builds (exe 6.6.3 vs libmf6 6.7.0), so
the comparison is tolerance-based, NOT bit-equivalence. The envelopes are
documented in ``tolerances_modflow6_runner_parity.toml`` and tests/TOLERANCES.md
row 43.

A fourth test confirms a developer callback passed through ``runner="api"``
fires and can read the lake stage, while HMP extraction still works.

The optional ``modflowapi`` / ``xmipy`` dependency and the libmf6 shared library
are gated with importorskip / skipif so the suite SKIPS (not fails) when they
are absent.
"""

from __future__ import annotations

import shutil
import sys
import tomllib
from pathlib import Path
from typing import Any

import numpy as np
import pytest

modflowapi = pytest.importorskip("modflowapi")
pytest.importorskip("xmipy")

from hydromodpy.solver.modflow6.api_runner import (  # noqa: E402
    Mf6ApiContext,
    Mf6ApiStep,
)
from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter  # noqa: E402
from hydromodpy.solver.modflow6.extractors.lake import lake_station_id  # noqa: E402
from hydromodpy.solver.modflow6.run import run_processing  # noqa: E402
from hydromodpy.solver.modflow_common import ModflowRunOptions  # noqa: E402
from hydromodpy.solver.modflow_common.binaries import (  # noqa: E402
    ensure_solver_binary,
    locate_solver_binary,
    managed_bin_dir,
)

# Reuse the proven single-lake DISV builder + recording store double.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_modflow6_lake_extractor_e2e import (  # noqa: E402
    _build_single_lake_disv,
    _RecordingStore,
)

_no_lib = locate_solver_binary(managed_bin_dir(), "libmf6") is None

pytestmark = [
    pytest.mark.mf6,
    pytest.mark.binary,
    pytest.mark.allow_subprocess,
    pytest.mark.skipif(_no_lib, reason="libmf6 shared library not in cache"),
]

_TOL = tomllib.loads(
    (Path(__file__).resolve().parent / "tolerances_modflow6_runner_parity.toml").read_text()
)
_MODEL_NAME = "lakd"


class _ShimModel:
    """Minimal model double honouring the run_processing contract.

    Carries the attributes ``run_processing`` reads: a loaded flopy ``sim`` for
    the subprocess leg, ``full_path`` for the api leg, and the api callback /
    lib-path hooks. ``flow_regime`` is None so the steady-init branch is skipped.
    """

    def __init__(self, sim: Any, full_path: Path) -> None:
        self.sim = sim
        self.full_path = str(full_path)
        self.flow = None
        self.flow_regime: str | None = None
        self.last_flow_solve_time_seconds: float | None = None
        self._runtime_dirty_packages: tuple[str, ...] = ()
        self._mf6_api_callback: Any = None
        self._mf6_api_lib_path: Any = None


def _solve(ws: Path, exe: str, runner: str, callback: Any = None) -> None:
    """Run the already-written workspace through run_processing with ``runner``."""
    import flopy

    sim = flopy.mf6.MFSimulation.load(sim_ws=str(ws), exe_name=exe)
    model = _ShimModel(sim, ws)
    model._mf6_api_callback = callback
    options = ModflowRunOptions(write_model=False, run_model=True, verbose=False, runner=runner)
    ok = run_processing(model, options)
    assert ok, f"{runner} run did not converge"


def _extract(ws: Path) -> tuple[dict[str, list[float]], np.ndarray]:
    """Extract lake series + final heads from a solved workspace."""
    import flopy.utils.binaryfile as bf

    store = _RecordingStore()
    Modflow6OutputAdapter().extract("sim", ws, store, model_name=_MODEL_NAME)
    station = lake_station_id("lac0")
    by_variable: dict[str, list[float]] = {}
    for record in store.timeseries:
        assert record["station_id"] == station
        by_variable.setdefault(record["variable"], []).append(float(record["value"]))

    head_file = bf.HeadFile(str(ws / f"{_MODEL_NAME}.hds"))
    heads = np.asarray(head_file.get_data(totim=head_file.get_times()[-1])).ravel()
    return by_variable, heads


@pytest.mark.fast
def test_runner_parity_subprocess_vs_api(tmp_path: Path) -> None:
    """Stage, volume, and heads agree across the two engines via HMP extraction."""
    exe = str(ensure_solver_binary("mf6"))

    base = tmp_path / "base"
    base.mkdir()
    _build_single_lake_disv(base, exe)

    sub_ws = tmp_path / "sub"
    api_ws = tmp_path / "api"
    shutil.copytree(base, sub_ws)
    shutil.copytree(base, api_ws)

    _solve(sub_ws, exe, "subprocess")
    _solve(api_ws, exe, "api")

    sub_vars, sub_heads = _extract(sub_ws)
    api_vars, api_heads = _extract(api_ws)

    # Both engines wrote the standard output filerecords the extractor reads.
    for ws in (sub_ws, api_ws):
        assert (ws / f"{_MODEL_NAME}.hds").is_file()
        assert (ws / f"{_MODEL_NAME}.lak.stage").is_file()

    # Structural parity: the same record keys land under the same station_id.
    assert set(sub_vars) == set(api_vars)
    assert "stage" in sub_vars and "volume" in sub_vars

    stage_tol = _TOL["stage"]
    assert np.allclose(
        api_vars["stage"], sub_vars["stage"], rtol=stage_tol["rtol"], atol=stage_tol["atol"]
    )
    vol_tol = _TOL["volume"]
    assert np.allclose(
        api_vars["volume"], sub_vars["volume"], rtol=vol_tol["rtol"], atol=vol_tol["atol"]
    )
    head_tol = _TOL["heads"]
    assert np.allclose(api_heads, sub_heads, rtol=head_tol["rtol"], atol=head_tol["atol"])


@pytest.mark.fast
def test_default_runner_is_subprocess() -> None:
    """The opt-in default keeps every existing caller on the subprocess path."""
    assert ModflowRunOptions().runner == "subprocess"
    from hydromodpy.solver.modflow6.modflow6_config import Modflow6RuntimeConfig

    assert Modflow6RuntimeConfig().mf6_runner == "subprocess"


@pytest.mark.fast
def test_api_runner_loads_libmf6_and_writes_outputs(tmp_path: Path) -> None:
    """The api mode genuinely loads libmf6 and produces the standard outputs."""
    exe = str(ensure_solver_binary("mf6"))
    ws = tmp_path / "ws"
    ws.mkdir()
    _build_single_lake_disv(ws, exe)

    # Remove the solver outputs the writer never produces, so their presence
    # after the run proves the api solve (not the prior write) created them.
    for name in (f"{_MODEL_NAME}.hds", f"{_MODEL_NAME}.cbc", f"{_MODEL_NAME}.lak.stage"):
        target = ws / name
        if target.exists():
            target.unlink()

    _solve(ws, exe, "api")

    assert (ws / f"{_MODEL_NAME}.hds").is_file()
    assert (ws / f"{_MODEL_NAME}.cbc").is_file()
    assert (ws / f"{_MODEL_NAME}.lak.stage").is_file()

    by_variable, _heads = _extract(ws)
    assert "stage" in by_variable
    assert all(np.isfinite(by_variable["stage"]))


@pytest.mark.fast
def test_api_runner_developer_callback_reads_stage(tmp_path: Path) -> None:
    """A developer callback passed to the api run fires and reads the lake stage."""
    exe = str(ensure_solver_binary("mf6"))
    ws = tmp_path / "ws"
    ws.mkdir()
    _build_single_lake_disv(ws, exe)

    seen: list[float] = []

    def callback(ctx: Mf6ApiContext) -> None:
        if ctx.step is Mf6ApiStep.timestep_end:
            value = float(ctx.read_lake_stage()[0])
            assert np.isfinite(value)
            seen.append(value)

    _solve(ws, exe, "api", callback=callback)

    assert seen, "developer callback never fired at timestep_end"
    # HMP extraction still works after a callback-driven api run.
    by_variable, _heads = _extract(ws)
    assert "stage" in by_variable
    # The callback's last reading matches the extracted final stage.
    assert seen[-1] == pytest.approx(by_variable["stage"][-1], rel=1e-6, abs=1e-3)
