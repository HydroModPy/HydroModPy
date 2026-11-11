"""``case_is_done`` reads the level of the run it finds, so a trial never answers a run.

A sealed directory whose lineage is a kept trial is ``research``: an identical
directory of that level does not close a case, since a run of the case has to
keep more. A run of ``result``, or a published copy, closes it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.project.launch.sites.expansion import case_is_done
from hydromodpy.results.session.descriptor import write_session
from hydromodpy.results.storage.contract import (
    PUBLICATION_FILENAME,
    RUN_MANIFEST_FILENAME,
)
from tests._helpers.sealed_runs import manifest_document
from tests._helpers.session_documents import session_descriptor

KEY = "H" * 64


def _seal(
    root: Path,
    name: str,
    *,
    key: str = KEY,
    kind: str | None = None,
    published: bool = False,
) -> Path:
    """Write a sealed run directory of *name* with the solution key *key*."""
    lineage = {} if kind is None else {"kind": kind, "trial": 1, "session_id": "s" * 32}
    document = manifest_document(name=name, lineage=lineage)
    document["identity"]["solution_key"] = key
    directory = root / "runs" / name
    directory.mkdir(parents=True)
    (directory / RUN_MANIFEST_FILENAME).write_text(json.dumps(document), encoding="utf-8")
    if published:
        (directory / PUBLICATION_FILENAME).write_text("{}", encoding="utf-8")
    return directory


def test_a_research_run_of_the_key_does_not_close_the_case(tmp_path: Path) -> None:
    _seal(tmp_path, "case", kind="trial")

    assert case_is_done(tmp_path, "case", KEY, "simulation") is False


def test_a_result_run_of_the_key_closes_the_case(tmp_path: Path) -> None:
    _seal(tmp_path, "case")

    assert case_is_done(tmp_path, "case", KEY, "simulation") is True


def test_a_published_copy_of_the_key_closes_the_case(tmp_path: Path) -> None:
    _seal(tmp_path, "case", published=True)

    assert case_is_done(tmp_path, "case", KEY, "simulation") is True


def test_a_version_of_the_case_name_is_read_at_its_level(tmp_path: Path) -> None:
    _seal(tmp_path, "case.v2", kind="trial")
    assert case_is_done(tmp_path, "case", KEY, "simulation") is False

    _seal(tmp_path, "case.v3")
    assert case_is_done(tmp_path, "case", KEY, "simulation") is True


@pytest.mark.parametrize(
    ("key", "hash_"),
    [("other", KEY), (KEY, None)],
    ids=["another-key", "no-key"],
)
def test_a_different_key_or_no_key_never_closes_the_case(
    tmp_path: Path, key: str, hash_: str | None
) -> None:
    _seal(tmp_path, "case", key=key)

    assert case_is_done(tmp_path, "case", hash_, "simulation") is False


def test_a_project_without_runs_closes_nothing(tmp_path: Path) -> None:
    assert case_is_done(tmp_path / "absent", "case", KEY, "simulation") is False


def test_an_unreadable_manifest_never_closes_the_case(tmp_path: Path) -> None:
    directory = tmp_path / "runs" / "case"
    directory.mkdir(parents=True)
    (directory / RUN_MANIFEST_FILENAME).write_text("{", encoding="utf-8")

    assert case_is_done(tmp_path, "case", KEY, "simulation") is False


def test_a_completed_session_of_the_hash_closes_the_calibration_case(tmp_path: Path) -> None:
    write_session(
        tmp_path / "sessions" / "case",
        session_descriptor("case", config_hash=KEY, status="completed"),
    )

    assert case_is_done(tmp_path, "case", KEY, "calibration") is True


def test_a_running_session_never_closes_the_calibration_case(tmp_path: Path) -> None:
    write_session(
        tmp_path / "sessions" / "case",
        session_descriptor("case", config_hash=KEY, status="running"),
    )

    assert case_is_done(tmp_path, "case", KEY, "calibration") is False
