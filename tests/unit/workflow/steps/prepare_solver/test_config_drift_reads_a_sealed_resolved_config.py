"""A run sealed by 2.0.0 drifts only where the computation drifts, not where a table moved.

The frozen run ``demo`` ran MODFLOW-NWT and sealed ``[modflow6]``, ``[modflownwt]``,
``[flow.runtime]`` and ``backend = {kind = "modflow_nwt"}``. Those tables now live under
``[solver]``. ``config_drift`` reads the sealed document under today's names, and a
table of a solver that did not run counts for nothing, so a replay sees the one key
the base saw. The run is copied out of the frozen corpus, which stays as it is.
"""

from __future__ import annotations

import shutil
import tomllib
import warnings
from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.workflow.steps.prepare_solver.resolved import config_drift

FROZEN_DEMO = (
    Path(__file__).resolve().parents[5]
    / "tests/regression/frozen_runs/v2.0.0/current/projects/example/runs/demo"
)

DRIFT_AT_THE_BASE = ("flow.sinks_sources.recharge.factor",)
"""What ``config_drift`` gave on this copy before the tables moved, measured once.

The key came with 2.0.0 after this run was sealed, and its default reproduces the
old computation. It is not the subject here.
"""

_COPIED = ("config.toml", "config.resolved.toml")


@pytest.fixture
def demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    run = tmp_path / "runs" / "demo"
    run.mkdir(parents=True)
    for name in _COPIED:
        shutil.copyfile(FROZEN_DEMO / name, run / name)
    monkeypatch.chdir(tmp_path)
    return run


def _drift_keys(run: Path) -> tuple[str, ...]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        snapshot = tomllib.loads((run / "config.toml").read_text(encoding="utf-8"))
        cfg = HydroModPyConfig.from_snapshot(snapshot)
        drift = config_drift(cfg, run, project_root=Path(cfg.workspace.project_root))
    assert drift is not None
    return tuple(item.key for item in drift)


def test_the_sealed_document_writes_the_tables_that_moved(demo: Path) -> None:
    sealed = tomllib.loads((demo / "config.resolved.toml").read_text(encoding="utf-8"))

    assert {"modflow6", "modflownwt"} <= set(sealed)
    assert "runtime" in sealed["flow"]
    assert sealed["solver"]["backend"] == {"kind": "modflow_nwt"}


def test_a_replay_drifts_on_the_keys_the_base_saw_and_no_other(demo: Path) -> None:
    assert _drift_keys(demo) == DRIFT_AT_THE_BASE


def test_the_settings_of_the_solver_that_ran_still_drift(demo: Path) -> None:
    resolved = demo / "config.resolved.toml"
    text = resolved.read_text(encoding="utf-8")
    resolved.write_text(text.replace("hdry = -100.0", "hdry = -77.0"), encoding="utf-8")
    assert text != resolved.read_text(encoding="utf-8"), "the sealed hdry of NWT is -100.0"

    assert "solver.modflow_nwt.runtime.upw.hdry" in _drift_keys(demo)
