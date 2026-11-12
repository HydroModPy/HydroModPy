"""``workspace.toml`` template generator + Pydantic loader tests."""

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


def test_write_workspace_toml_idempotent(tmp_path: Path):
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


@pytest.mark.parametrize(
    ("minimum", "installed", "opens"),
    [
        (WORKSPACE_VERSION_MIN, "2.0.0", True),
        (WORKSPACE_VERSION_MIN, "2.0.0a5", True),
        (WORKSPACE_VERSION_MIN, "2.3.1", True),
        ("2.1.0", "2.1.0rc1", True),
        ("2.1.0", "2.0.9", False),
        ("3.0.0", "2.9.0", False),
    ],
)
def test_the_minimum_version_is_compared_with_the_installed_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, minimum: str, installed: str, opens: bool
):
    ws = _scaffold_workspace(tmp_path)
    target = ws / WORKSPACE_TOML_FILENAME
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            f'hydromodpy_version_min = "{WORKSPACE_VERSION_MIN}"',
            f'hydromodpy_version_min = "{minimum}"',
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(workspace_toml, "HYDROMODPY_VERSION", installed)

    if opens:
        assert load_workspace_toml(ws).workspace.hydromodpy_version_min == minimum
        return
    with pytest.raises(SchemaVersionMismatchError) as refused:
        load_workspace_toml(ws)
    assert minimum in str(refused.value) and installed in str(refused.value)


@pytest.mark.parametrize(
    "build",
    [
        lambda ws: WorkspaceConfig(project_root=ws / "projects" / "p"),
        lambda ws: refuse_a_newer_workspace(ws),
    ],
    ids=["a config of a project", "a command on the workspace"],
)
def test_a_workspace_that_asks_for_more_is_refused_before_any_work(tmp_path: Path, build):
    ws = _scaffold_workspace(tmp_path)
    (ws / "projects" / "p").mkdir(parents=True)
    (ws / "data").mkdir()
    target = ws / WORKSPACE_TOML_FILENAME
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            f'hydromodpy_version_min = "{WORKSPACE_VERSION_MIN}"',
            'hydromodpy_version_min = "99.0.0"',
        ),
        encoding="utf-8",
    )

    with pytest.raises(SchemaVersionMismatchError, match="99.0.0"):
        build(ws)


def test_a_minimum_that_is_no_version_is_refused(tmp_path: Path):
    ws = _scaffold_workspace(tmp_path)
    target = ws / WORKSPACE_TOML_FILENAME
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            f'hydromodpy_version_min = "{WORKSPACE_VERSION_MIN}"',
            'hydromodpy_version_min = "soon"',
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="not a version"):
        load_workspace_toml(ws)


def test_template_constant_is_exported():
    assert "[workspace]" in DEFAULT_WORKSPACE_TOML_TEMPLATE
    assert "{project_name}" in DEFAULT_WORKSPACE_TOML_TEMPLATE


# ---------------------------------------------------------------------------
# Pydantic validation at load
# ---------------------------------------------------------------------------


def _scaffold_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    write_workspace_toml(
        ws,
        project_name="lab",
        creator_name="Alice",
        creator_email="alice@example.com",
        created_at="2026-05-12T00:00:00+00:00",
    )
    return ws


def test_load_workspace_toml_rejects_unknown_top_level_block(tmp_path: Path):
    ws = _scaffold_workspace(tmp_path)
    toml_path = ws / WORKSPACE_TOML_FILENAME
    toml_path.write_text(
        toml_path.read_text(encoding="utf-8") + '\n[unexpected]\nfoo = "bar"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_workspace_toml(ws)


def test_load_roundtrip_preserves_content(tmp_path: Path):
    ws = _scaffold_workspace(tmp_path)
    first = load_workspace_toml(ws)
    # Re-write the same file (no force, idempotent) then reload.
    write_workspace_toml(
        ws,
        project_name="lab",
        creator_name="Alice",
        creator_email="alice@example.com",
    )
    second = load_workspace_toml(ws)
    assert first.workspace.name == second.workspace.name
    assert first.workspace.contact == second.workspace.contact
    assert first.workspace.created_at == second.workspace.created_at
    assert first.workspace.team.members == second.workspace.team.members


def test_load_workspace_toml_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_workspace_toml(tmp_path / "absent")


def test_workspace_toml_model_frozen():
    """The validated model is immutable (frozen=True)."""
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
