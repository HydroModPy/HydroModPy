"""``provenance.json`` of a job, which answers "could I run this again" and nothing else.

It holds no clock, so two identical submissions give identical bytes and the reuse
short-circuit of ``job_id`` has something stable to compare. It names no machine
and no account, because a job directory is handed to somebody else.
"""

from __future__ import annotations

import getpass
import json
import socket
from pathlib import Path

import pytest

from hydromodpy.schema.job import provenance as provenance_module
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.provenance import (
    PROVENANCE_SCHEMA,
    build_provenance,
    git_state,
    write_provenance,
)

pytestmark = pytest.mark.fast


@pytest.fixture(autouse=True)
def git_answers_in_process(monkeypatch):
    # unit/ forbids a subprocess and these tests are about the document, not about git.
    answers = {("rev-parse", "HEAD"): "c0ffee\n", ("status", "--porcelain"): ""}
    monkeypatch.setattr(provenance_module, "_git", lambda *args: answers.get(args))


def provenance_document() -> dict:
    return build_provenance(
        job_id="sha256:" + "a" * 64,
        process_id="demo-delineate",
        process_version="1.2.3",
        backend={"name": "whitebox_workflows", "version": "1.3.5", "digest": "d" * 64},
    )


def leaves(payload: object) -> list[object]:
    """Every scalar of a nested document."""
    if isinstance(payload, dict):
        return [leaf for value in payload.values() for leaf in leaves(value)]
    if isinstance(payload, list):
        return [leaf for value in payload for leaf in leaves(value)]
    return [payload]


def test_names_the_tool_the_build_and_the_backend() -> None:
    document = provenance_document()

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


def test_no_instant_so_two_runs_render_the_same_bytes() -> None:
    first = json.dumps(provenance_document(), sort_keys=True)
    second = json.dumps(provenance_document(), sort_keys=True)

    assert first == second


def test_no_machine_no_account_no_local_path() -> None:
    # The home directory check caught a real leak. sys.executable is an absolute path
    # under somebody's home on an environment-managed install.
    document = provenance_document()
    values = {str(value) for value in leaves(document)}

    assert str(Path.home()) not in json.dumps(document)
    assert socket.gethostname() not in values
    assert getpass.getuser() not in values
    for forbidden in ("hostname", "user", "username", "executable"):
        assert forbidden not in document["platform"]
        assert forbidden not in document["python"]


def test_build_without_a_checkout_is_unknown_and_not_clean(monkeypatch) -> None:
    monkeypatch.setattr(provenance_module, "_git", lambda *args: None)

    assert git_state() == {"commit": None, "dirty": None}


def test_commit_without_a_status_is_not_clean(monkeypatch) -> None:
    def git_without_status(*args: str) -> str | None:
        return "abc123\n" if args[0] == "rev-parse" else None

    monkeypatch.setattr(provenance_module, "_git", git_without_status)

    assert git_state() == {"commit": "abc123", "dirty": None}


def test_packages_are_the_whole_environment_sorted() -> None:
    packages = provenance_module.frozen_packages()

    assert list(packages) == sorted(packages)
    assert "pydantic" in packages
    assert "geopandas" in packages


def test_written_where_the_directory_says(tmp_path: Path) -> None:
    job = JobDirectory.create(tmp_path / "job")

    written = write_provenance(job, provenance_document())

    assert written == job.provenance_path
    assert written.name == "provenance.json"
    assert json.loads(written.read_text(encoding="utf-8"))["schema"] == PROVENANCE_SCHEMA
