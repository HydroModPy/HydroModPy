"""A release that touches no computing code keeps ``--resume`` and the trial cache.

The key of a trial reads the code itself, one digest per layer, and never the
release number. So a new version string, or an edit of a docstring, moves nothing,
and an edit of the code that computes is refused by name.
"""

from __future__ import annotations

import os
import shutil
from datetime import timedelta
from pathlib import Path

import pytest

import hydromodpy.calibration.runners.state as state
from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners.cli_runner import run_calibration_cli
from hydromodpy.calibration.runners.state import build_cache_context
from hydromodpy.core.code_fingerprint import (
    clear_fingerprint_cache,
    code_fingerprint,
    fingerprint_tree,
)
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.results.heartbeat import read_heartbeat
from hydromodpy.results.outcome import effective_status, outcome_path, read_outcome
from hydromodpy.simulation.planning.config import SimulationTimeConfig
from hydromodpy.spatial.field.field_param_sections import FieldHomogeneousSection

pytestmark = pytest.mark.fast

DOCUMENT = """
[simulation]
name = "patch"

[calibration]
evaluator = "analytic_bowl"
method = "grid"
max_trials = 4
seed = 7
save_runs = "none"
method_options = { points_per_dim = 4 }

[calibration.parameters.a]
bounds = [1e-6, 1e-2]
search_space = "log"
path = "flow.param.K.field.value"
"""


def _search(root: Path, *, resume: bool = False) -> CalibrationPersistence:
    path = root / "patch.toml"
    path.write_text(DOCUMENT, encoding="utf-8")
    run_calibration_cli(path, workspace=root, resume=resume)
    return CalibrationPersistence(root / "sessions" / "patch")


