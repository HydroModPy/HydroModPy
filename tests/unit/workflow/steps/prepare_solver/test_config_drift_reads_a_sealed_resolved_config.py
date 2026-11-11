"""A run sealed by 2.0.0 drifts only where the computation drifts, not where a table moved.

The frozen run ``demo`` ran MODFLOW-NWT and sealed ``[modflow6]``, ``[modflownwt]``,
``[flow.runtime]`` and ``backend = {kind = "modflow_nwt"}``. Those tables now live under
``[solver]``. ``config_drift`` reads the sealed document under today's names, and a
table of a solver that did not run counts for nothing. A key the sealed file does not
write, at its default today, is no drift either: it is listed apart. The run is copied
out of the frozen corpus, which stays as it is.
"""

from __future__ import annotations

import shutil
import tomllib
import warnings
from pathlib import Path

import pytest

from hydromodpy.config import HydroModPyConfig
from hydromodpy.workflow.steps.prepare_solver.resolved import compare_with_sealed, config_drift

FROZEN_DEMO = (
    Path(__file__).resolve().parents[5]
    / "tests/regression/frozen_runs/v2.0.0/current/projects/example/runs/demo"
)
FROZEN_CALAGE = (
    Path(__file__).resolve().parents[5]
    / "tests/regression/frozen_runs/v2.0.0/current/projects/example/runs/calage"
)

NEW_AT_DEFAULT = {
    "flow.sinks_sources.recharge.factor": 1.0,
    "simulation.results.keep_face_flows": False,
    "simulation.time.window": "all",
    "workspace.products_cap_mb": 5000,
}
"""What these copies do not write and a replay holds at its default, measured once.

The recharge factor came with 2.0.0 after these runs were sealed by its release
candidate, and its default reproduces the old computation. ``config_drift`` gave it as
the one drift before a key absent from the sealed file counted for none. The cap of the
product store came later and moves no number, and so did ``keep_face_flows``, whose default
writes no face flow. A file of 2.0 writes no window key, and
the default of ``simulation.time.window`` plays the run in one piece. The default of
``window_length`` is ``None``, which is not counted.
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


@pytest.fixture
def calage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    run = tmp_path / "runs" / "calage"
    run.mkdir(parents=True)
    for name in _COPIED:
        shutil.copyfile(FROZEN_CALAGE / name, run / name)
    monkeypatch.chdir(tmp_path)
    return run


def _config_of(run: Path) -> HydroModPyConfig:
    snapshot = tomllib.loads((run / "config.toml").read_text(encoding="utf-8"))
    return HydroModPyConfig.from_snapshot(snapshot)


def _drift_keys(run: Path) -> tuple[str, ...]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cfg = _config_of(run)
        drift = config_drift(cfg, run, project_root=Path(cfg.workspace.project_root))
    assert drift is not None
    return tuple(item.key for item in drift)


def _new_at_default(run: Path) -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cfg = _config_of(run)
        compared = compare_with_sealed(cfg, run, project_root=Path(cfg.workspace.project_root))
    assert compared is not None
    return {key: value for key, value in compared.new_at_default.items() if key != "edition"}


def test_the_sealed_document_writes_the_tables_that_moved(demo: Path) -> None:
    sealed = tomllib.loads((demo / "config.resolved.toml").read_text(encoding="utf-8"))

    assert {"modflow6", "modflownwt"} <= set(sealed)
    assert "runtime" in sealed["flow"]
    assert sealed["solver"]["backend"] == {"kind": "modflow_nwt"}


@pytest.mark.parametrize("name", ["demo", "calage"])
def test_a_replay_of_a_run_of_2_0_does_not_drift(name: str, request: pytest.FixtureRequest) -> None:
    run = request.getfixturevalue(name)

    assert _drift_keys(run) == ()
    assert _new_at_default(run) == NEW_AT_DEFAULT


def test_a_new_key_away_from_its_default_still_drifts(demo: Path) -> None:
    config = demo / "config.toml"
    text = config.read_text(encoding="utf-8")
    config.write_text(
        text.replace(
            "[flow.sinks_sources.recharge]\n", "[flow.sinks_sources.recharge]\nfactor = 2.0\n"
        ),
        encoding="utf-8",
    )
    assert text != config.read_text(encoding="utf-8"), "the demo writes a recharge table"

    assert _drift_keys(demo) == ("flow.sinks_sources.recharge.factor",)


def test_the_settings_of_the_solver_that_ran_still_drift(demo: Path) -> None:
    resolved = demo / "config.resolved.toml"
    text = resolved.read_text(encoding="utf-8")
    resolved.write_text(text.replace("hdry = -100.0", "hdry = -77.0"), encoding="utf-8")
    assert text != resolved.read_text(encoding="utf-8"), "the sealed hdry of NWT is -100.0"

    assert "solver.modflow_nwt.runtime.upw.hdry" in _drift_keys(demo)
