""":class:`Environment` at the open of a project, and no other moment.

``default()`` answers the machine: the credentials at their default place,
the default bounds. ``check`` is the one moment the file is read, so a
refused file stops the verb before its first step instead of stopping a
delivery after hours of solve. An absent file at the default place is an
answer (no identifiers), an absent file the caller named is a refusal.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hydromodpy.cli.exit_codes import EXIT_CONFIG, exit_code_for
from hydromodpy.core.exceptions import BoundsError, CredentialsError
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.project.environment import Environment

GOOD = """
[[host]]
prefix = "ftps://depot.example.org/hydromodpy/"
user = "bastien"
password = "s3cr3t-hunter2"
"""


@pytest.fixture
def state_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The state root of the machine, here: a folder next to the project."""
    home = tmp_path / "state"
    monkeypatch.setenv("HMP_STATE_HOME", str(home))
    return home


@pytest.fixture
def roots(tmp_path: Path) -> dict[str, Path]:
    project = tmp_path / "projects" / "one"
    workspace = tmp_path / "workspace"
    project.mkdir(parents=True)
    workspace.mkdir(parents=True)
    return {"project": project, "workspace": workspace}


def _write(path: Path, body: str = GOOD, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(mode)
    return path


def test_check_accepts_named_roots(
    tmp_path: Path, state_home: Path, roots: dict[str, Path]
) -> None:
    environment = Environment(bounds=Bounds(allowed_roots=(tmp_path,)))
    environment.check(project_root=roots["project"], workspace_root=roots["workspace"])


def test_check_refuses_outside_roots(
    tmp_path: Path, state_home: Path, roots: dict[str, Path]
) -> None:
    elsewhere = tmp_path / "other-project"
    elsewhere.mkdir()
    environment = Environment(bounds=Bounds(allowed_roots=(roots["workspace"],)))
    with pytest.raises(BoundsError) as raised:
        environment.check(project_root=elsewhere, workspace_root=roots["workspace"])
    message = str(raised.value)
    assert "opening the project" in message
    assert str(elsewhere) in message


def test_named_absent_file_refused(
    tmp_path: Path, state_home: Path, roots: dict[str, Path]
) -> None:
    missing = tmp_path / "elsewhere.toml"
    environment = Environment(credentials=missing)
    with pytest.raises(CredentialsError) as raised:
        environment.check(project_root=roots["project"], workspace_root=roots["workspace"])
    message = str(raised.value)
    assert "does not exist" in message and "elsewhere.toml" in message
    assert not isinstance(raised.value, FileNotFoundError)
    assert exit_code_for(raised.value) == EXIT_CONFIG == 14


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_credentials_outside_project_only(
    tmp_path: Path, state_home: Path, roots: dict[str, Path]
) -> None:
    inside = _write(roots["project"] / "credentials.toml")
    environment = Environment(credentials=inside)
    with pytest.raises(CredentialsError, match="outside every project and workspace"):
        environment.check(project_root=roots["project"], workspace_root=roots["workspace"])

    outside = _write(tmp_path / "credentials-depot.toml")
    environment = Environment(credentials=outside)
    environment.check(project_root=roots["project"], workspace_root=roots["workspace"])


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_loose_mode_refused(tmp_path: Path, state_home: Path, roots: dict[str, Path]) -> None:
    loose = _write(tmp_path / "loose.toml", mode=0o644)
    environment = Environment(credentials=loose)
    with pytest.raises(CredentialsError, match="chmod 600"):
        environment.check(project_root=roots["project"], workspace_root=roots["workspace"])


def test_repr_hides_secret(tmp_path: Path, state_home: Path, roots: dict[str, Path]) -> None:
    outside = _write(tmp_path / "credentials-depot.toml")
    environment = Environment(credentials=outside)
    rendered = repr(environment)
    assert "credentials-depot.toml" in rendered
    assert "s3cr3t-hunter2" not in rendered


def test_no_file_reads_nothing(
    roots: dict[str, Path],
) -> None:
    environment = Environment(credentials=None)
    environment.check(project_root=roots["project"], workspace_root=roots["workspace"])
