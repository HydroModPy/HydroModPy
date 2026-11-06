"""Real TOMLs of the published alphas still read, or are refused for a reason named here.

``corpus/<tag>/`` holds example files as the tags ``v2.0.0a1`` to ``v2.0.0a5`` wrote
them, comments removed, with their ``base_config`` parents and their data paths left as
they are. Each one goes through the doctor, then through ``hmp config check``. Nothing
here looks at a number. A rename that forgets its row in ``config_migration`` shows up
as a reason this table does not hold, or as a file that stops validating.
"""

from __future__ import annotations

import shutil
import warnings
from fnmatch import fnmatch
from pathlib import Path

import pytest

from hydromodpy.config.config_migration import fix_config_chain
from hydromodpy.core.config_kit.base import CANNOT_REWRITE
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.project.check import check_project

CORPUS = Path(__file__).parent / "corpus"
FILES = sorted(path.relative_to(CORPUS) for path in CORPUS.rglob("*.toml"))

NO_SITE = "no [site] names it"
"""Only the author knows the catchment, so the doctor never writes ``[site]``. The test does."""

PROJECT_ROOT = "[workspace] project_root is not a key of a file"
"""The loader refuses it with the line to delete, and the doctor deletes the line."""

OLD_CALIBRATION_FORM = "This old form is refused"
"""A key of ``[calibration]`` has no delay: the loader names it, and the doctor rewrites it."""

REASONS = {
    "the drains replaced stream enforcement": "'enforce_streams' is not accepted any more",
    "the figure takes its window from the run": "has no option 'scoring_window'",
    "a list replaces, it no longer merges by position": "sources[0].source: Field required",
    "a source names its path": "sources[0].path: Field required",
    "a recharge series replaces the constant": "would be replaced by the series [data.recharge]",
    "an archive is written by hmp publish": 'format = "package" is retired',
    "the runoff ratio left the recharge source": "'runoff_ratio' is not accepted any more",
    "[mesh] replaced [mesh_catchment]": "Section [mesh_catchment] is replaced by [mesh]",
    "[mesh] replaced [mesh_input]": "Section [mesh_input] is replaced by [mesh.triangle]",
    "[persistence] is not read": "Section [persistence] is not read by any run",
    "a comparison is a set of recipes": "workflow.mode = 'comparison' is gone",
    "maxiter is no evaluation count": "does not take maxiter",
}

EXPECTED = (
    ("*/04_*/step[123]_*", None),
    ("*/06_*/project_simulation.toml", None),
    ("*/20_*", None),
    ("*/04_*/step6_*", "the figure takes its window from the run"),
    ("*/04_*/step4_*", "a recharge series replaces the constant"),
    ("v2.0.0a1/04_*/step5_*", "a recharge series replaces the constant"),
    ("*/04_*/step5_*", "an archive is written by hmp publish"),
    ("v2.0.0a1/04_*", "the drains replaced stream enforcement"),
    ("v2.0.0a5/04_*/run_daily*", "the figure takes its window from the run"),
    ("*/04_*/run_daily*", "a list replaces, it no longer merges by position"),
    ("*/04_*", "the figure takes its window from the run"),
    ("*/01_*", "the runoff ratio left the recharge source"),
    ("*/05_*", "a source names its path"),
    ("*/06_*", "[mesh] replaced [mesh_catchment]"),
    ("*/09_*/base_*", "[mesh] replaced [mesh_input]"),
    ("*/09_*/compare_*", "a comparison is a set of recipes"),
    ("*/21_*/auto_sfr_drn*", "the drains replaced stream enforcement"),
    ("*/21_*/calibrated_best*", "[persistence] is not read"),
    ("*/21_*/ref_example04*", "maxiter is no evaluation count"),
)
"""What each file gives once the doctor ran: the first pattern that matches says it."""


def _expected_reason(relative: Path) -> str | None:
    return next(reason for pattern, reason in EXPECTED if fnmatch(str(relative), pattern))


def _copy_of(relative: Path, tmp_path: Path) -> Path:
    """Copy the example of *relative* aside, so nothing rewrites the corpus."""
    example = Path(*relative.parts[:2])
    shutil.copytree(CORPUS / example, tmp_path / example)
    return tmp_path / relative


def _errors_of(path: Path) -> str:
    """Return what ``hmp config check`` refuses in *path*, with ``[site]`` added when it asks."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        errors = " ".join(check_project(path).errors)
        if NO_SITE in errors:
            child = path.with_name(f"with_a_site_{path.name}")
            child.write_text(
                f'base_config = "{path.name}"\n[site]\nname = "corpus"\n', encoding="utf-8"
            )
            errors = " ".join(check_project(child).errors)
    return errors


def test_the_corpus_is_found_and_every_reason_serves() -> None:
    assert len(FILES) >= 50
    assert {reason for _, reason in EXPECTED} - {None} == set(REASONS)


@pytest.mark.parametrize("relative", FILES, ids=str)
def test_a_file_is_refused_only_for_a_named_reason_before_the_doctor(
    relative: Path, tmp_path: Path
) -> None:
    reason = _expected_reason(relative)
    named = (PROJECT_ROOT, OLD_CALIBRATION_FORM, *(() if reason is None else (REASONS[reason],)))

    errors = _errors_of(_copy_of(relative, tmp_path))

    assert not errors or any(text in errors for text in named), errors


@pytest.mark.parametrize("relative", FILES, ids=str)
def test_a_file_validates_after_the_doctor_or_is_refused_for_its_named_reason(
    relative: Path, tmp_path: Path
) -> None:
    target = _copy_of(relative, tmp_path)
    refused = False
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            # A file above is left until the file below it is rewritten, so a chain of two
            # files takes a second pass and settles on the third.
            for _ in range(3):
                again = fix_config_chain(target)
        except ConfigError as error:
            # A child that adds to a list of its parent is refused: the files are left as written.
            assert "to one file by hand" in str(error)
            refused = True

    if not refused:
        assert not [c for changes in again.values() for c in changes if CANNOT_REWRITE not in c]
    reason = _expected_reason(relative)
    errors = _errors_of(target)
    if refused:
        assert errors  # still the old form: the loader names its first problem
    elif reason is None:
        assert not errors
    else:
        assert REASONS[reason] in errors, errors
