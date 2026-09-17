"""``provenance.json`` answers "could I run this again", and nothing else.

Two properties carry the weight here. It holds no clock, so two identical
submissions produce two identical documents and the reuse short-circuit of
``job_id`` has something stable to compare. And it names no machine and no
account, because a job directory is handed to somebody else by construction.
"""

from __future__ import annotations

import json

import pytest

from hydromodpy.schema.job import JobDirectory
from hydromodpy.schema.job import provenance as provenance_module
from hydromodpy.schema.job.provenance import (
    PROVENANCE_SCHEMA,
    build_provenance,
    git_state,
    write_provenance,
)

pytestmark = pytest.mark.fast


@pytest.fixture(autouse=True)
def _git_answers_without_a_subprocess(monkeypatch):
    """Answer the two git calls in process.

    ``unit/`` forbids a subprocess, and what these tests are about is the
    document, not whether git is installed. The two tests that are about git
    replace this stub with their own.
    """
    answers = {("rev-parse", "HEAD"): "c0ffee\n", ("status", "--porcelain"): ""}
    monkeypatch.setattr(provenance_module, "_git", lambda *args: answers.get(args))


def _document() -> dict:
    return build_provenance(
        job_id="sha256:" + "a" * 64,
        process_id="demo-delineate",
        process_version="1.2.3",
        backend={"name": "whitebox_workflows", "version": "1.3.5", "digest": "d" * 64},
    )


def test_the_document_names_the_tool_the_build_and_the_backend():
    document = _document()

    assert document["schema"] == PROVENANCE_SCHEMA
    assert document["job_id"] == "sha256:" + "a" * 64
    assert document["process"] == {"id": "demo-delineate", "version": "1.2.3"}
    assert document["tool"]["name"] == "hydromodpy"
    assert document["tool"]["version"]
    assert document["backend"]["name"] == "whitebox_workflows"
    assert set(document["git"]) == {"commit", "dirty"}
    assert document["python"]["implementation"]
    assert document["platform"]["system"]
    assert document["packages"]["pydantic"]


def test_the_document_carries_no_instant_so_two_runs_render_the_same_bytes():
    first = json.dumps(_document(), sort_keys=True)
    second = json.dumps(_document(), sort_keys=True)

    assert first == second


def test_the_document_names_no_machine_no_account_and_no_local_path():
    """The three ways this document has leaked, or could.

    The home-directory check is the one that caught a real defect:
    ``sys.executable`` is an absolute path under somebody's home on every
    environment-managed install, so publishing it published an account name.
    """
    import getpass
    import socket
    from pathlib import Path

    document = _document()
    rendered = json.dumps(document)
    values = {str(value) for value in _leaves(document)}

    assert str(Path.home()) not in rendered
    assert socket.gethostname() not in values
    assert getpass.getuser() not in values
    for forbidden in ("hostname", "user", "username", "executable"):
        assert forbidden not in document["platform"]
        assert forbidden not in document["python"]


def _leaves(payload: object) -> list[object]:
    """Every scalar of a nested document, so a value is compared as a value."""
    if isinstance(payload, dict):
        return [leaf for value in payload.values() for leaf in _leaves(value)]
    if isinstance(payload, list):
        return [leaf for value in payload for leaf in _leaves(value)]
    return [payload]


def test_a_build_that_no_checkout_backs_says_unknown_rather_than_clean(monkeypatch):
    monkeypatch.setattr(provenance_module, "_git", lambda *args: None)

    state = git_state()

    assert state == {"commit": None, "dirty": None}


def test_a_commit_without_a_readable_status_does_not_claim_to_be_clean(monkeypatch):
    def fake_git(*args: str) -> str | None:
        return "abc123\n" if args[0] == "rev-parse" else None

    monkeypatch.setattr(provenance_module, "_git", fake_git)

    assert git_state() == {"commit": "abc123", "dirty": None}


def test_the_packages_are_the_whole_environment_sorted_by_name():
    packages = provenance_module.frozen_packages()

    assert list(packages) == sorted(packages)
    assert "pydantic" in packages
    assert "geopandas" in packages


def test_writing_it_puts_it_where_the_directory_says(tmp_path):
    job = JobDirectory.create(tmp_path / "job")

    written = write_provenance(job, _document())

    assert written == job.provenance_path
    assert written.name == "provenance.json"
    assert json.loads(written.read_text(encoding="utf-8"))["schema"] == PROVENANCE_SCHEMA
