"""``hmp publish --verify`` on the folder ``hmp publish .`` writes for a project.

The folder holds one copy per sealed run and one for the summary, each with
its ``PUBLICATION.json``, and its own ``PUBLICATION.json`` of kind ``project``
that lists them. Verified as a whole, every member is checked and a
difference names its member; a member removed is named. A folder of copies
without the project ``PUBLICATION.json`` is still verified member by member.
A folder that holds no copy is refused by name, never with a raw ``OSError``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_GENERIC, EXIT_NOT_FOUND, EXIT_OK
from tests._helpers.cli_runner import CliRunner
from tests.unit.results._published_run import (
    RUN_NAME,
    make_project,
    make_sealed_run,
    make_summary,
)


def _invoke(*args: str):
    return CliRunner().invoke(["publish", *args])


def _published(tmp_path: Path) -> Path:
    project = make_project(tmp_path)
    make_sealed_run(project)
    make_summary(project, error_message="diverged")
    destination = tmp_path / "out"
    result = _invoke(".", "--to", str(destination), "-w", str(project))
    assert result.exit_code == EXIT_OK, result.stderr
    return destination


def test_a_project_copy_is_verified_through_its_own_publication(tmp_path: Path) -> None:
    destination = _published(tmp_path)

    result = _invoke("--verify", str(destination))

    assert result.exit_code == EXIT_OK, result.stderr
    assert "a campaign copy" not in result.stderr
    assert "every file matches PUBLICATION.json" in result.stderr


def test_a_removed_member_is_named(tmp_path: Path) -> None:
    destination = _published(tmp_path)
    shutil.rmtree(destination / RUN_NAME)

    result = _invoke("--verify", str(destination))

    assert result.exit_code == EXIT_GENERIC
    assert f"{RUN_NAME}: missing" in result.stdout


def test_a_changed_file_names_its_member(tmp_path: Path) -> None:
    destination = _published(tmp_path)
    (destination / "summary" / "by_case.csv").write_text("changed\n", encoding="utf-8")
    (destination / "notes.txt").write_text("added by hand\n", encoding="utf-8")

    result = _invoke("--verify", str(destination))

    assert result.exit_code == EXIT_GENERIC
    assert "summary/by_case.csv: digest differs" in result.stdout
    assert "notes.txt: not listed in PUBLICATION.json" in result.stdout
    assert f"{RUN_NAME}/" not in result.stdout


def test_a_folder_of_copies_without_the_project_publication_is_verified(tmp_path: Path) -> None:
    destination = _published(tmp_path)
    (destination / "PUBLICATION.json").unlink()
    (destination / "notes.txt").write_text("added by hand\n", encoding="utf-8")

    result = _invoke("--verify", str(destination))

    assert result.exit_code == EXIT_GENERIC
    assert "a campaign copy: verifying its 2 members" in result.stderr
    assert "notes.txt: not a published copy" in result.stdout
    assert f"{RUN_NAME}/" not in result.stdout


def test_a_folder_without_any_copy_is_refused_by_name(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    result = _invoke("--verify", str(empty))

    assert result.exit_code == EXIT_NOT_FOUND
    assert "holds no PUBLICATION.json and no published copy" in result.stderr
    assert "Errno" not in result.stderr
