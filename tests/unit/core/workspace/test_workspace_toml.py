"""Writer and loader of ``workspace.toml``, the file that marks a workspace root.

The file holds the workspace name, its contact, and the minimum HydroModPy version
that may open it. The loader refuses a newer minimum and any unknown block.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.core.exceptions import SchemaVersionMismatchError
from hydromodpy.core.state.layout import WORKSPACE_TOML_FILENAME
from hydromodpy.core.workspace import workspace_toml
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.core.workspace.workspace_toml import (
    DEFAULT_WORKSPACE_TOML_TEMPLATE,
    WORKSPACE_VERSION_MIN,
    WorkspaceToml,
    load_workspace_toml,
    refuse_a_newer_workspace,
    write_workspace_toml,
)


def scaffold_workspace(tmp_path: Path, minimum: str | None = None) -> Path:
    ws = tmp_path / "ws"
    write_workspace_toml(
        ws,
        project_name="lab",
        creator_name="Alice",
        creator_email="alice@example.com",
        created_at="2026-05-12T00:00:00+00:00",
    )
    if minimum is not None:
        target = ws / WORKSPACE_TOML_FILENAME
        target.write_text(
            target.read_text(encoding="utf-8").replace(
                f'hydromodpy_version_min = "{WORKSPACE_VERSION_MIN}"',
                f'hydromodpy_version_min = "{minimum}"',
            ),
            encoding="utf-8",
        )
    return ws


def test_write_is_idempotent(tmp_path: Path):
    target_dir = tmp_path / "ws"
    first = write_workspace_toml(
        target_dir,
        project_name="ws",
        creator_name="Bastien",
        creator_email="b@example.com",
    )
    assert first.name == WORKSPACE_TOML_FILENAME
    first_content = first.read_text(encoding="utf-8")

    second = write_workspace_toml(
        target_dir,
        project_name="overridden",
        creator_name="X",
        creator_email="x@example.com",
    )
    assert second == first
    assert second.read_text(encoding="utf-8") == first_content


VERSIONS = [
    pytest.param(WORKSPACE_VERSION_MIN, "2.0.0", True, id="current minimum, same version"),
    pytest.param(WORKSPACE_VERSION_MIN, "2.0.0a5", True, id="prerelease of the minimum"),
    pytest.param(WORKSPACE_VERSION_MIN, "2.3.1", True, id="newer install"),
    pytest.param("2.0.1", "2.0.1rc1", True, id="release candidate opens"),
    pytest.param("2.0.1", "2.0.0", False, id="install too old"),
    pytest.param("3.0.0", "2.9.0", False, id="next major"),
]


@pytest.mark.parametrize(("minimum", "installed", "opens"), VERSIONS)
def test_minimum_version_check(tmp_path, monkeypatch, minimum, installed, opens):
    ws = scaffold_workspace(tmp_path, minimum)
    monkeypatch.setattr(workspace_toml, "HYDROMODPY_VERSION", installed)

    if opens:
        assert load_workspace_toml(ws).workspace.hydromodpy_version_min == minimum
        return
    with pytest.raises(SchemaVersionMismatchError) as refused:
        load_workspace_toml(ws)
    assert minimum in str(refused.value) and installed in str(refused.value)


def test_newer_workspace_is_refused_in_a_config(tmp_path: Path):
    ws = scaffold_workspace(tmp_path, "99.0.0")
    (ws / "projects" / "p").mkdir(parents=True)
    (ws / "data").mkdir()
    with pytest.raises(SchemaVersionMismatchError, match="99.0.0"):
        WorkspaceConfig(project_root=ws / "projects" / "p")


def test_newer_workspace_is_refused_by_a_command(tmp_path: Path):
    ws = scaffold_workspace(tmp_path, "99.0.0")
    with pytest.raises(SchemaVersionMismatchError, match="99.0.0"):
        refuse_a_newer_workspace(ws)


def test_minimum_that_is_no_version_is_refused(tmp_path: Path):
    ws = scaffold_workspace(tmp_path, "soon")
    with pytest.raises(ValidationError, match="not a version"):
        load_workspace_toml(ws)


def test_unknown_top_level_block_is_refused(tmp_path: Path):
    ws = scaffold_workspace(tmp_path)
    toml_path = ws / WORKSPACE_TOML_FILENAME
    toml_path.write_text(
        toml_path.read_text(encoding="utf-8") + '\n[unexpected]\nfoo = "bar"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_workspace_toml(ws)


def test_missing_file_is_refused(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_workspace_toml(tmp_path / "absent")


def test_template_has_its_placeholders():
    assert "[workspace]" in DEFAULT_WORKSPACE_TOML_TEMPLATE
    assert "{project_name}" in DEFAULT_WORKSPACE_TOML_TEMPLATE


def test_rewrite_keeps_the_content(tmp_path: Path):
    ws = scaffold_workspace(tmp_path)
    first = load_workspace_toml(ws)
    write_workspace_toml(
        ws, project_name="lab", creator_name="Alice", creator_email="alice@example.com"
    )
    second = load_workspace_toml(ws)
    assert first.workspace.name == second.workspace.name
    assert first.workspace.contact == second.workspace.contact
    assert first.workspace.created_at == second.workspace.created_at
    assert first.workspace.team.members == second.workspace.team.members


def test_model_is_frozen():
    parsed = WorkspaceToml.model_validate(
        {
            "workspace": {
                "name": "lab",
                "contact": "x@y.z",
                "created_at": "2026-05-12T00:00:00+00:00",
            }
        }
    )
    with pytest.raises(ValidationError):
        parsed.workspace.name = "other"  # type: ignore[misc]
