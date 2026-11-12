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


def test_check_accepts_a_project_under_the_roots_the_call_named(
    tmp_path: Path, state_home: Path, roots: dict[str, Path]
) -> None:
    environment = Environment(bounds=Bounds(allowed_roots=(tmp_path,)))
    environment.check(project_root=roots["project"], workspace_root=roots["workspace"])


def test_check_refuses_a_project_outside_the_roots(
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


def test_a_file_named_and_absent_is_refused_as_a_configuration(
    tmp_path: Path, state_home: Path, roots: dict[str, Path]
) -> None:
    """Named by the caller, a missing file stops the verb, never FileNotFound."""
    missing = tmp_path / "elsewhere.toml"
    environment = Environment(credentials=missing)
    with pytest.raises(CredentialsError) as raised:
        environment.check(project_root=roots["project"], workspace_root=roots["workspace"])
    message = str(raised.value)
    assert "does not exist" in message and "elsewhere.toml" in message
    assert not isinstance(raised.value, FileNotFoundError)
    assert exit_code_for(raised.value) == EXIT_CONFIG == 14


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_check_reads_the_file_once_and_only_outside_the_root(
    tmp_path: Path, state_home: Path, roots: dict[str, Path]
) -> None:
    """A readable file is read here; a file under the project is refused."""
    inside = _write(roots["project"] / "credentials.toml")
    environment = Environment(credentials=inside)
    with pytest.raises(CredentialsError, match="outside every project and workspace"):
        environment.check(project_root=roots["project"], workspace_root=roots["workspace"])

    outside = _write(tmp_path / "credentials-depot.toml")
    environment = Environment(credentials=outside)
    environment.check(project_root=roots["project"], workspace_root=roots["workspace"])


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_a_file_readable_by_others_is_refused_before_any_step(
    tmp_path: Path, state_home: Path, roots: dict[str, Path]
) -> None:
    loose = _write(tmp_path / "loose.toml", mode=0o644)
    environment = Environment(credentials=loose)
    with pytest.raises(CredentialsError, match="chmod 600"):
        environment.check(project_root=roots["project"], workspace_root=roots["workspace"])


def test_the_repr_carries_the_paths_and_never_a_secret(
    tmp_path: Path, state_home: Path, roots: dict[str, Path]
) -> None:
    outside = _write(tmp_path / "credentials-depot.toml")
    environment = Environment(credentials=outside)
    rendered = repr(environment)
    assert "credentials-depot.toml" in rendered
    assert "s3cr3t-hunter2" not in rendered


def test_an_environment_without_a_file_reads_nothing(
    roots: dict[str, Path],
) -> None:
    """The server's no-credentials call: nothing at all is read."""
    environment = Environment(credentials=None)
    environment.check(project_root=roots["project"], workspace_root=roots["workspace"])
