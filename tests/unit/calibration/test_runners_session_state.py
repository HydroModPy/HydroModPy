"""Tests of `runners.session`: the file a session reads, the identity it records, the period it scores."""

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
from hydromodpy.calibration.runners import resume, session, state
from hydromodpy.calibration.runners.resume import (
    ReusableStage,
    fingerprint_matches,
    reusable_stage,
    trials_another_cost_scored,
)
from hydromodpy.calibration.runners.session import search_windows


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_the_calibration_is_read_from_the_first_file_of_the_chain_that_writes_it(tmp_path) -> None:
    _write(tmp_path / "base.toml", "[calibration]\nmethod = 'grid'\n")
    _write(tmp_path / "mid.toml", "base_config = 'base.toml'\n")
    top = _write(tmp_path / "top.toml", f"base_config = '{tmp_path / 'mid.toml'}'\n")

    assert session._carrier_of_calibration(top) == (tmp_path / "base.toml").resolve()


def test_a_chain_that_never_writes_the_calibration_stays_on_the_file_it_started_from(
    tmp_path,
) -> None:
    top = _write(tmp_path / "top.toml", "base_config = 'missing.toml'\n")

    assert session._carrier_of_calibration(top) == top


def test_the_identity_of_a_session_follows_the_model_then_the_document(monkeypatch) -> None:
    from hydromodpy.calibration.runners import trial

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
def test_the_period_a_search_scores_is_the_declared_one_or_nothing(
    phase, document, expected
) -> None:
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


# ---------------------------------------------------------------------------
# runners_state
# Tests of `runners.state`: the fingerprints that decide whether a stored trial is the same trial.
# ---------------------------------------------------------------------------


class _Config(BaseModel):
    name: str = "c"


def _entry(path: Path, role: str = "dem") -> SimpleNamespace:
    return SimpleNamespace(role=role, category="data", canonical_path=path)


def test_an_entry_point_without_a_colon_is_refused() -> None:
    with pytest.raises(ValueError, match="'module.path:callable', got: 'metrics'"):
        state.load_metric_fn_entry_point("metrics")


@pytest.mark.parametrize("centers", [np.zeros(3), np.zeros((0, 2))])
def test_a_mesh_without_centroids_has_no_identity(centers) -> None:
    ctx = SimpleNamespace(setup=SimpleNamespace(cell_mesh=SimpleNamespace(centers=centers)))

    assert state.mesh_fingerprint(ctx) is None


def test_a_map_folder_and_a_missing_map_have_a_digest(tmp_path) -> None:
    folder = tmp_path / "map"
    folder.mkdir()
    (folder / "a.txt").write_text("x")

    assert state._map_digest(folder) == state.sha256_directory(folder)
    assert state._map_digest(tmp_path / "none") == "missing"


def test_input_files_are_fingerprinted_by_kind(monkeypatch, tmp_path) -> None:
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


def test_a_configuration_whose_inputs_cannot_be_listed_has_no_fingerprints(monkeypatch) -> None:
    def refuse(config, base=None):
        raise RuntimeError("no inputs")

    monkeypatch.setattr(state, "collect_input_files", refuse)

    assert state._input_file_fingerprints(_Config()) == []
    assert state._input_file_fingerprints(object()) == []


# ---------------------------------------------------------------------------
# runners_resume
# Tests of `runners.resume`: what a reopened session may trust of a phase it already solved.
# ---------------------------------------------------------------------------

CONTEXT = {"mesh": "m1"}


def _trial(number, status, hash_, k=1e-5):
    case = None if hash_ is None else SimpleNamespace(params_hash=hash_)
    return SimpleNamespace(
        trial=number,
        status=status,
        only_case=case,
        parameters={"K": k},
    )


def test_a_phase_that_left_no_scored_trial_is_not_reused(monkeypatch) -> None:
    monkeypatch.setattr(resume, "completed_phases", lambda persistence: {"flow": object()})
    persistence = SimpleNamespace(held_trial=lambda name: None)

    assert reusable_stage(persistence, "flow") is None


def test_a_trial_with_no_recorded_hash_is_not_trusted() -> None:
    stage = ReusableStage("flow", 1, 1, 0.1, {"K": 1e-5}, None)

    assert fingerprint_matches(stage, cache_context=CONTEXT) is False


def test_only_completed_trials_are_checked_against_the_cost_of_today(monkeypatch) -> None:
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


# A completed session of the same case and key answers a calibration again.


def test_a_completed_session_of_the_same_key_is_given_back_as_its_report(tmp_path: Path) -> None:
    from hydromodpy.calibration.runners.document import identical_session
    from tests._helpers.sealed_runs import CONFIG_HASH, write_session_dir

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
def test_no_session_answers_another_key_another_case_or_an_unfinished_search(
    tmp_path: Path, key: str | None, case: str, status: str
) -> None:
    from hydromodpy.calibration.runners.document import identical_session
    from tests._helpers.sealed_runs import CONFIG_HASH, write_session_dir

    write_session_dir(tmp_path, "calage", status=status)

    asked = CONFIG_HASH if key == "same" else key
    assert identical_session(asked, project_root=tmp_path, case=case) is None


def test_the_case_of_the_search_is_the_one_its_file_or_its_document_names(tmp_path: Path) -> None:
    from hydromodpy.calibration.runners.document import identical_session
    from tests._helpers.sealed_runs import CONFIG_HASH, write_session_dir

    write_session_dir(tmp_path, "cal")
    source = tmp_path / "cal.toml"
    source.write_text("[calibration]\n", encoding="utf-8")

    assert identical_session(CONFIG_HASH, project_root=tmp_path, source=source) is not None
    named = {"simulation": {"name": "cal"}}
    assert identical_session(CONFIG_HASH, project_root=tmp_path, document=named) is not None
    assert identical_session(CONFIG_HASH, project_root=tmp_path, document={}) is None


@pytest.mark.parametrize(
    ("file_name", "text", "case"),
    [
        ("Calib Winter.toml", "[calibration]\n", "calib_winter"),
        ("calage.toml", "[calibration]\n", "calage"),
        ("Calib Winter.toml", '[simulation]\nname = "kept"\n[calibration]\n', "kept"),
    ],
    ids=["a stem the code folds", "a stem already a name", "a name the file writes"],
)
def test_the_case_of_a_file_is_its_written_name_or_its_stem_folded(
    tmp_path: Path, file_name: str, text: str, case: str
) -> None:
    """A run of the same file folds its stem the same way, so the two share a name."""
    path = _write(tmp_path / file_name, text)

    assert session.calibration_case_name(path) == case


@pytest.mark.parametrize("name", ["Calib Winter", "aux", "a__b"])
def test_a_case_that_breaks_the_rule_of_a_name_is_refused_before_the_search(name: str) -> None:
    from hydromodpy.calibration.runners.promotion import promotion_name_check
    from hydromodpy.core.exceptions import ConfigError

    with pytest.raises(ConfigError):
        promotion_name_check(name)
