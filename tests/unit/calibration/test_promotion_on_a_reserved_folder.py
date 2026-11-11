"""A kept trial is promoted onto the folder its promotion reserved, as Windows asks it.

Windows refuses to rename a folder onto another one, even an empty one, so
``os.replace`` raises there. The promotion then removes the empty reservation
and renames without replacing. A process that takes the name in between keeps
it, and the promotion fails with a sentence that says to promote again.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners.promotion import promote_trial_from_session
from hydromodpy.core.exceptions import WriteConflictError
from hydromodpy.core.io import filesystem
from hydromodpy.results.session.journal import read_trials
from tests._helpers.windows_os import PatchedOs
from tests.unit.calibration._factories_runners import make_session

_REAL_REPLACE = os.replace
_REAL_RENAME = os.rename


def _windows_replace(source, target, *args, **kwargs):
    """``os.replace`` as Windows does it: a folder is never moved onto a folder."""
    if Path(source).is_dir() and Path(target).is_dir():
        raise PermissionError(5, "Access is denied", str(target))
    return _REAL_REPLACE(source, target, *args, **kwargs)


def _kept_trial(project: Path) -> tuple[CalibrationPersistence, Path]:
    """A session of two trials whose second one is kept under the session."""
    (project / "project.toml").write_text('[site]\nname = "nancon"\n', encoding="utf-8")
    persistence = make_session(project, costs=(0.9, 0.1))
    kept = persistence.directory / "trials" / "0002"
    kept.mkdir(parents=True)
    (kept / "manifest.json").write_text("{}", encoding="utf-8")
    return persistence, kept


def test_the_trial_lands_on_the_reserved_name_when_the_rename_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    persistence, kept = _kept_trial(tmp_path)
    monkeypatch.setattr(filesystem, "os", PatchedOs(name="nt", replace=_windows_replace))
    monkeypatch.setattr(filesystem, "WINDOWS_PATH_LIMIT", 10**6)  # tmp_path is long

    target = promote_trial_from_session(tmp_path, "calage", 2, as_name="k_low")

    assert target == tmp_path / "runs" / "k_low"
    assert (target / "manifest.json").is_file()
    assert not kept.exists()
    line = {item.trial: item for item in read_trials(persistence.directory)}[2]
    assert line.only_case.rel_dir == "runs/k_low"


def test_a_name_taken_in_between_stays_with_its_taker_and_the_trial_stays_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    persistence, kept = _kept_trial(tmp_path)
    target = tmp_path / "runs" / "k_low"

    def taken_in_between(source, destination, *args, **kwargs):
        if Path(destination) != target:
            return _REAL_RENAME(source, destination, *args, **kwargs)
        target.mkdir()
        (target / "theirs.txt").write_text("another process", encoding="utf-8")
        raise FileExistsError(183, "Cannot create a file when that file already exists")

    patched = PatchedOs(name="nt", replace=_windows_replace, rename=taken_in_between)
    monkeypatch.setattr(filesystem, "os", patched)
    monkeypatch.setattr(filesystem, "WINDOWS_PATH_LIMIT", 10**6)  # tmp_path is long

    with pytest.raises(WriteConflictError) as raised:
        promote_trial_from_session(tmp_path, "calage", 2, as_name="k_low")

    assert str(raised.value) == (
        f"{target} was taken by another process while the trial moved into it; promote again."
    )
    assert (target / "theirs.txt").read_text(encoding="utf-8") == "another process"
    assert (kept / "manifest.json").is_file()
    line = {item.trial: item for item in read_trials(persistence.directory)}[2]
    assert line.only_case.rel_dir != "runs/k_low"
