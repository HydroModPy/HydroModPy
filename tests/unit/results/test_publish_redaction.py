"""Nothing that leaves the tree names the machine: no host, no user, no absolute path.

Every JSON and TOML document of a copy goes through the one ``redact``
function; text pages have the private paths replaced. The sweep reads every
text file of the copy. A copy that would still leak is refused whole.
"""

from __future__ import annotations

import socket
import tarfile
from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ExportError
from hydromodpy.results.export.publish import publish
from hydromodpy.results.publication import read_published
from tests.unit.results._published_run import make_project, make_sealed_run

_TEXT = {".json", ".jsonld", ".toml", ".md", ".html", ".txt", ".csv"}


def _private_strings(project: Path) -> list[str]:
    workspace = project.parent.parent
    return [str(project), str(workspace), str(Path.home()), f'"{socket.gethostname()}"', "someone"]


def _sweep(copy: Path, private: list[str]) -> list[str]:
    leaks = []
    for path in sorted(copy.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _TEXT:
            continue
        text = path.read_text(encoding="utf-8")
        leaks.extend(f"{path.relative_to(copy)}: {item}" for item in private if item in text)
    return leaks


def test_no_text_of_a_copy_names_the_host_the_user_or_a_private_path(tmp_path) -> None:
    project = make_project(tmp_path)
    copy = publish(
        make_sealed_run(project),
        tmp_path / "out" / "nancon",
        project_root=project,
        with_=("results", "inputs"),
    )

    assert _sweep(copy, _private_strings(project)) == []


def test_the_provenance_keeps_what_it_says_and_loses_who_and_where(tmp_path) -> None:
    import json

    project = make_project(tmp_path)
    copy = publish(make_sealed_run(project), tmp_path / "out" / "nancon", project_root=project)

    provenance = json.loads((copy / "provenance.json").read_text())
    assert "hostname" not in provenance["platform"]
    assert "user" not in provenance["platform"]
    assert provenance["platform"]["cpu"] == "x86_64"
    assert provenance["solver"]["binary_path"] == "<absolute path>"
    assert provenance["sim_id"]


def test_the_frozen_config_keeps_its_tables_with_paths_made_relative(tmp_path) -> None:
    import tomllib

    project = make_project(tmp_path)
    copy = publish(make_sealed_run(project), tmp_path / "out" / "nancon", project_root=project)

    config = tomllib.loads((copy / "config.toml").read_text())
    assert config["publication"]["license"] == "etalab-2.0"
    assert config["workspace"]["root"] == "<absolute path>"


def test_a_tar_is_swept_like_a_directory(tmp_path) -> None:
    project = make_project(tmp_path)
    archive = publish(
        make_sealed_run(project), tmp_path / "out" / "nancon", project_root=project, format="tar"
    )
    extracted = tmp_path / "extracted"
    with tarfile.open(archive) as handle:
        handle.extractall(extracted, filter="data")

    assert _sweep(extracted, _private_strings(project)) == []


def test_a_copy_that_would_still_leak_is_refused_whole(tmp_path) -> None:
    project = make_project(tmp_path)
    run_dir = make_sealed_run(project)
    (run_dir / "exports" / "where.csv").write_text(f"path\n{project}/runs/x\n")

    with pytest.raises(ExportError, match="never names the machine"):
        publish(run_dir, tmp_path / "out" / "nancon", project_root=project)
    assert not (tmp_path / "out" / "nancon").exists()
    assert not any(p.name.startswith(".nancon") for p in (tmp_path / "out").iterdir())
    assert read_published(run_dir) == []