def _edited_layer(tmp_path: Path, layer: str, edit: tuple[str, str]) -> dict[str, str]:
    """Return the fingerprint of a copy of the package with one edit in one file of *layer*."""
    package = Path(state.__file__).resolve().parents[2]
    copy = tmp_path / "package"
    shutil.copytree(
        package / layer, copy / layer, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    target = copy / layer / "report.py"
    source = target.read_text(encoding="utf-8")
    assert edit[0] in source
    target.write_text(source.replace(edit[0], edit[1], 1), encoding="utf-8")
    clear_fingerprint_cache()
    edited = fingerprint_tree(copy, [layer])
    clear_fingerprint_cache()
    return {**code_fingerprint(), **edited}


def _copy_as_shipped(tmp_path: Path, layer: str) -> dict[str, str]:
    """Return the fingerprint of an untouched copy: the path of a file enters by its name."""
    return _edited_layer(tmp_path / "plain", layer, ("Calibration", "Calibration"))


def test_a_new_release_number_reads_every_trial_from_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _search(tmp_path)
    solved = [line.only_case.params_hash for line in first.trials()]
    monkeypatch.setattr("hydromodpy.core.version.__version__", "2.0.1")

    again = _search(tmp_path, resume=True)

    lines = again.trials()
    assert [line.only_case.params_hash for line in lines[len(solved) :]] == solved
    assert all(line.only_case.from_cache for line in lines[len(solved) :])
    assert again.descriptor.status == "completed"


def test_an_edited_docstring_moves_no_digest_and_an_edited_statement_does(tmp_path: Path) -> None:
    plain = _copy_as_shipped(tmp_path, "calibration")
    docstring = _edited_layer(
        tmp_path / "doc", "calibration", ('"""Calibration session', '"""A reworded session')
    )
    statement = _edited_layer(
        tmp_path / "code", "calibration", ("logger = get_logger(__name__)", "logger = None")
    )
    assert docstring["calibration"] == plain["calibration"]
    assert statement["calibration"] != plain["calibration"]


def test_a_resume_after_a_docstring_edit_keeps_its_trials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _search(tmp_path)
    n_solved = len(first.trials())
    shipped = code_fingerprint()
    monkeypatch.setattr(state, "code_fingerprint", lambda: dict(shipped))

    again = _search(tmp_path, resume=True)

    assert all(line.only_case.from_cache for line in again.trials()[n_solved:])


def test_a_resume_after_a_change_of_the_computing_code_names_the_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _search(tmp_path)
    moved = {**code_fingerprint(), "solver": "another digest"}
    monkeypatch.setattr(state, "code_fingerprint", lambda: moved)

    with pytest.raises(CalibrationError, match=r"code\.solver changed since they ran"):
        _search(tmp_path, resume=True)


def test_the_session_keeps_the_fingerprint_of_each_member_of_the_key(tmp_path: Path) -> None:
    case = _search(tmp_path).descriptor.cases["patch"]
    members = case.context["main"]
    assert members["schema"] == "hydromodpy.calibration.params_hash.v4"
    assert {f"code.{layer}" for layer in code_fingerprint()} <= set(members)
    assert "code_version" not in members
    assert len(members["calibration"]) == 16


def _section(extra: str = "") -> CalibrationConfig:
    return CalibrationConfig.model_validate(
        {
            "parameters": {"a": {"bounds": [1e-6, 1e-2], "path": "flow.param.K.field.value"}},
            "method": "grid",
            **({"objective": extra} if extra else {}),
        }
    )


def _key(cfg: CalibrationConfig) -> dict[str, object]:
    space = ParameterSpace.from_toml_mapping(
        {name: decl.model_dump(exclude_none=True) for name, decl in cfg.parameters.items()}
    )
    return build_cache_context(
        cfg=cfg, trial_ctx=None, space=space, override_paths={}, objective_entrypoint=None
    )


def test_a_key_written_at_its_default_is_another_key() -> None:
    default = CalibrationConfig.model_fields["objective"].default
    assert _key(_section())["calibration"] != _key(_section(str(default)))["calibration"]


_DATES = {"start_datetime": "2000-01-01", "end_datetime": "2000-12-31"}


@pytest.mark.parametrize(
    ("model", "first", "second"),
    [
        (
            SimulationTimeConfig,
            {**_DATES, "step_value": "1 month"},
            {**_DATES, "step_value": "1 day"},
        ),
        (FieldHomogeneousSection, {"value": "1e-5 m/s"}, {"value": "1e-5 cm/s"}),
    ],
)
def test_a_unit_written_inside_a_value_stays_in_what_the_file_wrote(
    model: type, first: dict[str, str], second: dict[str, str]
) -> None:
    dumps = [
        model.model_validate(doc).model_dump(mode="json", exclude_unset=True)
        for doc in (first, second)
    ]
    assert dumps[0] != dumps[1]


def test_a_cached_trial_reads_the_numbers_and_never_the_run_of_another_session(
    tmp_path: Path,
) -> None:
    first = _search(tmp_path)
    number = first.trials()[0].trial
    first.link_trial(number, sim_id="another-session-run", rel_dir="runs/patch")

    path = tmp_path / "patch.toml"
    run_calibration_cli(path, workspace=tmp_path)
    second = CalibrationPersistence(tmp_path / "sessions" / "patch.v2")

    cases = [line.only_case for line in second.trials()]
    assert all(case.from_cache and case.sim_id is None and not case.detail for case in cases)
    assert cases[0].components == first.trials()[0].only_case.components


def test_a_live_session_pulses_and_reads_running_whatever_its_outcome_says(
    tmp_path: Path,
) -> None:
    from tests._helpers.session_documents import session_opening

    persistence = CalibrationPersistence(tmp_path)
    persistence.start_session(**session_opening())
    persistence.start_pulse()
    try:
        beat = read_heartbeat(tmp_path)
        assert beat is not None
        assert beat.attempt_id == read_outcome(tmp_path).attempt_id
        long_ago = beat.at.timestamp() - 3600
        os.utime(outcome_path(tmp_path), (long_ago, long_ago))
        assert effective_status(tmp_path, now=beat.at + timedelta(seconds=10)) == "running"
    finally:
        persistence.stop_pulse()
    assert effective_status(tmp_path, now=beat.at + timedelta(hours=1)) == "stale"
