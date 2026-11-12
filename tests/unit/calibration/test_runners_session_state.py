"""Calibration session identity and reuse: the file a session reads, the period it scores, the fingerprints of a stored trial.

Covers `runners.session`, `runners.state`, `runners.resume` and `runners.document`. Costs are objective values.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import BaseModel

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.cache import params_hash
from hydromodpy.calibration.runners import resume, session, state, trial
from hydromodpy.calibration.runners.document import identical_session
from hydromodpy.calibration.runners.promotion import promotion_name_check
from hydromodpy.calibration.runners.resume import (
    ReusableStage,
    fingerprint_matches,
    reusable_stage,
    trials_another_cost_scored,
)
from hydromodpy.calibration.runners.session import search_windows
from hydromodpy.core.exceptions import ConfigError
from tests._helpers.sealed_runs import CONFIG_HASH, write_session_dir


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_carrier_of_calibration(tmp_path) -> None:
    _write(tmp_path / "base.toml", "[calibration]\nmethod = 'grid'\n")
    _write(tmp_path / "mid.toml", "base_config = 'base.toml'\n")
    top = _write(tmp_path / "top.toml", f"base_config = '{tmp_path / 'mid.toml'}'\n")

    assert session._carrier_of_calibration(top) == (tmp_path / "base.toml").resolve()


def test_chain_without_calibration(
    tmp_path,
) -> None:
    top = _write(tmp_path / "top.toml", "base_config = 'missing.toml'\n")

    assert session._carrier_of_calibration(top) == top


def test_session_identity(monkeypatch) -> None:
    asked: list[object] = []

    class _Pipeline:
        def session_key(self, cfg: object) -> str | None:
            asked.append(cfg)
            return "key-of-the-model"

    ctx = SimpleNamespace(base_cfg=SimpleNamespace(model_dump=dict))
    monkeypatch.setattr(trial, "_PIPELINE", _Pipeline())

    assert session.session_config_hash({"a": 1}, ctx) == "key-of-the-model"
    assert asked == [ctx.base_cfg]

    expected = hashlib.sha256(json.dumps({"a": 1}, sort_keys=True).encode()).hexdigest()
    assert session.session_config_hash({"a": 1}, None) == expected
    monkeypatch.setattr(_Pipeline, "session_key", lambda self, cfg: None)
    assert session.session_config_hash({"a": 1}, ctx) == expected


_PARAMETERS = {"K": {"bounds": [1e-9, 1e-3], "path": "flow.param.K.field.value"}}


@pytest.mark.parametrize(
    ("phase", "document", "expected"),
    [
        ({"regime": "steady"}, None, {}),
        ({}, None, {}),
        ({}, {"simulation": "x"}, {}),
        ({}, {"simulation": {"time": {"start_datetime": "", "end_datetime": None}}}, {}),
        (
            {},
            {
                "simulation": {
                    "time": {"start_datetime": "2000-01-01", "end_datetime": "2001-06-30"}
                }
            },
            (date(2000, 1, 1), date(2001, 6, 30)),
        ),
    ],
)
def test_search_windows(phase, document, expected) -> None:
    cfg = CalibrationConfig.model_validate(
        {
            "method": "grid",
            "parameters": _PARAMETERS,
            "phases": [{"name": "p", "parameters": ["K"], **phase}],
        }
    )

    found = search_windows(cfg, document)

    if expected == {}:
        assert found == {}
    else:
        [window] = found.values()
        assert (window.start, window.end) == expected


class _Config(BaseModel):
    name: str = "c"


def _entry(path: Path, role: str = "dem") -> SimpleNamespace:
    return SimpleNamespace(role=role, category="data", canonical_path=path)


def test_entry_point_refused() -> None:
    with pytest.raises(ValueError, match="'module.path:callable', got: 'metrics'"):
        state.load_metric_fn_entry_point("metrics")


@pytest.mark.parametrize("centers", [np.zeros(3), np.zeros((0, 2))])
def test_mesh_without_centroids(centers) -> None:
    ctx = SimpleNamespace(setup=SimpleNamespace(cell_mesh=SimpleNamespace(centers=centers)))

    assert state.mesh_fingerprint(ctx) is None


def test_map_digest(tmp_path) -> None:
    folder = tmp_path / "map"
    folder.mkdir()
    (folder / "a.txt").write_text("x")

    assert state._map_digest(folder) == state.sha256_directory(folder)
    assert state._map_digest(tmp_path / "none") == "missing"


def test_input_file_fingerprints(monkeypatch, tmp_path) -> None:
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir" / "a.txt").write_text("a")
    (tmp_path / "f.txt").write_text("hello")
    entries = [
        _entry(tmp_path / "f.txt", "file"),
        _entry(tmp_path / "dir", "dir"),
        _entry(tmp_path / "gone", "gone"),
    ]
    monkeypatch.setattr(state, "collect_input_files", lambda config, base=None: entries)

    found = {item["role"]: item for item in state._input_file_fingerprints(_Config())}

    assert found["file"]["kind"] == "file"
    assert found["file"]["sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert found["file"]["size_bytes"] == 5
    assert found["dir"]["sha256"] == state.sha256_directory(tmp_path / "dir")
    assert (found["gone"]["kind"], found["gone"]["exists"]) == ("missing", False)


def test_unlistable_inputs(monkeypatch) -> None:
    def refuse(config, base=None):
        raise RuntimeError("no inputs")

    monkeypatch.setattr(state, "collect_input_files", refuse)

    assert state._input_file_fingerprints(_Config()) == []
    assert state._input_file_fingerprints(object()) == []


CONTEXT = {"mesh": "m1"}


def _trial(number, status, hash_, k=1e-5):
    case = None if hash_ is None else SimpleNamespace(params_hash=hash_)
    return SimpleNamespace(
        trial=number,
        status=status,
        only_case=case,
        parameters={"K": k},
    )


def test_phase_without_scored_trial(monkeypatch) -> None:
    monkeypatch.setattr(resume, "completed_phases", lambda persistence: {"flow": object()})
    persistence = SimpleNamespace(held_trial=lambda name: None)

    assert reusable_stage(persistence, "flow") is None


def test_trial_without_hash() -> None:
    stage = ReusableStage("flow", 1, 1, 0.1, {"K": 1e-5}, None)

    assert fingerprint_matches(stage, cache_context=CONTEXT) is False


def test_trials_of_another_cost(monkeypatch) -> None:
    monkeypatch.setattr(resume, "physical_parameters", lambda line: line.parameters)
    good = params_hash({"K": 1e-5}, context=CONTEXT)
    lines = [
        _trial(1, "completed", good),
        _trial(2, "completed", "stale"),
        _trial(3, "completed", None),
        _trial(4, "crashed", "stale"),
    ]
    persistence = SimpleNamespace(trials=lambda phase: lines)

    assert trials_another_cost_scored(persistence, "flow", cache_context=CONTEXT) == ([2], [3])


def test_identical_session_report(tmp_path: Path) -> None:
    session_id = write_session_dir(tmp_path, "calage", trials=3, best_trial=2)

    report = identical_session(CONFIG_HASH, project_root=tmp_path, case="calage")

    assert report is not None
    assert report.extra == {"identical_to": "calage"}
    assert (report.session_id, report.n_trials, report.best_trial) == (session_id, 3, 2)
    assert (report.duration_s, report.promoted, report.status) == (0.0, 0, "completed")
    assert report.best_parameters == {"K": pytest.approx(2e-5)}
    assert report.session_dir == tmp_path / "sessions" / "calage"
    assert report.to_dict()["extra"] == {"identical_to": "calage"}


@pytest.mark.parametrize(
    ("key", "case", "status"),
    [
        pytest.param(None, "calage", "completed", id="a key not told offline"),
        pytest.param("other", "calage", "completed", id="another key"),
        pytest.param("same", "other", "completed", id="another case"),
        pytest.param("same", "calage", "failed", id="a search that failed"),
    ],
)
def test_no_identical_session(tmp_path: Path, key: str | None, case: str, status: str) -> None:
    write_session_dir(tmp_path, "calage", status=status)

    asked = CONFIG_HASH if key == "same" else key
    assert identical_session(asked, project_root=tmp_path, case=case) is None


def test_case_of_the_search(tmp_path: Path) -> None:
    write_session_dir(tmp_path, "cal")
    source = tmp_path / "cal.toml"
    source.write_text("[calibration]\n", encoding="utf-8")

    assert identical_session(CONFIG_HASH, project_root=tmp_path, source=source) is not None
    named = {"simulation": {"name": "cal"}}
    assert identical_session(CONFIG_HASH, project_root=tmp_path, document=named) is not None
    assert identical_session(CONFIG_HASH, project_root=tmp_path, document={}) is None


@pytest.mark.parametrize("name", ["Calib Winter", "aux", "a__b"])
def test_case_name_refused(name: str) -> None:
    with pytest.raises(ConfigError):
        promotion_name_check(name)
